"""DNS server for SDN controller.

Provides A (forward) and PTR (reverse) record resolution for hosts
registered via DHCP.  Manual DNS wire-format parsing (no dnspython dependency).
"""

import struct
import socket
import logging

_logger = logging.getLogger(__name__)

QTYPE_A = 1
QTYPE_PTR = 12
QCLASS_IN = 1
RCODE_NOERROR = 0
RCODE_NXDOMAIN = 3

QR_MASK = 0x8000
AA_MASK = 0x0400
OPCODE_SHIFT = 11
OPCODE_MASK = 0x7800


class DNSConfig:
    controller_ip = '192.168.1.1'
    controller_mac = '7e:49:b3:f0:f9:99'
    ttl = 60


class DNSServer:
    _records = {}           # hostname -> ip
    _ip_to_hostname = {}    # ip -> hostname

    # ------------------------------------------------------------------
    # record management
    # ------------------------------------------------------------------
    @classmethod
    def add_record(cls, hostname, ip):
        if hostname and ip:
            old_ip = cls._records.get(hostname)
            if old_ip and old_ip != ip and cls._ip_to_hostname.get(old_ip) == hostname:
                del cls._ip_to_hostname[old_ip]
            cls._records[hostname] = ip
            cls._ip_to_hostname[ip] = hostname
            _logger.info("[DNS] Registered %s <-> %s", hostname, ip)

    @classmethod
    def remove_record(cls, hostname=None, ip=None):
        if hostname and hostname in cls._records:
            ip = cls._records.pop(hostname)
            if cls._ip_to_hostname.get(ip) == hostname:
                del cls._ip_to_hostname[ip]
        elif ip and ip in cls._ip_to_hostname:
            hostname = cls._ip_to_hostname.pop(ip)
            if cls._records.get(hostname) == ip:
                del cls._records[hostname]

    # ------------------------------------------------------------------
    # domain-name encoding helpers
    # ------------------------------------------------------------------
    @classmethod
    def _encode_domain(cls, name):
        if isinstance(name, bytes):
            return name
        result = b''
        for part in name.split('.'):
            result += struct.pack('B', len(part)) + part.encode()
        result += b'\x00'
        return result

    @classmethod
    def _decode_domain(cls, data, offset):
        labels = []
        jumped = False
        jumped_offset = None
        while True:
            if offset >= len(data):
                break
            length = data[offset]
            if length == 0:
                offset += 1
                break
            if (length & 0xC0) == 0xC0:
                pointer = struct.unpack('!H', data[offset:offset + 2])[0] & 0x3FFF
                if not jumped:
                    jumped_offset = offset + 2
                    jumped = True
                offset = pointer
                continue
            offset += 1
            labels.append(data[offset:offset + length].decode())
            offset += length
        name = '.'.join(labels)
        return name, (jumped_offset if jumped else offset)

    @classmethod
    def _ip_to_ptr_name(cls, ip_str):
        return '.'.join(reversed(ip_str.split('.'))) + '.in-addr.arpa'

    @classmethod
    def _ptr_name_to_ip(cls, name):
        if name.endswith('.in-addr.arpa'):
            name = name[:-len('.in-addr.arpa')]
        return '.'.join(reversed(name.split('.')))

    # ------------------------------------------------------------------
    # packet assembly
    # ------------------------------------------------------------------
    @classmethod
    def _build_response(cls, txid, questions, answers):
        flags = QR_MASK | AA_MASK
        if answers is None:
            flags |= RCODE_NXDOMAIN
            answers = []
        header = struct.pack('!HHHHHH',
                             txid, flags, len(questions),
                             len(answers), 0, 0)
        qsection = b''
        for qname, qtype, qclass in questions:
            qsection += cls._encode_domain(qname)
            qsection += struct.pack('!HH', qtype, qclass)
        asection = b''
        for name, atype, ttl, rdata in answers:
            asection += b'\xc0\x0c'
            asection += struct.pack('!HH', atype, QCLASS_IN)
            asection += struct.pack('!I', ttl)
            if atype == QTYPE_A:
                ip_bytes = socket.inet_aton(rdata)
                asection += struct.pack('!H', 4) + ip_bytes
            elif atype == QTYPE_PTR:
                enc = cls._encode_domain(rdata)
                asection += struct.pack('!H', len(enc)) + enc
        return header + qsection + asection

    # ------------------------------------------------------------------
    # query handling
    # ------------------------------------------------------------------
    @classmethod
    def handle_dns(cls, datapath, in_port, msg_data, pkt_ipv4, pkt_udp, pkt_eth):
        try:
            ip_header_len = (struct.unpack('!B', msg_data[14:15])[0] & 0x0F) * 4
            dns_offset = 14 + ip_header_len + 8
            if len(msg_data) < dns_offset + 12:
                return
            dns_data = msg_data[dns_offset:]

            txid = struct.unpack('!H', dns_data[0:2])[0]
            flags = struct.unpack('!H', dns_data[2:4])[0]
            qdcount = struct.unpack('!H', dns_data[4:6])[0]

            if (flags & QR_MASK) != 0:
                return
            if ((flags & OPCODE_MASK) >> OPCODE_SHIFT) != 0:
                return

            offset = 12
            questions = []
            for _ in range(qdcount):
                if offset >= len(dns_data):
                    break
                qname, offset = cls._decode_domain(dns_data, offset)
                if offset + 4 > len(dns_data):
                    break
                qtype = struct.unpack('!H', dns_data[offset:offset + 2])[0]
                qclass = struct.unpack('!H', dns_data[offset + 2:offset + 4])[0]
                offset += 4
                questions.append((qname, qtype, qclass))

            answers = []
            found = False
            for qname, qtype, qclass in questions:
                if qclass != QCLASS_IN:
                    continue
                if qtype == QTYPE_A:
                    if qname in cls._records:
                        answers.append((qname, QTYPE_A, DNSConfig.ttl, cls._records[qname]))
                        found = True
                elif qtype == QTYPE_PTR:
                    ip = cls._ptr_name_to_ip(qname)
                    if ip in cls._ip_to_hostname:
                        answers.append((qname, QTYPE_PTR, DNSConfig.ttl, cls._ip_to_hostname[ip]))
                        found = True

            selected = questions[:1] if questions else []
            resp = cls._build_response(txid, selected, answers if found else None)
            cls._send_response(datapath, in_port, pkt_ipv4, pkt_udp, pkt_eth, resp)
        except Exception as e:
            _logger.error("[DNS] handle_dns error: %s", e)

    # ------------------------------------------------------------------
    # send helper
    # ------------------------------------------------------------------
    @classmethod
    def _checksum(cls, data):
        if len(data) % 2:
            data += b'\x00'
        s = 0
        for i in range(0, len(data), 2):
            s += (data[i] << 8) + data[i + 1]
        s = (s >> 16) + (s & 0xFFFF)
        s += s >> 16
        return ~s & 0xFFFF

    @classmethod
    def _send_response(cls, datapath, in_port, pkt_ipv4, pkt_udp, pkt_eth, dns_payload):
        from os_ken.lib import addrconv

        ip_src_b = socket.inet_aton(pkt_ipv4.dst)
        ip_dst_b = socket.inet_aton(pkt_ipv4.src)
        src_mac_b = addrconv.mac.text_to_bin(DNSConfig.controller_mac)
        dst_mac_b = addrconv.mac.text_to_bin(pkt_eth.src)

        client_port = 53
        try:
            client_port = pkt_udp.src_port
        except Exception:
            pass

        udp_len = 8 + len(dns_payload)
        ip_total_len = 20 + udp_len

        # IP header
        ip_hdr = struct.pack('!BBHHHBBH',
                             0x45, 0, ip_total_len,
                             0, 0x4000,
                             64, 17, 0) + ip_src_b + ip_dst_b
        ip_csum = cls._checksum(ip_hdr)
        ip_hdr = struct.pack('!BBHHHBBH',
                             0x45, 0, ip_total_len,
                             0, 0x4000,
                             64, 17, ip_csum) + ip_src_b + ip_dst_b

        # UDP header (checksum initially 0 for calculation)
        udp_hdr = struct.pack('!HHHH', 53, client_port, udp_len, 0)
        pseudo = ip_src_b + ip_dst_b + struct.pack('!BBH', 0, 17, udp_len)
        udp_csum = cls._checksum(pseudo + udp_hdr + dns_payload)
        udp_hdr = struct.pack('!HHHH', 53, client_port, udp_len, udp_csum)

        # Ethernet header
        eth_hdr = dst_mac_b + src_mac_b + struct.pack('!H', 0x0800)

        full = eth_hdr + ip_hdr + udp_hdr + dns_payload

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        actions = [parser.OFPActionOutput(port=in_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=full,
        )
        datapath.send_msg(out)
