"""SNAT (Source NAT / Masquerading) module for SDN controller.

Performs stateful source-address rewriting for hosts on an internal
network accessing external destinations.  Installs bidirectional OpenFlow
flows to offload established connections to the data plane.
"""

import struct
import socket
import time
import logging

from os_ken.lib import hub
from os_ken.lib import addrconv

_logger = logging.getLogger(__name__)

PROTO_ICMP = 1
PROTO_TCP = 6
PROTO_UDP = 17

TCP_STATE_NEW = 'NEW'
TCP_STATE_ESTABLISHED = 'ESTABLISHED'
TCP_STATE_CLOSING = 'CLOSING'

DNS_PRIORITY = 55000
NAT_PRIORITY = 50000
NAT_COOKIE = 0x14A7


class NATConfig:
    external_ip = '10.0.2.15'
    internal_network = '192.168.1.0/24'
    internal_prefix = 24
    controller_mac = '7e:49:b3:f0:f9:99'
    tcp_timeout = 300
    udp_timeout = 30
    icmp_timeout = 60
    gc_interval = 30


def _ip_to_int(ip):
    return struct.unpack('!I', socket.inet_aton(ip))[0]


def _int_to_ip(i):
    return socket.inet_ntoa(struct.pack('!I', i & 0xFFFFFFFF))


def _ip_in_network(ip, network, prefix):
    ip_int = _ip_to_int(ip)
    net_int = _ip_to_int(network)
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    return (ip_int & mask) == (net_int & mask)


def _checksum(data):
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def _parse_eth_ip(raw, offset=0):
    """Parse Ethernet + IP headers, return dict of fields and protocol offset."""
    if len(raw) < offset + 14 + 20:
        return None
    eth_type = struct.unpack('!H', raw[offset + 12:offset + 14])[0]
    if eth_type != 0x0800:
        return None
    ip_ver_ihl = raw[offset + 14]
    ip_ihl = (ip_ver_ihl & 0x0F) * 4
    if ip_ihl < 20 or len(raw) < offset + 14 + ip_ihl:
        return None
    proto = raw[offset + 23]
    src_ip_b = raw[offset + 26:offset + 30]
    dst_ip_b = raw[offset + 30:offset + 34]
    total_len = struct.unpack('!H', raw[offset + 16:offset + 18])[0]
    return {
        'src_mac': raw[offset:offset + 6],
        'dst_mac': raw[offset + 6:offset + 12],
        'src_ip': socket.inet_ntoa(src_ip_b),
        'dst_ip': socket.inet_ntoa(dst_ip_b),
        'proto': proto,
        'ip_ihl': ip_ihl,
        'total_len': total_len,
        'l4_offset': offset + 14 + ip_ihl,
        'eth_header': raw[offset:offset + 14],
    }


class NATTable:
    _connections = {}
    _port_index = {}
    _next_port = 1024

    @classmethod
    def _alloc_port(cls):
        port = cls._next_port
        cls._next_port = port + 1 if port + 1 < 65535 else 1024
        while port in cls._port_index:
            port = cls._next_port
            cls._next_port = port + 1 if port + 1 < 65535 else 1024
        return port

    @classmethod
    def _conn_key(cls, src_ip, src_port, dst_ip, dst_port, proto):
        if proto == PROTO_TCP or proto == PROTO_UDP:
            return (src_ip, src_port, dst_ip, dst_port, proto)
        elif proto == PROTO_ICMP:
            return (src_ip, src_port, dst_ip, dst_port, proto)

    @classmethod
    def _create_entry(cls, src_ip, src_port, dst_ip, dst_port, proto, nat_ip, src_mac=b'', nat_port=None):
        if nat_port is None:
            nat_port = cls._alloc_port()
        now = time.time()
        key = cls._conn_key(src_ip, src_port, dst_ip, dst_port, proto)
        entry = {
            'src_ip': src_ip,
            'src_port': src_port,
            'dst_ip': dst_ip,
            'dst_port': dst_port,
            'proto': proto,
            'nat_ip': nat_ip,
            'nat_port': nat_port,
            'src_mac': src_mac,
            'state': TCP_STATE_ESTABLISHED if proto != PROTO_TCP else TCP_STATE_NEW,
            'created_at': now,
            'last_seen': now,
        }
        cls._connections[key] = entry
        cls._port_index[nat_port] = key
        _logger.info("[NAT] New entry: %s:%s -> %s:%s via %s:%s",
                     src_ip, src_port, dst_ip, dst_port, nat_ip, nat_port)
        return entry

    @classmethod
    def _lookup_outbound(cls, src_ip, src_port, dst_ip, dst_port, proto):
        key = cls._conn_key(src_ip, src_port, dst_ip, dst_port, proto)
        entry = cls._connections.get(key)
        if entry:
            entry['last_seen'] = time.time()
        return entry

    @classmethod
    def _lookup_inbound(cls, nat_ip, nat_port, proto):
        key = cls._port_index.get(nat_port)
        if key and key[4] == proto:
            entry = cls._connections.get(key)
            if entry and entry['nat_ip'] == nat_ip:
                entry['last_seen'] = time.time()
                return entry
        return None

    @classmethod
    def _update_tcp_state(cls, entry, flags):
        if entry['proto'] != PROTO_TCP:
            return
        if flags & 0x01:  # FIN
            entry['state'] = TCP_STATE_CLOSING
        elif flags & 0x04:  # RST
            entry['state'] = TCP_STATE_CLOSING
        elif flags & 0x02 and not (flags & 0x10) and entry['state'] == TCP_STATE_NEW:  # SYN only
            pass  # stay in NEW
        elif flags & 0x02 and flags & 0x10:  # SYN+ACK
            entry['state'] = TCP_STATE_ESTABLISHED
        elif flags & 0x10 and entry['state'] == TCP_STATE_NEW:  # ACK after SYN
            entry['state'] = TCP_STATE_ESTABLISHED

    # ------------------------------------------------------------------
    # packet rewriting
    # ------------------------------------------------------------------
    @classmethod
    def _rewrite_outbound(cls, raw, info, entry, dst_mac=None):
        """Rewrite src IP -> nat_ip, src port -> nat_port, src mac -> controller mac,
        and optionally dst mac -> external host's real mac."""
        data = bytearray(raw)
        ip_offset = 14
        l4_offset = ip_offset + info['ip_ihl']

        # Ethernet src -> controller mac
        from os_ken.lib import addrconv
        ctrl_mac = addrconv.mac.text_to_bin(NATConfig.controller_mac)
        data[6:12] = ctrl_mac

        # Ethernet dst -> external host's real mac (in case internal host used gateway MAC)
        if dst_mac:
            data[0:6] = dst_mac

        # IP src -> nat_ip
        nat_ip_b = socket.inet_aton(entry['nat_ip'])
        data[26:30] = nat_ip_b

        # Recalc IP checksum
        data[24] = 0
        data[25] = 0
        ip_csum = _checksum(data[ip_offset:l4_offset])
        data[24] = (ip_csum >> 8) & 0xFF
        data[25] = ip_csum & 0xFF

        proto = info['proto']

        if proto == PROTO_TCP:
            src_port_off = l4_offset
            struct.pack_into('!H', data, src_port_off, entry['nat_port'])
            # Clear TCP checksum
            data[l4_offset + 16] = 0
            data[l4_offset + 17] = 0
            # Recalc TCP checksum with pseudo-header
            orig_dst_ip_b = socket.inet_aton(entry['dst_ip'])
            tcp_hdr_len = ((data[l4_offset + 12] >> 4) & 0x0F) * 4
            tcp_seg = data[l4_offset:l4_offset + tcp_hdr_len]
            tcp_payload = data[l4_offset + tcp_hdr_len:]
            pseudo = nat_ip_b + orig_dst_ip_b + struct.pack('!BBH', 0, PROTO_TCP,
                                                             len(tcp_seg) + len(tcp_payload))
            tcp_csum = _checksum(pseudo + tcp_seg[:16] + b'\x00\x00' + tcp_seg[18:] + tcp_payload)
            data[l4_offset + 16] = (tcp_csum >> 8) & 0xFF
            data[l4_offset + 17] = tcp_csum & 0xFF
            # Track TCP flags
            flags = data[l4_offset + 13] & 0x3F if len(data) > l4_offset + 13 else 0
            cls._update_tcp_state(entry, flags)

        elif proto == PROTO_UDP:
            src_port_off = l4_offset
            struct.pack_into('!H', data, src_port_off, entry['nat_port'])
            # Clear UDP checksum (optional in IPv4, set to 0 to disable)
            data[l4_offset + 6] = 0
            data[l4_offset + 7] = 0
            # Recalc UDP checksum
            orig_dst_ip_b = socket.inet_aton(entry['dst_ip'])
            udp_len = struct.unpack('!H', data[l4_offset + 4:l4_offset + 6])[0]
            pseudo = nat_ip_b + orig_dst_ip_b + struct.pack('!BBH', 0, PROTO_UDP, udp_len)
            udp_csum = _checksum(pseudo + data[l4_offset:l4_offset + udp_len])
            if udp_csum == 0:
                udp_csum = 0xFFFF
            data[l4_offset + 6] = (udp_csum >> 8) & 0xFF
            data[l4_offset + 7] = udp_csum & 0xFF

        elif proto == PROTO_ICMP:
            icmp_csum_off = l4_offset + 2
            data[icmp_csum_off] = 0
            data[icmp_csum_off + 1] = 0
            icmp_data = data[l4_offset:]
            icmp_csum = _checksum(icmp_data)
            data[icmp_csum_off] = (icmp_csum >> 8) & 0xFF
            data[icmp_csum_off + 1] = icmp_csum & 0xFF

        return bytes(data)

    @classmethod
    def _rewrite_inbound(cls, raw, info, entry):
        """Rewrite dst IP -> orig_src_ip, dst port -> orig_src_port, dst mac -> orig_src_mac."""
        data = bytearray(raw)
        from os_ken.lib import addrconv

        ip_offset = 14
        l4_offset = ip_offset + info['ip_ihl']

        # Ethernet dst -> original internal host MAC
        src_host_mac = entry.get('src_mac', b'')
        if src_host_mac:
            data[0:6] = src_host_mac
        else:
            ctrl_mac = addrconv.mac.text_to_bin(NATConfig.controller_mac)
            data[0:6] = ctrl_mac

        # IP dst -> original internal IP
        src_ip_b = socket.inet_aton(entry['src_ip'])
        data[30:34] = src_ip_b

        # Recalc IP checksum
        data[24] = 0
        data[25] = 0
        ip_csum = _checksum(data[ip_offset:l4_offset])
        data[24] = (ip_csum >> 8) & 0xFF
        data[25] = ip_csum & 0xFF

        nat_ip_b = socket.inet_aton(entry['nat_ip'])

        proto = info['proto']

        if proto == PROTO_TCP:
            dst_port_off = l4_offset + 2
            struct.pack_into('!H', data, dst_port_off, entry['src_port'])
            data[l4_offset + 16] = 0
            data[l4_offset + 17] = 0
            orig_src_ip_b = socket.inet_aton(entry['dst_ip'])
            tcp_hdr_len = ((data[l4_offset + 12] >> 4) & 0x0F) * 4
            tcp_seg = data[l4_offset:l4_offset + tcp_hdr_len]
            tcp_payload = data[l4_offset + tcp_hdr_len:]
            pseudo = orig_src_ip_b + src_ip_b + struct.pack('!BBH', 0, PROTO_TCP,
                                                             len(tcp_seg) + len(tcp_payload))
            tcp_csum = _checksum(pseudo + tcp_seg[:16] + b'\x00\x00' + tcp_seg[18:] + tcp_payload)
            data[l4_offset + 16] = (tcp_csum >> 8) & 0xFF
            data[l4_offset + 17] = tcp_csum & 0xFF
            # Track TCP flags
            flags = data[l4_offset + 13] & 0x3F if len(data) > l4_offset + 13 else 0
            cls._update_tcp_state(entry, flags)

        elif proto == PROTO_UDP:
            dst_port_off = l4_offset + 2
            struct.pack_into('!H', data, dst_port_off, entry['src_port'])
            # Clear and recalc UDP checksum
            data[l4_offset + 6] = 0
            data[l4_offset + 7] = 0
            orig_src_ip_b = socket.inet_aton(entry['dst_ip'])
            udp_len = struct.unpack('!H', data[l4_offset + 4:l4_offset + 6])[0]
            pseudo = orig_src_ip_b + src_ip_b + struct.pack('!BBH', 0, PROTO_UDP, udp_len)
            udp_csum = _checksum(pseudo + data[l4_offset:l4_offset + udp_len])
            if udp_csum == 0:
                udp_csum = 0xFFFF
            data[l4_offset + 6] = (udp_csum >> 8) & 0xFF
            data[l4_offset + 7] = udp_csum & 0xFF

        elif proto == PROTO_ICMP:
            icmp_csum_off = l4_offset + 2
            data[icmp_csum_off] = 0
            data[icmp_csum_off + 1] = 0
            icmp_csum = _checksum(data[l4_offset:])
            data[icmp_csum_off] = (icmp_csum >> 8) & 0xFF
            data[icmp_csum_off + 1] = icmp_csum & 0xFF

        return bytes(data)

    # ------------------------------------------------------------------
    # main handlers — called from controller
    # ------------------------------------------------------------------
    @classmethod
    def handle_outbound(cls, datapath, in_port, raw_data, output_port, dst_mac=None):
        """Process an outbound packet (internal -> external)."""
        info = _parse_eth_ip(raw_data)
        if info is None:
            return

        src_ip = info['src_ip']
        dst_ip = info['dst_ip']
        proto = info['proto']

        src_port = 0
        dst_port = 0
        l4_offset = info['l4_offset']

        if proto == PROTO_TCP or proto == PROTO_UDP:
            if len(raw_data) < l4_offset + 4:
                return
            src_port = struct.unpack('!H', raw_data[l4_offset:l4_offset + 2])[0]
            dst_port = struct.unpack('!H', raw_data[l4_offset + 2:l4_offset + 4])[0]
        elif proto == PROTO_ICMP:
            if len(raw_data) < l4_offset + 4:
                return
            icmp_type = raw_data[l4_offset]
            if icmp_type in (8, 0):
                src_port = struct.unpack('!H', raw_data[l4_offset + 4:l4_offset + 6])[0]
                dst_port = 0

        entry = cls._lookup_outbound(src_ip, src_port, dst_ip, dst_port, proto)
        if entry is None:
            # For ICMP, use the ICMP identifier as nat_port so inbound lookup works
            nat_port = src_port if proto == PROTO_ICMP else None
            entry = cls._create_entry(src_ip, src_port, dst_ip, dst_port, proto,
                                      NATConfig.external_ip, info['src_mac'],
                                      nat_port=nat_port)

        rewritten = cls._rewrite_outbound(raw_data, info, entry, dst_mac)
        cls._send_packet(datapath, in_port, rewritten, output_port)

    @classmethod
    def handle_inbound(cls, datapath, in_port, raw_data):
        """Process an inbound packet (external -> NAT IP).
        Returns (rewritten_data, entry) or (None, None).
        Caller is responsible for sending the rewritten packet."""
        info = _parse_eth_ip(raw_data)
        if info is None:
            return None, None

        nat_ip = info['dst_ip']
        proto = info['proto']
        nat_port = 0
        l4_offset = info['l4_offset']

        if proto == PROTO_TCP or proto == PROTO_UDP:
            if len(raw_data) < l4_offset + 4:
                return None, None
            nat_port = struct.unpack('!H', raw_data[l4_offset + 2:l4_offset + 4])[0]
        elif proto == PROTO_ICMP:
            if len(raw_data) < l4_offset + 6:
                return None, None
            icmp_type = raw_data[l4_offset]
            if icmp_type in (0, 8):
                nat_port = struct.unpack('!H', raw_data[l4_offset + 4:l4_offset + 6])[0]

        entry = cls._lookup_inbound(nat_ip, nat_port, proto)
        if entry is None:
            return None, None

        rewritten = cls._rewrite_inbound(raw_data, info, entry)
        # Debug: verify the rewritten packet checksums
        new_info = _parse_eth_ip(rewritten)
        if new_info:
            ip_hdr = rewritten[14:14 + new_info['ip_ihl']]
            ip_csum = _checksum(ip_hdr)
            tcp_ok = 'OK' if ip_csum == 0 else 'BAD(%s)' % ip_csum
            _logger.info("[NAT-IN-DBG] IP csum=%s proto=%s", tcp_ok, proto)
        return rewritten, entry

    # ------------------------------------------------------------------
    # flow installation
    # ------------------------------------------------------------------
    @classmethod
    def _install_bidirectional_flows(cls, datapath, entry, in_port, out_port):
        """Install two unidirectional flows for an established NAT connection."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        src_ip = entry['src_ip']
        dst_ip = entry['dst_ip']
        nat_ip = entry['nat_ip']
        src_port = entry['src_port']
        dst_port = entry['dst_port']
        nat_port = entry['nat_port']
        proto = entry['proto']
        idle_timeout = NATConfig.tcp_timeout if proto == PROTO_TCP else NATConfig.udp_timeout

        try:
            src_ip_int = _ip_to_int(src_ip)
            dst_ip_int = _ip_to_int(dst_ip)
            nat_ip_int = _ip_to_int(nat_ip)
            nat_ip_mac_b = addrconv.mac.text_to_bin(NATConfig.controller_mac)
            ctrl_mac_b = addrconv.mac.text_to_bin(NATConfig.controller_mac)
        except Exception as e:
            _logger.error("[NAT] IP conversion error: %s", e)
            return

        # Forward: internal -> external
        fw = ofproto.OFPFW_ALL & ~ofproto.OFPFW_DL_TYPE
        wildcards_src = (32 - 32) << ofproto.OFPFW_NW_SRC_SHIFT | ~ofproto.OFPFW_NW_SRC_MASK
        wildcards_dst = (32 - 32) << ofproto.OFPFW_NW_DST_SHIFT | ~ofproto.OFPFW_NW_DST_MASK
        fw &= wildcards_src
        fw &= wildcards_dst
        fw &= ~ofproto.OFPFW_NW_PROTO
        fw &= ~ofproto.OFPFW_TP_SRC
        fw &= ~ofproto.OFPFW_TP_DST

        fwd_match = parser.OFPMatch(
            fw, 0, 0, 0, 0, 0,
            0x0800, 0, proto,
            src_ip_int, dst_ip_int, src_port, dst_port,
        )
        fwd_actions = [
            parser.OFPActionSetNwSrc(nat_ip_int),
        ]
        if proto != PROTO_ICMP:
            fwd_actions.append(parser.OFPActionSetTpSrc(nat_port))
        fwd_actions.append(parser.OFPActionOutput(out_port, 0))

        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, match=fwd_match, cookie=NAT_COOKIE,
            command=ofproto.OFPFC_ADD, priority=NAT_PRIORITY,
            idle_timeout=idle_timeout,
            actions=fwd_actions, buffer_id=ofproto.OFP_NO_BUFFER,
        ))

        # Reverse: external -> internal
        rw = ofproto.OFPFW_ALL & ~ofproto.OFPFW_DL_TYPE
        rw &= wildcards_src
        rw &= wildcards_dst
        rw &= ~ofproto.OFPFW_NW_PROTO
        rw &= ~ofproto.OFPFW_TP_SRC
        rw &= ~ofproto.OFPFW_TP_DST

        rev_match = parser.OFPMatch(
            rw, 0, 0, 0, 0, 0,
            0x0800, 0, proto,
            dst_ip_int, nat_ip_int, dst_port, nat_port,
        )
        rev_actions = [
            parser.OFPActionSetNwDst(src_ip_int),
        ]
        if proto != PROTO_ICMP:
            rev_actions.append(parser.OFPActionSetTpDst(src_port))
        rev_actions.append(parser.OFPActionOutput(in_port, 0))

        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, match=rev_match, cookie=NAT_COOKIE,
            command=ofproto.OFPFC_ADD, priority=NAT_PRIORITY,
            idle_timeout=idle_timeout,
            actions=rev_actions, buffer_id=ofproto.OFP_NO_BUFFER,
        ))

    # ------------------------------------------------------------------
    # install capture flows (called at switch connect)
    # ------------------------------------------------------------------
    @classmethod
    def install_capture_flows(cls, datapath):
        """Install flows that send NAT-relevant packets to the controller."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        from ofctl_utilis import ipv4_text_to_int

        # Outbound: match packets going to external network
        # /24 match: wildcard last 8 bits
        net_prefix = NATConfig.internal_prefix
        net_ip = NATConfig.internal_network.split('/')[0]
        ext_ip = NATConfig.external_ip

        # Capture packets going to external IPs (not in internal network)
        # Actually, we match packets destined for external IP specifically
        # Use a broad match: nw_dst != internal_network gets sent to controller
        # But OpenFlow 1.0 can't do negation. So we use:
        #   - Higher-priority exact match for internal-to-internal (forwarding prio 10)
        #   - Lower-priority wildcard match for everything else
        # Since we need to capture specific traffic, let's install:
        # 1. Match nw_dst = external_ip/32 (inbound capture)
        ext_ip_int = ipv4_text_to_int(ext_ip)
        wildcards_ext = ofproto.OFPFW_ALL & ~ofproto.OFPFW_DL_TYPE
        v = (32 - 32) << ofproto.OFPFW_NW_DST_SHIFT | ~ofproto.OFPFW_NW_DST_MASK
        wildcards_ext &= v
        match_out = parser.OFPMatch(
            wildcards_ext, 0, 0, 0, 0, 0,
            0x0800, 0, 0,
            0, ext_ip_int, 0, 0,
        )
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 0xffff)]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, match=match_out, cookie=NAT_COOKIE,
            command=ofproto.OFPFC_ADD, priority=NAT_PRIORITY,
            actions=actions, buffer_id=ofproto.OFP_NO_BUFFER,
        ))

        # 2. Match all non-internal traffic for outbound capture
        # Actually, since we can't negate, let's capture all IP traffic
        # not matching internal-to-internal. We'll catch everything
        # via the table-miss or a broader rule.
        # But the existing table-miss already sends everything to controller.
        # So we just need: inbound match (above) + the table-miss handles outbound.
        # However, to avoid affecting performance, let's NOT add a broad outbound
        # capture - the table-miss will handle it for the first packet of each flow.
        pass

    # ------------------------------------------------------------------
    # garbage collector
    # ------------------------------------------------------------------
    @classmethod
    def _gc(cls):
        while True:
            hub.sleep(NATConfig.gc_interval)
            now = time.time()
            to_remove = []
            for key, entry in list(cls._connections.items()):
                timeout = NATConfig.tcp_timeout if entry['proto'] == PROTO_TCP else \
                          NATConfig.udp_timeout if entry['proto'] == PROTO_UDP else \
                          NATConfig.icmp_timeout
                if entry['state'] == TCP_STATE_CLOSING:
                    timeout = 30
                if now - entry['last_seen'] > timeout:
                    to_remove.append(key)
            for key in to_remove:
                entry = cls._connections.pop(key, None)
                if entry:
                    cls._port_index.pop(entry['nat_port'], None)
                    _logger.info("[NAT] Removed expired entry: %s:%s -> %s:%s",
                                 entry['src_ip'], entry['src_port'],
                                 entry['dst_ip'], entry['dst_port'])

    # ------------------------------------------------------------------
    # send helper
    # ------------------------------------------------------------------
    @classmethod
    def _send_packet(cls, datapath, in_port, data, output_port):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        if output_port is None:
            output_port = ofproto.OFPP_ALL
        actions = [parser.OFPActionOutput(port=output_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)
