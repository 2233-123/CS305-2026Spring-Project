from os_ken.lib import addrconv
from os_ken.lib.packet import packet
from os_ken.lib.packet import ethernet
from os_ken.lib.packet import ipv4
from os_ken.lib.packet import udp
from os_ken.lib.packet import dhcp
from os_ken.lib.packet import arp
from os_ken.lib import hub
from dns_server import DNSServer
import struct
import socket
import time
import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback constants (os-ken's dhcp module should define these; numeric
# fallbacks ensure correctness on any version)
# ---------------------------------------------------------------------------
_DHCP_NAK            = getattr(dhcp, 'DHCP_NAK', 6)
_DHCP_DECLINE        = getattr(dhcp, 'DHCP_DECLINE', 4)
_DHCP_RELEASE        = getattr(dhcp, 'DHCP_RELEASE', 7)
_DHCP_REQ_IP_OPT     = getattr(dhcp, 'DHCP_REQUESTED_IP_ADDR_OPT', 50)   # RFC 2132
_DHCP_MSG_OPT        = getattr(dhcp, 'DHCP_MESSAGE_OPT', 56)              # RFC 2132
_DHCP_HOST_NAME_OPT  = getattr(dhcp, 'DHCP_HOST_NAME_OPT', 12)            # RFC 2132


class DHCPConfig:
    controller_macAddr = '7e:49:b3:f0:f9:99'
    dns = '8.8.8.8'
    start_ip = '192.168.1.2'
    end_ip = '192.168.1.100'
    netmask = '255.255.255.0'
    lease_time = 60          # seconds — shorten for testing; change to 86400 for production
    reaper_interval = 30      # seconds between lease expiry scans
    probe_timeout = 2         # seconds to wait for ARP probe response
    conflict_ttl = 300        # seconds before retrying a previously-conflicted IP


# ---------------------------------------------------------------------------
# Lease state machine
# ---------------------------------------------------------------------------
LEASE_PROBING = 'PROBING'
LEASE_OFFERED = 'OFFERED'
LEASE_ALLOCATED = 'ALLOCATED'
LEASE_RELEASED = 'RELEASED'
LEASE_CONFLICTED = 'CONFLICTED'


class DHCPServer:
    hardware_addr = DHCPConfig.controller_macAddr
    start_ip = DHCPConfig.start_ip
    end_ip = DHCPConfig.end_ip
    netmask = DHCPConfig.netmask
    dns = DHCPConfig.dns
    lease_time = DHCPConfig.lease_time
    server_ip = '192.168.1.1'

    mac_to_lease = {}   # mac_bytes -> {"ip": str, "assigned_at": float, "expires_at": float, "state": str}
    ip_to_mac = {}      # ip_str -> mac_bytes
    mac_to_hostname = {}  # mac_bytes -> hostname_str

    _all_datapaths = {}  # dpid -> datapath (set by controller)

    # ARP probe state — shared between DHCP greenlet and ARP-reply handler
    _probing = {}            # ip_str -> bool  (True=waiting, False=conflict-detected)
    _conflict_ips = {}       # ip_str -> float (Unix timestamp of last conflict)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @classmethod
    def _ip_to_int(cls, ip_str):
        return struct.unpack('!I', socket.inet_aton(ip_str))[0]

    @classmethod
    def _int_to_ip(cls, ip_int):
        return socket.inet_ntoa(struct.pack('!I', ip_int))

    @classmethod
    def _now(cls):
        return time.time()

    @classmethod
    def _release_lease(cls, mac_addr):
        if mac_addr in cls.mac_to_lease:
            info = cls.mac_to_lease[mac_addr]
            ip = info['ip']
            cls.mac_to_lease[mac_addr]['state'] = LEASE_RELEASED
            cls.mac_to_lease[mac_addr]['expires_at'] = 0
            if ip in cls.ip_to_mac:
                del cls.ip_to_mac[ip]
            cls.mac_to_hostname.pop(mac_addr, None)
            DNSServer.remove_record(ip=ip)
            _logger.info("[DHCP] RELEASED IP %s from MAC %s", ip, mac_addr.hex(':'))

    # ------------------------------------------------------------------
    # ARP probe — RFC 2131 §2.2
    # ------------------------------------------------------------------
    @classmethod
    def _send_arp_probe(cls, datapath, target_ip):
        """Broadcast an ARP Request from ALL known switches to check target_ip."""
        sends = set()
        for dp in list(cls._all_datapaths.values()) + [datapath]:
            if dp.id in sends:
                continue
            sends.add(dp.id)
            src_mac = cls.hardware_addr
            src_ip = cls.server_ip

            e = ethernet.ethernet(dst='ff:ff:ff:ff:ff:ff', src=src_mac,
                                  ethertype=ethernet.ether.ETH_TYPE_ARP)
            a = arp.arp(
                hwtype=arp.ARP_HW_TYPE_ETHERNET,
                proto=ethernet.ether.ETH_TYPE_IP,
                hlen=6, plen=4,
                opcode=arp.ARP_REQUEST,
                src_mac=src_mac, src_ip=src_ip,
                dst_mac='00:00:00:00:00:00', dst_ip=target_ip,
            )
            p = packet.Packet()
            p.add_protocol(e)
            p.add_protocol(a)
            p.serialize()

            ofproto = dp.ofproto
            parser = dp.ofproto_parser
            actions = [parser.OFPActionOutput(port=ofproto.OFPP_ALL)]
            out = parser.OFPPacketOut(
                datapath=dp,
                buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER,
                actions=actions,
                data=p.data,
            )
            dp.send_msg(out)
        _logger.info("[DHCP] ARP PROBE sent for IP %s from %d switches", target_ip, len(sends))

    @classmethod
    def _arp_probe(cls, ip_str, datapath):
        """
        Send ARP probe for *ip_str* and wait PROBE_TIMEOUT seconds.
        Returns True if IP is free, False if a conflict was detected.
        Also returns False immediately for recently-conflicted IPs.
        """
        now = cls._now()

        # clean up stale conflict entries
        stale = [ip for ip, ts in cls._conflict_ips.items()
                 if now - ts > DHCPConfig.conflict_ttl]
        for ip in stale:
            del cls._conflict_ips[ip]

        if ip_str in cls._conflict_ips:
            _logger.info("[DHCP] IP %s still in conflict list (%.0fs ago), skipping",
                         ip_str, now - cls._conflict_ips[ip_str])
            return False

        cls._probing[ip_str] = True
        cls._send_arp_probe(datapath, ip_str)
        hub.sleep(DHCPConfig.probe_timeout)

        result = cls._probing.pop(ip_str, False)   # True=clear, False=conflict
        if not result:
            cls._conflict_ips[ip_str] = now
            _logger.warning("[DHCP] ARP CONFLICT detected on IP %s", ip_str)
            return False
        _logger.info("[DHCP] ARP PROBE clear for IP %s", ip_str)
        return True

    @classmethod
    def _mark_arp_conflict(cls, ip_str):
        """Called from controller.py when an ARP_REPLY is received for a probed IP."""
        if ip_str in cls._probing:
            cls._probing[ip_str] = False
            _logger.info("[DHCP] ARP CONFLICT flagged for IP %s (reply observed)", ip_str)

    # ------------------------------------------------------------------
    # IP allocation
    # ------------------------------------------------------------------
    @classmethod
    def _find_free_ip(cls, mac_addr, datapath=None):
        if mac_addr in cls.mac_to_lease:
            info = cls.mac_to_lease[mac_addr]
            if info['state'] == LEASE_ALLOCATED:
                return info['ip']

        now = cls._now()
        used = set()
        for mac, info in cls.mac_to_lease.items():
            if info['state'] == LEASE_ALLOCATED and now < info['expires_at']:
                used.add(info['ip'])

        start = cls._ip_to_int(cls.start_ip)
        end = cls._ip_to_int(cls.end_ip)
        for ip_int in range(start, end + 1):
            ip_str = cls._int_to_ip(ip_int)
            if ip_str not in used:
                if datapath is not None and not cls._arp_probe(ip_str, datapath):
                    continue
                cls.mac_to_lease[mac_addr] = {
                    'ip': ip_str,
                    'assigned_at': now,
                    'expires_at': now + cls.lease_time,
                    'state': LEASE_OFFERED,
                }
                return ip_str
        return None

    @classmethod
    def _get_requested_ip(cls, pkt):
        """Extract the requested IP address from DHCPREQUEST Option 50."""
        dhcp_data = pkt.get_protocol(dhcp.dhcp)
        if dhcp_data is None or dhcp_data.options is None or dhcp_data.options.option_list is None:
            return None
        for opt in dhcp_data.options.option_list:
            if opt.tag == _DHCP_REQ_IP_OPT:
                try:
                    return socket.inet_ntoa(opt.value)
                except Exception:
                    return None
        return None

    @classmethod
    def _get_hostname(cls, pkt):
        """Extract the client hostname from DHCP Option 12."""
        dhcp_data = pkt.get_protocol(dhcp.dhcp)
        if dhcp_data is None or dhcp_data.options is None or dhcp_data.options.option_list is None:
            return None
        for opt in dhcp_data.options.option_list:
            if opt.tag == _DHCP_HOST_NAME_OPT:
                try:
                    val = opt.value
                    if isinstance(val, bytes):
                        return val.decode('utf-8', errors='replace').rstrip('\x00')
                    return str(val)
                except Exception:
                    return None
        return None

    # ------------------------------------------------------------------
    # packet assembly
    # ------------------------------------------------------------------
    @classmethod
    def assemble_offer(cls, pkt, datapath):
        dhcp_data = pkt.get_protocol(dhcp.dhcp)
        eth = pkt.get_protocol(ethernet.ethernet)
        client_mac = eth.src
        mac_bytes = addrconv.mac.text_to_bin(client_mac)
        free_ip = cls._find_free_ip(mac_bytes, datapath)

        if free_ip is None:
            _logger.warning("[DHCP] No free IP for MAC %s", client_mac)
            return None

        _logger.info("[DHCP] OFFER IP %s -> MAC %s (expires in %ds)",
                     free_ip, client_mac, cls.lease_time)

        opt_list = [
            dhcp.option(tag=dhcp.DHCP_MESSAGE_TYPE_OPT,
                       value=bytes([dhcp.DHCP_OFFER])),
            dhcp.option(tag=dhcp.DHCP_SUBNET_MASK_OPT,
                       value=socket.inet_aton(cls.netmask)),
            dhcp.option(tag=dhcp.DHCP_DNS_SERVER_ADDR_OPT,
                       value=socket.inet_aton(cls.dns)),
            dhcp.option(tag=dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT,
                       value=struct.pack('!I', cls.lease_time)),
            dhcp.option(tag=dhcp.DHCP_SERVER_IDENTIFIER_OPT,
                       value=socket.inet_aton(cls.server_ip)),
        ]
        dhcp_opts = dhcp.options(option_list=opt_list)

        dhcp_pkt = dhcp.dhcp(
            op=dhcp.DHCP_BOOT_REPLY,
            chaddr=mac_bytes,
            htype=1, hlen=6,
            xid=dhcp_data.xid,
            yiaddr=free_ip,
            siaddr=cls.server_ip,
            options=dhcp_opts,
        )

        e = ethernet.ethernet(
            dst=client_mac, src=cls.hardware_addr, ethertype=0x0800,
        )
        i = ipv4.ipv4(
            src=cls.server_ip, dst=free_ip, proto=17,
            identification=0, offset=0, ttl=64, total_length=0,
        )
        u = udp.udp(src_port=67, dst_port=68, total_length=0)

        pkt_out = packet.Packet()
        pkt_out.add_protocol(e)
        pkt_out.add_protocol(i)
        pkt_out.add_protocol(u)
        pkt_out.add_protocol(dhcp_pkt)

        return pkt_out

    @classmethod
    def assemble_nak(cls, pkt, datapath, port, message="requested address not available"):
        """Build and return a DHCPNAK packet."""
        dhcp_data = pkt.get_protocol(dhcp.dhcp)
        eth = pkt.get_protocol(ethernet.ethernet)
        client_mac = eth.src
        mac_bytes = addrconv.mac.text_to_bin(client_mac)

        opt_list = [
            dhcp.option(tag=dhcp.DHCP_MESSAGE_TYPE_OPT,
                       value=bytes([_DHCP_NAK])),
            dhcp.option(tag=dhcp.DHCP_SERVER_IDENTIFIER_OPT,
                       value=socket.inet_aton(cls.server_ip)),
            dhcp.option(tag=_DHCP_MSG_OPT,
                       value=message.encode() if isinstance(message, str) else message),
        ]
        dhcp_opts = dhcp.options(option_list=opt_list)

        dhcp_pkt = dhcp.dhcp(
            op=dhcp.DHCP_BOOT_REPLY,
            chaddr=mac_bytes,
            htype=1, hlen=6,
            xid=dhcp_data.xid,
            yiaddr='0.0.0.0',
            siaddr=cls.server_ip,
            options=dhcp_opts,
        )

        e = ethernet.ethernet(
            dst=client_mac, src=cls.hardware_addr, ethertype=0x0800,
        )
        i = ipv4.ipv4(
            src=cls.server_ip, dst='255.255.255.255', proto=17,
            identification=0, offset=0, ttl=64, total_length=0,
        )
        u = udp.udp(src_port=67, dst_port=68, total_length=0)

        p = packet.Packet()
        p.add_protocol(e)
        p.add_protocol(i)
        p.add_protocol(u)
        p.add_protocol(dhcp_pkt)

        _logger.warning("[DHCP] NAK sent to MAC %s: %s", client_mac, message)
        return p

    @classmethod
    def assemble_ack(cls, pkt, datapath, port):
        dhcp_data = pkt.get_protocol(dhcp.dhcp)
        eth = pkt.get_protocol(ethernet.ethernet)
        client_mac = eth.src
        mac_bytes = addrconv.mac.text_to_bin(client_mac)
        now = cls._now()
        requested_ip = cls._get_requested_ip(pkt)

        lease = cls.mac_to_lease.get(mac_bytes)
        if lease is not None and lease['state'] == LEASE_OFFERED:
            assigned_ip = lease['ip']
            if requested_ip is not None and requested_ip != assigned_ip:
                return cls.assemble_nak(pkt, datapath, port,
                                        "requested IP %s does not match offer %s" %
                                        (requested_ip, assigned_ip))
            cls.mac_to_lease[mac_bytes] = {
                'ip': assigned_ip,
                'assigned_at': now,
                'expires_at': now + cls.lease_time,
                'state': LEASE_ALLOCATED,
            }
            cls.ip_to_mac[assigned_ip] = mac_bytes
            hostname = cls.mac_to_hostname.get(mac_bytes)
            if hostname:
                DNSServer.add_record(hostname, assigned_ip)
            _logger.info("[DHCP] ACK IP %s -> MAC %s (state ALLOCATED, expires in %ds)",
                         assigned_ip, client_mac, cls.lease_time)
        elif lease is not None and lease['state'] == LEASE_ALLOCATED:
            assigned_ip = lease['ip']
            if requested_ip is not None and requested_ip != assigned_ip:
                return cls.assemble_nak(pkt, datapath, port,
                                        "requested IP %s does not match lease %s" %
                                        (requested_ip, assigned_ip))
            cls.mac_to_lease[mac_bytes]['expires_at'] = now + cls.lease_time
            hostname = cls.mac_to_hostname.get(mac_bytes)
            if hostname:
                DNSServer.add_record(hostname, assigned_ip)
            _logger.info("[DHCP] RENEW IP %s -> MAC %s (expires in %ds)",
                         assigned_ip, client_mac, cls.lease_time)
        else:
            assigned_ip = cls._find_free_ip(mac_bytes, datapath)
            if assigned_ip is None:
                _logger.warning("[DHCP] No IP available for ACK to MAC %s", client_mac)
                return None
            cls.mac_to_lease[mac_bytes] = {
                'ip': assigned_ip,
                'assigned_at': now,
                'expires_at': now + cls.lease_time,
                'state': LEASE_ALLOCATED,
            }
            cls.ip_to_mac[assigned_ip] = mac_bytes
            hostname = cls.mac_to_hostname.get(mac_bytes)
            if hostname:
                DNSServer.add_record(hostname, assigned_ip)
            _logger.info("[DHCP] ACK IP %s -> MAC %s (new allocation, expires in %ds)",
                         assigned_ip, client_mac, cls.lease_time)

        opt_list = [
            dhcp.option(tag=dhcp.DHCP_MESSAGE_TYPE_OPT,
                       value=bytes([dhcp.DHCP_ACK])),
            dhcp.option(tag=dhcp.DHCP_SUBNET_MASK_OPT,
                       value=socket.inet_aton(cls.netmask)),
            dhcp.option(tag=dhcp.DHCP_DNS_SERVER_ADDR_OPT,
                       value=socket.inet_aton(cls.dns)),
            dhcp.option(tag=dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT,
                       value=struct.pack('!I', cls.lease_time)),
            dhcp.option(tag=dhcp.DHCP_SERVER_IDENTIFIER_OPT,
                       value=socket.inet_aton(cls.server_ip)),
        ]
        dhcp_opts = dhcp.options(option_list=opt_list)

        dhcp_pkt = dhcp.dhcp(
            op=dhcp.DHCP_BOOT_REPLY,
            chaddr=mac_bytes,
            htype=1, hlen=6,
            xid=dhcp_data.xid,
            yiaddr=assigned_ip,
            siaddr=cls.server_ip,
            options=dhcp_opts,
        )

        e = ethernet.ethernet(
            dst=client_mac, src=cls.hardware_addr, ethertype=0x0800,
        )
        i = ipv4.ipv4(
            src=cls.server_ip, dst=assigned_ip, proto=17,
            identification=0, offset=0, ttl=64, total_length=0,
        )
        u = udp.udp(src_port=67, dst_port=68, total_length=0)

        ack_pkt = packet.Packet()
        ack_pkt.add_protocol(e)
        ack_pkt.add_protocol(i)
        ack_pkt.add_protocol(u)
        ack_pkt.add_protocol(dhcp_pkt)

        return ack_pkt

    # ------------------------------------------------------------------
    # DHCP message dispatcher
    # ------------------------------------------------------------------
    @classmethod
    def handle_dhcp(cls, datapath, port, pkt):
        dhcp_data = pkt.get_protocol(dhcp.dhcp)
        if dhcp_data is None:
            return

        if dhcp_data.op != dhcp.DHCP_BOOT_REQUEST:
            return

        if dhcp_data.options is None or dhcp_data.options.option_list is None:
            return

        msg_type = None
        for opt in dhcp_data.options.option_list:
            if opt.tag == dhcp.DHCP_MESSAGE_TYPE_OPT:
                msg_type = opt.value
                break

        if msg_type is None:
            return

        eth = pkt.get_protocol(ethernet.ethernet)
        mac_bytes = addrconv.mac.text_to_bin(eth.src) if eth else None

        hostname = cls._get_hostname(pkt)
        if hostname and mac_bytes:
            cls.mac_to_hostname[mac_bytes] = hostname

        # ---- DHCPDISCOVER ----
        if msg_type == bytes([dhcp.DHCP_DISCOVER]):
            resp_pkt = cls.assemble_offer(pkt, datapath)
            if resp_pkt is not None:
                cls._send_packet(datapath, port, resp_pkt)

        # ---- DHCPREQUEST ----
        elif msg_type == bytes([dhcp.DHCP_REQUEST]):
            resp_pkt = cls.assemble_ack(pkt, datapath, port)
            if resp_pkt is not None:
                cls._send_packet(datapath, port, resp_pkt)

        # ---- DHCPRELEASE ----
        elif msg_type == bytes([_DHCP_RELEASE]):
            if mac_bytes:
                cls._release_lease(mac_bytes)

        # ---- DHCPDECLINE ----
        elif msg_type == bytes([_DHCP_DECLINE]):
            if mac_bytes:
                lease = cls.mac_to_lease.get(mac_bytes)
                if lease:
                    declined_ip = lease['ip']
                    cls._conflict_ips[declined_ip] = cls._now()
                    cls._release_lease(mac_bytes)
                    _logger.warning("[DHCP] DECLINE received — IP %s from MAC %s added to conflict list",
                                    declined_ip, mac_bytes.hex(':'))

    # ------------------------------------------------------------------
    # lease reaper — background coroutine
    # ------------------------------------------------------------------
    @classmethod
    def _lease_reaper(cls):
        while True:
            hub.sleep(DHCPConfig.reaper_interval)
            now = cls._now()
            expired = []
            for mac, info in cls.mac_to_lease.items():
                if info['state'] == LEASE_ALLOCATED and now >= info['expires_at']:
                    expired.append(mac)
            for mac in expired:
                cls._release_lease(mac)

    # ------------------------------------------------------------------
    # send helper
    # ------------------------------------------------------------------
    @classmethod
    def _send_packet(cls, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        if isinstance(pkt, str):
            pkt = pkt.encode()
        pkt.serialize()
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)
