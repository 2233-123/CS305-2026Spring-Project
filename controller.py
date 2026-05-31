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
from os_ken.lib.packet import ethernet
from os_ken.lib.packet import ipv4
from os_ken.lib.packet import packet
from os_ken.lib.packet import udp
from dhcp import DHCPServer
from collections import defaultdict
import time
from ofctl_utilis import OfCtl,OfCtl_v1_0,OfCtl_after_v1_2,VLANID_NONE
from ofctl_utilis import ipv4_text_to_int
import logging
import copy
import heapq
from firewall import Firewall
import struct
from os_ken.lib import hub


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
        hub.spawn(DHCPServer._lease_reaper)

    def _install_table_miss(self, datapath):
        ofctl = OfCtl.factory(datapath, self.logger)
        self.ofctls[datapath.id] = ofctl
        self.switches[datapath.id] = datapath
        ofctl.set_packetin_flow(cookie=0, priority=0)

    def _dijkstra(self, src_dpid):
        dist = {d: float('inf') for d in self.switches}
        prev = {d: None for d in self.switches}
        dist[src_dpid] = 0
        pq = [(0, src_dpid)]
        while pq:
            d, u = heapq.heappop(pq)
            if d != dist[u]:
                continue
            for v, port in self.adjacency[u].items():
                alt = d + 1
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u
                    heapq.heappush(pq, (alt, v))
        return dist, prev

    def _get_next_hop(self, src_dpid, dst_dpid):
        if src_dpid == dst_dpid:
            return None
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

    def _install_host_flows(self):
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

    def _probe_loop(self):
        while True:
            hub.sleep(2)
            self._install_probe_flows()
            for dpid, datapath in list(self.switches.items()):
                for port_no in range(1, 5):
                    self._send_probe(datapath, port_no)

    def _start_probe(self):
        hub.spawn(self._probe_loop)

    def _delayed_firewall(self, datapath):
        hub.sleep(0.5)
        self._install_firewall_rules(datapath)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self._install_table_miss(datapath)
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
        if host_mac and host_ip and host_port:
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
            'src_dpid': link.src.dp.id,
            'dst_dpid': link.dst.dp.id,
            'src_port': 0,
            'dst_port': 0,
        })
        self._update_topology()
        self._install_host_flows()

    @set_ev_cls(event.EventLinkDelete)
    def handle_link_delete(self, ev):
        link = ev.link
        self.links = [l for l in self.links
                      if not (l['src_dpid'] == link.src.dp.id and
                              l['dst_dpid'] == link.dst.dp.id)]
        self._update_topology()
        self._install_host_flows()

    @set_ev_cls(event.EventPortModify)
    def handle_port_modify(self, ev):
        pass

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

            if len(msg.data) >= 14:
                eth_type = struct.unpack('!H', msg.data[12:14])[0]
                if eth_type == self.PROBE_ETH_TYPE:
                    src_dpid, src_port_no = self._parse_probe(msg.data)
                    if src_dpid is not None and src_port_no is not None:
                        local_dpid = datapath.id
                        local_port = inPort
                        link_key = (min(local_dpid, src_dpid), max(local_dpid, src_dpid))
                        known = any(
                            min(l['src_dpid'], l['dst_dpid']) == link_key[0] and
                            max(l['src_dpid'], l['dst_dpid']) == link_key[1]
                            for l in self.links
                        )
                        if not known:
                            self.links.append({
                                'src_dpid': src_dpid,
                                'dst_dpid': local_dpid,
                                'src_port': src_port_no,
                                'dst_port': local_port,
                            })
                            self._update_topology()
                            self._install_host_flows()
                    return

            pkt_arp = pkt.get_protocol(arp.arp)
            if pkt_arp:
                if pkt_arp.opcode == arp.ARP_REQUEST:
                    target_ip = pkt_arp.dst_ip
                    if target_ip in self.ip_to_mac:
                        target_mac = self.ip_to_mac[target_ip]
                        eth = pkt.get_protocol(ethernet.ethernet)
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
                    src_mac = pkt_arp.src_mac
                    src_ip = pkt_arp.src_ip
                    if src_mac and src_ip:
                        if src_ip not in self.ip_to_mac or self.hosts.get(src_mac, {}).get('dpid') != datapath.id:
                            self.ip_to_mac[src_ip] = src_mac
                            self.mac_to_ip[src_mac] = src_ip
                            self.hosts[src_mac] = {
                                'ip': src_ip,
                                'dpid': datapath.id,
                                'port': inPort,
                            }
                            self.port_to_mac[(datapath.id, inPort)] = src_mac
                            self._install_host_flows()
            return
        except Exception as e:
            self.logger.error(e)
