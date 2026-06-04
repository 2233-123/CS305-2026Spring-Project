from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.topology import event
from os_ken.topology.switches import Switch, Host, HostState, Port, PortState, PortData, PortDataState, Link, LinkState
from os_ken.topology.switches import Switches
from os_ken.ofproto import ofproto_v1_0, ether, inet
from os_ken.lib.packet import packet, ethernet, ether_types, arp
from os_ken.lib.packet import dhcp
from os_ken.lib.packet import ipv4
from os_ken.lib.packet import udp
from dhcp import DHCPServer, DHCPConfig
from dns_server import DNSServer, DNSConfig
from nat import NATTable, NATConfig, NAT_COOKIE, NAT_PRIORITY, _ip_in_network
from collections import defaultdict
import time
from ofctl_utilis import OfCtl,OfCtl_v1_0,OfCtl_after_v1_2,VLANID_NONE
from ofctl_utilis import ipv4_text_to_int
import logging
import copy
import heapq
import json
import os
from firewall import Firewall
import struct
from os_ken.lib import hub

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False


class ControllerApp(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ControllerApp, self).__init__(*args, **kwargs)
        self.hosts = {}
        self.host_ports = {}
        self.switches = {}
        self.links = []
        self.adjacency = defaultdict(dict)
        self.ofctls = {}
        self.ip_to_mac = {}
        self.mac_to_ip = {}
        self.port_to_mac = {}
        self.firewall = Firewall()
        self.link_weights = {}
        self.routing_algorithm = 'dijkstra'
        self._load_weights()
        self._load_routing_config()
        hub.spawn(DHCPServer._lease_reaper)
        hub.spawn(NATTable._gc)
        self._load_nat_config()
        self._register_gateway_arp()

    def _load_weights(self):
        path = 'link_weights.json'
        if not os.path.exists(path):
            self.logger.info("[Routing] link_weights.json not found, using default weight=1")
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            for entry in data.get('weights', []):
                pair = tuple(sorted(entry['switch_pair']))
                self.link_weights[pair] = entry['weight']
            self.logger.info("[Routing] Link weights: %s", dict(self.link_weights))
        except Exception as e:
            self.logger.error("[Routing] Failed to load weights: %s", e)

    def _load_routing_config(self):
        path = 'routing_config.json'
        if not os.path.exists(path):
            self.logger.info("[Routing] routing_config.json not found, using default: dijkstra")
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            algo = data.get('algorithm', 'dijkstra').lower().strip()
            if algo in ('dijkstra', 'bellman-ford'):
                self.routing_algorithm = algo
            else:
                self.logger.warning("[Routing] Unknown algorithm '%s', fallback to dijkstra", algo)
                self.routing_algorithm = 'dijkstra'
            self.logger.info("[Routing] Algorithm: %s", self.routing_algorithm)
        except Exception as e:
            self.logger.error("[Routing] Failed to load routing config: %s", e)

    def _load_nat_config(self):
        path = 'nat_rules.json'
        if not os.path.exists(path):
            self.logger.info("[NAT] nat_rules.json not found, using defaults")
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            for key in ('external_ip', 'internal_network', 'internal_prefix',
                        'tcp_timeout', 'udp_timeout', 'icmp_timeout'):
                if key in data:
                    if hasattr(NATConfig, key):
                        setattr(NATConfig, key, data[key])
            self.logger.info("[NAT] Config loaded: external_ip=%s, internal=%s/%s",
                             NATConfig.external_ip, NATConfig.internal_network,
                             NATConfig.internal_prefix)
        except Exception as e:
            self.logger.error("[NAT] Failed to load config: %s", e)

    def _register_gateway_arp(self):
        mac = DHCPConfig.controller_macAddr
        self.ip_to_mac[DNSConfig.controller_ip] = mac
        self.ip_to_mac[NATConfig.external_ip] = mac
        self.logger.info("[ARP] Registered gateway IPs: %s, %s -> %s",
                         DNSConfig.controller_ip, NATConfig.external_ip, mac)

    def _install_table_miss(self, datapath):
        ofctl = OfCtl.factory(datapath, self.logger)
        self.ofctls[datapath.id] = ofctl
        self.switches[datapath.id] = datapath
        DHCPServer._all_datapaths[datapath.id] = datapath
        ofctl.set_packetin_flow(cookie=0, priority=0)

    def _edge_weight(self, u, v):
        key = (min(u, v, key=lambda x: (isinstance(x, int), x)),
               max(u, v, key=lambda x: (isinstance(x, int), x)))
        return self.link_weights.get(key, 1)

    def _dijkstra(self, src_dpid):
        dist = {d: float('inf') for d in self.switches}
        prev = {d: None for d in self.switches}
        dist[src_dpid] = 0
        pq = [(0, src_dpid)]
        while pq:
            d, u = heapq.heappop(pq)
            if d != dist[u]:
                continue
            for v in self.adjacency[u]:
                weight = self._edge_weight(u, v)
                alt = d + weight
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u
                    heapq.heappush(pq, (alt, v))
        return dist, prev

    def _dijkstra_all(self, src_dpid):
        dist = {d: float('inf') for d in self.switches}
        prev = {d: [] for d in self.switches}
        dist[src_dpid] = 0
        pq = [(0, src_dpid)]
        while pq:
            d, u = heapq.heappop(pq)
            if d != dist[u]:
                continue
            for v in self.adjacency[u]:
                weight = self._edge_weight(u, v)
                alt = d + weight
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = [u]
                    heapq.heappush(pq, (alt, v))
                elif alt == dist[v]:
                    prev[v].append(u)
        return dist, prev

    def _bellman_ford(self, src_dpid):
        dist = {d: float('inf') for d in self.switches}
        prev = {d: None for d in self.switches}
        dist[src_dpid] = 0
        n = len(self.switches)
        for _ in range(n - 1):
            updated = False
            for u in self.switches:
                if dist[u] == float('inf'):
                    continue
                for v in self.adjacency[u]:
                    weight = self._edge_weight(u, v)
                    alt = dist[u] + weight
                    if alt < dist[v]:
                        dist[v] = alt
                        prev[v] = u
                        updated = True
            if not updated:
                break
        return dist, prev

    def _get_next_hop(self, src_dpid, dst_dpid):
        if src_dpid == dst_dpid:
            return None
        if self.routing_algorithm == 'bellman-ford':
            _, prev = self._bellman_ford(src_dpid)
        else:
            _, prev = self._dijkstra(src_dpid)
        curr = dst_dpid
        if prev.get(curr) is None:
            return None
        while prev.get(curr) is not None and prev[curr] != src_dpid:
            curr = prev[curr]
        if prev.get(curr) is None:
            return None
        if curr in self.adjacency.get(src_dpid, {}):
            return self.adjacency[src_dpid][curr]
        return None

    def _get_host_port(self, in_port, ip):
        """Look up the output port for a given IP address from known hosts."""
        mac = self.ip_to_mac.get(ip)
        if mac and mac in self.hosts:
            return self.hosts[mac].get('port', None)
        for host_mac, info in self.hosts.items():
            if info.get('ip') == ip:
                return info.get('port', None)
        return None

    def _log_switch_paths(self):
        switch_ids = sorted(self.switches.keys())
        if len(switch_ids) < 2:
            return
        self.logger.info("[Topology] === Switch-to-Switch Shortest Paths ===")
        for i, s_a in enumerate(switch_ids):
            for s_b in switch_ids[i + 1:]:
                path = self._build_path(s_a, s_b)
                if path is not None:
                    if self.routing_algorithm == 'bellman-ford':
                        dist, _ = self._bellman_ford(s_a)
                    else:
                        dist, _ = self._dijkstra(s_a)
                    cost = dist.get(s_b, float('inf'))
                    edges = len(path) + 1
                    self.logger.info("[Topology]   s%s -> s%s : %s, %d edges (cost=%s)",
                                     s_a, s_b,
                                     ' -> '.join(str(d) for d in [s_a] + path + [s_b]),
                                     edges, cost)
                else:
                    self.logger.info("[Topology]   s%s -> s%s : NO PATH", s_a, s_b)

    def _print_topology(self):
        self.logger.info("[Topology] === Current Topology ===")
        self.logger.info("[Topology] Switches: %s",
                         sorted(self.switches.keys()))
        self.logger.info("[Topology] Links: %s",
                         [(l['src_dpid'], l['dst_dpid']) for l in self.links])
        self.logger.info("[Topology] Hosts: %s",
                         [(info.get('ip', mac), info['dpid'], info['port'])
                          for mac, info in self.hosts.items()])
        self._log_switch_paths()
        self._log_routing_paths()
        self._print_networkx_topology()

    def _print_networkx_topology(self):
        """Print topology graph info using networkx (text-based)."""
        if not _HAS_NX:
            self.logger.info("[NetworkX] networkx not installed, skipping graph output")
            return
        try:
            G = nx.Graph()
            for dpid in self.switches:
                G.add_node(dpid, label=f's{dpid}', node_type='switch')
            for link in self.links:
                G.add_edge(link['src_dpid'], link['dst_dpid'],
                           src_port=link.get('src_port', '?'),
                           dst_port=link.get('dst_port', '?'))
            for mac, info in self.hosts.items():
                host_label = info.get('ip', mac)
                host_dpid = info['dpid']
                host_port = info['port']
                node_id = f'h_{host_label}'
                G.add_node(node_id, label=str(host_label), node_type='host')
                G.add_edge(node_id, host_dpid, port=host_port)

            self.logger.info("[NetworkX] Graph: %d nodes, %d edges",
                             G.number_of_nodes(), G.number_of_edges())
            switch_ids = sorted(self.switches.keys())
            self.logger.info("[NetworkX] Switch-to-Switch shortest paths (networkx):")
            for i, s_a in enumerate(switch_ids):
                for s_b in switch_ids[i + 1:]:
                    try:
                        path = nx.shortest_path(G, source=s_a, target=s_b,
                                                weight='weight')
                        length = len(path) - 1
                        if length > 0:
                            self.logger.info("[NetworkX]   s%s -> s%s : %s, %d edges (nx)",
                                             s_a, s_b,
                                             ' -> '.join(f's{p}' for p in path),
                                             length)
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        self.logger.info("[NetworkX]   s%s -> s%s : NO PATH (nx)", s_a, s_b)
        except Exception as e:
            self.logger.error("[NetworkX] Error: %s", e)

    def _log_routing_paths(self):
        if len(self.hosts) < 2:
            return
        self.logger.info("[Routing] === Host-to-Host Paths (algorithm: %s) ===", self.routing_algorithm)
        host_list = list(self.hosts.items())
        for i, (mac_a, info_a) in enumerate(host_list):
            for mac_b, info_b in host_list[i + 1:]:
                dpid_a, dpid_b = info_a['dpid'], info_b['dpid']
                path = self._build_path(dpid_a, dpid_b)
                if path is not None and self.routing_algorithm == 'dijkstra':
                    dist, _ = self._dijkstra(dpid_a)
                    cost = dist.get(dpid_b, float('inf'))
                elif path is not None:
                    dist, _ = self._bellman_ford(dpid_a)
                    cost = dist.get(dpid_b, float('inf'))
                else:
                    cost = float('inf')
                if path is not None:
                    self.logger.info("[Routing]   %s <-> %s : path %s, cost=%s",
                                     info_a.get('ip', mac_a), info_b.get('ip', mac_b),
                                     '->'.join(str(d) for d in [dpid_a] + path + [dpid_b]), cost)
                else:
                    self.logger.info("[Routing]   %s <-> %s : NO PATH",
                                     info_a.get('ip', mac_a), info_b.get('ip', mac_b))

    def _build_path(self, src_dpid, dst_dpid):
        if src_dpid == dst_dpid:
            return []
        if self.routing_algorithm == 'bellman-ford':
            _, prev = self._bellman_ford(src_dpid)
        else:
            _, prev = self._dijkstra(src_dpid)
        if prev.get(dst_dpid) is None:
            return None
        path = []
        curr = dst_dpid
        while curr != src_dpid:
            prev_node = prev.get(curr)
            if prev_node is None:
                return None
            path.append(curr)
            curr = prev_node
        path.reverse()
        return path[:-1]

    def _install_host_flows(self):
        self._print_topology()
        for host_mac, info in list(self.hosts.items()):
            host_dpid = info['dpid']
            host_port = info['port']
            for sw_dpid in self.switches:
                if host_mac not in self.hosts:
                    continue
                if sw_dpid == host_dpid:
                    ofctl = self.ofctls.get(sw_dpid)
                    if ofctl:
                        dp = self.switches[sw_dpid]
                        actions = [dp.ofproto_parser.OFPActionOutput(host_port)]
                        ofctl.set_flow(cookie=0x10, priority=10,
                                       dl_type=ether.ETH_TYPE_IP,
                                       dl_dst=host_mac, dl_vlan=VLANID_NONE,
                                       actions=actions)
                        ofctl.set_flow(cookie=0x10, priority=10,
                                       dl_type=ether.ETH_TYPE_ARP,
                                       dl_dst=host_mac, dl_vlan=VLANID_NONE,
                                       actions=actions)
                else:
                    port = self._get_next_hop(sw_dpid, host_dpid)
                    if port is not None:
                        ofctl = self.ofctls.get(sw_dpid)
                        if ofctl:
                            dp = self.switches[sw_dpid]
                            actions = [dp.ofproto_parser.OFPActionOutput(port)]
                            ofctl.set_flow(cookie=0x10, priority=10,
                                           dl_type=ether.ETH_TYPE_IP,
                                           dl_dst=host_mac, dl_vlan=VLANID_NONE,
                                           actions=actions)
                            ofctl.set_flow(cookie=0x10, priority=10,
                                           dl_type=ether.ETH_TYPE_ARP,
                                           dl_dst=host_mac, dl_vlan=VLANID_NONE,
                                           actions=actions)
                    else:
                        self.logger.info("[Flow] No route: sw=s%s -> host=%s(dpid=s%s)",
                                         sw_dpid, host_mac[-6:], host_dpid)

    def _install_firewall_rules(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        for rule in self.firewall.rules:
            if rule.action != 'deny':
                continue
            proto_num = self.firewall._proto_to_number(rule.proto)
            src_ip = rule.src_ip or 0
            dst_ip = rule.dst_ip or 0
            wildcards = ofproto.OFPFW_ALL
            if dl_type := (ether.ETH_TYPE_IP if proto_num or rule.src_ip or rule.dst_ip else 0):
                wildcards &= ~ofproto.OFPFW_DL_TYPE
            if proto_num:
                wildcards &= ~ofproto.OFPFW_NW_PROTO
            if rule.src_ip:
                src_ip = ipv4_text_to_int(src_ip)
                v = (32 - 32) << ofproto.OFPFW_NW_SRC_SHIFT | ~ofproto.OFPFW_NW_SRC_MASK
                wildcards &= v
            if rule.dst_ip:
                dst_ip = ipv4_text_to_int(dst_ip)
                v = (32 - 32) << ofproto.OFPFW_NW_DST_SHIFT | ~ofproto.OFPFW_NW_DST_MASK
                wildcards &= v
            tp_src = 0
            tp_dst = 0
            src_port_val = self.firewall._normalize_port(rule.src_port)
            dst_port_val = self.firewall._normalize_port(rule.dst_port)
            if src_port_val:
                tp_src = int(src_port_val)
                wildcards &= ~ofproto.OFPFW_TP_SRC
            if dst_port_val:
                tp_dst = int(dst_port_val)
                wildcards &= ~ofproto.OFPFW_TP_DST

            match = parser.OFPMatch(
                wildcards, 0, 0, 0, 0, 0,
                dl_type, 0, proto_num,
                src_ip, dst_ip, tp_src, tp_dst
            )
            flow_mod = parser.OFPFlowMod(
                datapath=datapath, match=match, cookie=self.firewall.COOKIE,
                command=ofproto.OFPFC_ADD, priority=self.firewall.PRIORITY,
                actions=[], buffer_id=ofproto.OFP_NO_BUFFER,
            )
            datapath.send_msg(flow_mod)

    def _update_topology(self):
        self.adjacency.clear()
        for link in self.links:
            src_dpid = link['src_dpid']
            dst_dpid = link['dst_dpid']
            src_port = link['src_port']
            dst_port = link['dst_port']
            self.adjacency[src_dpid][dst_dpid] = src_port
            self.adjacency[dst_dpid][src_dpid] = dst_port

    PROBE_ETH_TYPE = 0x9999

    def _send_probe(self, datapath, port_no):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        try:
            payload = struct.pack('!QH', dpid, port_no)
            dst_mac_bytes = struct.pack('!BBBBBB', 0xff, 0xff, 0xff, 0xff, 0xff, 0xff)
            src_mac_bytes = struct.pack('!BBBBBB', 0x00, 0x00, 0x00, 0x00, 0x00, port_no & 0xFF)
            eth_type_bytes = struct.pack('!H', self.PROBE_ETH_TYPE)
            pkt_data = dst_mac_bytes + src_mac_bytes + eth_type_bytes + payload
            actions = [parser.OFPActionOutput(port_no, 0)]
            out = parser.OFPPacketOut(
                datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER, actions=actions, data=pkt_data)
            datapath.send_msg(out)
        except Exception:
            pass

    def _parse_probe(self, data):
        try:
            if len(data) < 24:
                return None, None
            dpid, port_no = struct.unpack('!QH', data[14:24])
            return dpid, port_no
        except Exception:
            return None, None

    def _install_probe_flows(self):
        for dpid, datapath in list(self.switches.items()):
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            w = ofproto.OFPFW_ALL & ~ofproto.OFPFW_DL_TYPE
            match = parser.OFPMatch(w, 0, 0, 0, 0, 0, self.PROBE_ETH_TYPE, 0, 0, 0, 0, 0, 0)
            actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 0xffff)]
            datapath.send_msg(parser.OFPFlowMod(
                datapath=datapath, match=match, cookie=2,
                command=ofproto.OFPFC_ADD, priority=65000,
                actions=actions, buffer_id=ofproto.OFP_NO_BUFFER))

    def _register_arp_host(self, src_mac, src_ip, dpid, port):
        if not src_mac or not src_ip or src_ip == '0.0.0.0':
            return
        if src_mac == DHCPConfig.controller_macAddr:
            return
        if src_ip in self.ip_to_mac and self.hosts.get(src_mac, {}).get('dpid') == dpid:
            return
        self.ip_to_mac[src_ip] = src_mac
        self.mac_to_ip[src_mac] = src_ip
        self.hosts[src_mac] = {'ip': src_ip, 'dpid': dpid, 'port': port}
        self.port_to_mac[(dpid, port)] = src_mac
        self.logger.info("[ARP-Host] Registered mac=%s ip=%s dpid=%s port=%s",
                         src_mac[-6:], src_ip, dpid, port)
        self._install_host_flows()

    def _probe_loop(self):
        while True:
            hub.sleep(2)
            self._install_probe_flows()
            for dpid, datapath in list(self.switches.items()):
                for port_no in range(1, 9):
                    self._send_probe(datapath, port_no)

    def _start_probe(self):
        hub.spawn(self._probe_loop)

    def _delayed_firewall(self, datapath):
        hub.sleep(0.5)
        self._install_firewall_rules(datapath)

    def _install_dns_capture_flow(self, datapath):
        """Install flow to capture DNS queries (UDP port 53) to controller."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        w = ofproto.OFPFW_ALL & ~ofproto.OFPFW_DL_TYPE & ~ofproto.OFPFW_NW_PROTO & ~ofproto.OFPFW_TP_DST
        match = parser.OFPMatch(
            w, 0, 0, 0, 0, 0, ether.ETH_TYPE_IP, 0, inet.IPPROTO_UDP, 0, 0, 0, 53,
        )
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 0xffff)]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, match=match, cookie=0xD15C,
            command=ofproto.OFPFC_ADD, priority=55000,
            actions=actions, buffer_id=ofproto.OFP_NO_BUFFER,
        ))

    def _install_nat_capture_flow(self, datapath):
        """Install flow to capture inbound NAT packets (dst=NAT external IP)."""
        from ofctl_utilis import ipv4_text_to_int
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        ext_ip_int = ipv4_text_to_int(NATConfig.external_ip)
        w = ofproto.OFPFW_ALL & ~ofproto.OFPFW_DL_TYPE
        v = (32 - 32) << ofproto.OFPFW_NW_DST_SHIFT | ~ofproto.OFPFW_NW_DST_MASK
        w &= v
        match = parser.OFPMatch(
            w, 0, 0, 0, 0, 0, ether.ETH_TYPE_IP, 0, 0, 0, ext_ip_int, 0, 0,
        )
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 0xffff)]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, match=match, cookie=NAT_COOKIE,
            command=ofproto.OFPFC_ADD, priority=NAT_PRIORITY,
            actions=actions, buffer_id=ofproto.OFP_NO_BUFFER,
        ))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self._install_table_miss(datapath)
        self._install_dns_capture_flow(datapath)
        self._install_nat_capture_flow(datapath)
        hub.spawn(self._delayed_firewall, datapath)

    @set_ev_cls(event.EventSwitchEnter)
    def handle_switch_add(self, ev):
        datapath = ev.switch.dp
        self._install_table_miss(datapath)
        self._install_host_flows()
        if len(self.switches) == 1:
            self._start_probe()

    @set_ev_cls(event.EventSwitchLeave)
    def handle_switch_delete(self, ev):
        dpid = ev.switch.dp.id
        self.switches.pop(dpid, None)
        self.ofctls.pop(dpid, None)
        DHCPServer._all_datapaths.pop(dpid, None)
        # Remove hosts attached to this switch
        to_remove = [mac for mac, info in self.hosts.items() if info['dpid'] == dpid]
        for mac in to_remove:
            ip = self.hosts[mac]['ip']
            self.hosts.pop(mac, None)
            self.ip_to_mac.pop(ip, None)
            self.mac_to_ip.pop(mac, None)
            for key in list(self.port_to_mac.keys()):
                if self.port_to_mac[key] == mac:
                    self.port_to_mac.pop(key, None)
        self.links = [l for l in self.links
                      if l['src_dpid'] != dpid and l['dst_dpid'] != dpid]
        self._update_topology()
        self._install_host_flows()

    @set_ev_cls(event.EventHostAdd)
    def handle_host_add(self, ev):
        host = ev.host
        host_mac = host.mac
        host_ip = host.ipv4[0] if host.ipv4 else None
        host_port = host.port
        self.logger.info("[HostAdd] handle_host_add: mac=%s ip=%s dpid=%s port=%s",
                         host_mac, host_ip,
                         host_port.dpid if host_port else '?',
                         host_port.port_no if host_port else '?')
        if host_mac and host_ip and host_ip != '0.0.0.0' and host_port:
            self.hosts[host_mac] = {
                'ip': host_ip,
                'dpid': host_port.dpid,
                'port': host_port.port_no,
            }
            self.ip_to_mac[host_ip] = host_mac
            self.mac_to_ip[host_mac] = host_ip
            self.port_to_mac[(host_port.dpid, host_port.port_no)] = host_mac
            self._install_host_flows()

    @set_ev_cls(event.EventLinkAdd)
    def handle_link_add(self, ev):
        link = ev.link
        self.links.append({
            'src_dpid': link.src.dpid,
            'dst_dpid': link.dst.dpid,
            'src_port': link.src.port_no,
            'dst_port': link.dst.port_no,
        })
        self._update_topology()
        self._install_host_flows()

    @set_ev_cls(event.EventLinkDelete)
    def handle_link_delete(self, ev):
        link = ev.link
        self.links = [l for l in self.links
                      if not (l['src_dpid'] == link.src.dpid and
                              l['dst_dpid'] == link.dst.dpid)]
        self._update_topology()
        self._install_host_flows()

    @set_ev_cls(event.EventPortModify)
    def handle_port_modify(self, ev):
        port = ev.port
        dpid = port.dpid
        port_no = port.port_no

        if port.is_down():
            self.logger.info("[PortEvent] Port s%s:%s DOWN — removing affected links/hosts",
                             dpid, port_no)
            self.links = [l for l in self.links
                          if not ((l['src_dpid'] == dpid and l['src_port'] == port_no) or
                                  (l['dst_dpid'] == dpid and l['dst_port'] == port_no))]
            to_remove = [mac for mac, info in self.hosts.items()
                         if info['dpid'] == dpid and info['port'] == port_no]
            for mac in to_remove:
                ip = self.hosts[mac]['ip']
                self.hosts.pop(mac, None)
                self.ip_to_mac.pop(ip, None)
                self.mac_to_ip.pop(mac, None)
                self.port_to_mac.pop((dpid, port_no), None)
            self._update_topology()
            self._install_host_flows()
        else:
            self.logger.info("[PortEvent] Port s%s:%s UP", dpid, port_no)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        msg = ev.msg
        reason = msg.reason
        desc = msg.desc
        dpid = msg.datapath.id
        port_no = desc.port_no
        ofproto = msg.datapath.ofproto

        if reason == ofproto.OFPPR_MODIFY:
            is_down = (desc.state & ofproto.OFPPS_LINK_DOWN) > 0
            if is_down:
                self.logger.info("[PortStatus] s%s:%s OFPPR_MODIFY DOWN", dpid, port_no)
                self.links = [l for l in self.links
                              if not ((l['src_dpid'] == dpid and l['src_port'] == port_no) or
                                      (l['dst_dpid'] == dpid and l['dst_port'] == port_no))]
                self._update_topology()
                self._install_host_flows()
            else:
                self.logger.info("[PortStatus] s%s:%s OFPPR_MODIFY UP", dpid, port_no)
        elif reason == ofproto.OFPPR_DELETE:
            self.logger.info("[PortStatus] s%s:%s OFPPR_DELETE", dpid, port_no)
            self.links = [l for l in self.links
                          if not ((l['src_dpid'] == dpid and l['src_port'] == port_no) or
                                  (l['dst_dpid'] == dpid and l['dst_port'] == port_no))]
            to_remove = [mac for mac, info in self.hosts.items()
                         if info['dpid'] == dpid and info['port'] == port_no]
            for mac in to_remove:
                ip = self.hosts[mac]['ip']
                self.hosts.pop(mac, None)
                self.ip_to_mac.pop(ip, None)
                self.mac_to_ip.pop(mac, None)
                self.port_to_mac.pop((dpid, port_no), None)
            self._update_topology()
            self._install_host_flows()

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        try:
            msg = ev.msg
            datapath = msg.datapath
            pkt = packet.Packet(data=msg.data)
            pkt_dhcp = pkt.get_protocols(dhcp.dhcp)
            inPort = msg.in_port
            if pkt_dhcp:
                hub.spawn(DHCPServer.handle_dhcp, datapath, inPort, pkt)
                return

            # ---- DNS ----
            pkt_ipv4 = pkt.get_protocol(ipv4.ipv4)
            pkt_udp = pkt.get_protocol(udp.udp)
            if pkt_ipv4 and pkt_udp and pkt_udp.dst_port == 53:
                pkt_eth = pkt.get_protocol(ethernet.ethernet)
                if pkt_eth:
                    DNSServer.handle_dns(datapath, inPort, msg.data,
                                         pkt_ipv4, pkt_udp, pkt_eth)
                return

            # ---- NAT ----
            if pkt_ipv4:
                dst_ip = pkt_ipv4.dst
                if dst_ip == NATConfig.external_ip:
                    # Inbound: external host sends to NAT IP
                    target_mac = self.ip_to_mac.get(dst_ip)
                    out_port = self._get_host_port(inPort, dst_ip)
                    if out_port is None:
                        out_port = datapath.ofproto.OFPP_ALL
                    NATTable.handle_inbound(datapath, inPort, msg.data, out_port)
                    return
                elif (dst_ip != DNSConfig.controller_ip and
                      not _ip_in_network(dst_ip, NATConfig.internal_network.split('/')[0],
                                         NATConfig.internal_prefix)):
                    # Outbound: internal host sends to external IP
                    out_port = self._get_host_port(inPort, dst_ip)
                    if out_port is None:
                        out_port = datapath.ofproto.OFPP_ALL
                    NATTable.handle_outbound(datapath, inPort, msg.data, out_port)
                    return

            if len(msg.data) >= 14:
                eth_type = struct.unpack('!H', msg.data[12:14])[0]
                if eth_type == self.PROBE_ETH_TYPE:
                    src_dpid, src_port_no = self._parse_probe(msg.data)
                    if src_dpid is not None and src_port_no is not None:
                        local_dpid = datapath.id
                        local_port = inPort
                        link_key = (min(local_dpid, src_dpid), max(local_dpid, src_dpid))

                        updated = False
                        for l in self.links:
                            a, b = min(l['src_dpid'], l['dst_dpid']), max(l['src_dpid'], l['dst_dpid'])
                            if a == link_key[0] and b == link_key[1]:
                                old_src = l['src_port']
                                old_dst = l['dst_port']
                                if l['src_dpid'] == src_dpid:
                                    l['src_port'] = src_port_no
                                    l['dst_port'] = local_port
                                else:
                                    l['src_port'] = local_port
                                    l['dst_port'] = src_port_no
                                if old_src != l['src_port'] or old_dst != l['dst_port']:
                                    self.logger.info("[Probe] Updated link s%s<->s%s ports: %d<->%d",
                                                     link_key[0], link_key[1], l['src_port'], l['dst_port'])
                                updated = True
                                break

                        if not updated:
                            self.links.append({
                                'src_dpid': src_dpid,
                                'dst_dpid': local_dpid,
                                'src_port': src_port_no,
                                'dst_port': local_port,
                            })
                            self.logger.info("[Probe] New link s%s<->s%s ports: %d<->%d",
                                             src_dpid, local_dpid, src_port_no, local_port)
                            self._update_topology()
                            self._install_host_flows()
                        else:
                            self._update_topology()
                            self._install_host_flows()
                    return

            pkt_arp = pkt.get_protocol(arp.arp)
            if pkt_arp:
                if pkt_arp.opcode == arp.ARP_REQUEST:
                    eth = pkt.get_protocol(ethernet.ethernet)
                    if eth:
                        self._register_arp_host(eth.src, pkt_arp.src_ip, datapath.id, inPort)
                    target_ip = pkt_arp.dst_ip
                    if target_ip in self.ip_to_mac:
                        target_mac = self.ip_to_mac[target_ip]
                        sender_mac = eth.src

                        e = ethernet.ethernet(
                            dst=sender_mac, src=target_mac,
                            ethertype=ether.ETH_TYPE_ARP)
                        a = arp.arp(
                            hwtype=1, proto=ether.ETH_TYPE_IP, hlen=6, plen=4,
                            opcode=arp.ARP_REPLY,
                            src_mac=target_mac, src_ip=target_ip,
                            dst_mac=sender_mac, dst_ip=pkt_arp.src_ip)
                        reply_pkt = packet.Packet()
                        reply_pkt.add_protocol(e)
                        reply_pkt.add_protocol(a)
                        reply_pkt.serialize()

                        ofproto = datapath.ofproto
                        parser = datapath.ofproto_parser
                        actions = [parser.OFPActionOutput(port=inPort)]
                        out = parser.OFPPacketOut(
                            datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                            in_port=ofproto.OFPP_CONTROLLER, actions=actions,
                            data=reply_pkt.data)
                        datapath.send_msg(out)
                elif pkt_arp.opcode == arp.ARP_REPLY:
                    DHCPServer._mark_arp_conflict(pkt_arp.src_ip)
                    self._register_arp_host(pkt_arp.src_mac, pkt_arp.src_ip, datapath.id, inPort)
            return
        except Exception as e:
            self.logger.error(e)
