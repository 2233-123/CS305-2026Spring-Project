"""
DNS integration test — non-interactive.
Run on the VM with the controller already started:

    Terminal 1:  osken-manager --observe-links controller.py
    Terminal 2:  sudo env "PATH=$PATH" python tests/dns_test/test_network.py
"""
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time
import sys
import os
import struct
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dns_server import DNSConfig

PASS = 0
FAIL = 0


def check(condition, test_name):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {test_name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {test_name}")


def disable_ipv6(node):
    node.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")


def send_arp(node, count=1):
    ip = get_ip(node)
    if ip:
        node.cmd('arping -c %d -A -I %s-eth0 %s' % (count, node.name, ip))


def send_dhcp(node):
    print(f'  Sending DHCP request: dhclient -v {node.name}-eth0')
    node.cmd('dhclient -v %s-eth0' % node.name)
    time.sleep(2)
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    if out:
        ip, mask = (out.split('/') + ['24'])[:2]
        node.setIP(ip, prefixLen=int(mask))
        return ip
    return None


def get_ip(node):
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    return out if out else None


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


def _build_dns_query(domain, qtype):
    txid = 0x1234
    flags = 0x0100
    header = struct.pack('!HHHHHH', txid, flags, 1, 0, 0, 0)
    parts = domain.split('.')
    qname = b''
    for p in parts:
        qname += struct.pack('B', len(p)) + p.encode('ascii')
    qname += b'\x00'
    question = qname + struct.pack('!HH', qtype, 1)
    return header + question


def _parse_dns_response(data):
    if len(data) < 12:
        return ('FAIL', '')
    flags = struct.unpack('!H', data[2:4])[0]
    rcode = flags & 0xF
    ancount = struct.unpack('!H', data[6:8])[0]
    if rcode == 3:
        return ('NXDOMAIN', '')
    if ancount == 0:
        return ('FAIL', '')
    offset = 12
    while offset < len(data):
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:
            offset += 2
            break
        offset += 1 + length
    offset += 4
    offset += 2
    atype, aclass, ttl, rdlength = struct.unpack('!HHIH', data[offset:offset + 10])
    offset += 10
    if atype == 1 and rdlength == 4:
        ip = socket.inet_ntoa(data[offset:offset + 4])
        return ('OK', ip)
    elif atype == 12:
        saved = offset
        name = ''
        while offset < saved + rdlength:
            l = data[offset]
            if l == 0:
                break
            if (l & 0xC0) == 0xC0:
                break
            offset += 1
            name += data[offset:offset + l].decode('ascii', errors='replace') + '.'
            offset += l
        return ('OK', name.rstrip('.'))
    return ('FAIL', '')


def dns_query_from_host(host_cmd, domain, dns_ip, qtype=1):
    """Send DNS query from within a Mininet host via node.cmd.
    
    We use a Python inline approach via the cmd() method which runs
    inside the host's network namespace.
    """
    query = _build_dns_query(domain, qtype)
    query_hex = query.hex()
    resp_hex = host_cmd(
        "python3 -c \""
        "import socket, sys, binascii;"
        "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM);"
        "s.settimeout(4);"
        "s.sendto(binascii.unhexlify('%s'), ('%s', 53));"
        "d, _ = s.recvfrom(512);"
        "print(d.hex());"
        "s.close()"
        "\" 2>/dev/null" % (query_hex, dns_ip)
    ).strip()
    if not resp_hex:
        return ('FAIL', 'no response')
    try:
        data = bytes.fromhex(resp_hex)
        return _parse_dns_response(data)
    except Exception as e:
        return ('FAIL', str(e))


class TestTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        h1 = self.addHost('h1', ip='no ip defined/8')
        h2 = self.addHost('h2', ip='no ip defined/8')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)


def run_tests():
    print("=" * 70)
    print("DNS -- Integration Tests")
    print("=" * 70)

    topo = TestTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for node in net.hosts:
        disable_ipv6(node)
    for node in net.switches:
        disable_ipv6(node)
    net.start()

    h1, h2 = net.get('h1', 'h2')

    print("\n=== DHCP allocation (registers DNS A + PTR records) ===")
    ip1 = send_dhcp(h1)
    check(ip1 is not None, "h1 got IP: " + str(ip1))
    ip2 = send_dhcp(h2)
    check(ip2 is not None, "h2 got IP: " + str(ip2))
    do_arp_all(net)
    time.sleep(1)

    dns_ip = DNSConfig.controller_ip

    print("\n=== DNS A record queries ===")
    status, result = dns_query_from_host(h1, 'h2', dns_ip, 1)
    check(status == 'OK' and result == ip2,
          "h1 nslookup h2 -> " + result + " (expected " + str(ip2) + ")")

    status, result = dns_query_from_host(h2, 'h1', dns_ip, 1)
    check(status == 'OK' and result == ip1,
          "h2 nslookup h1 -> " + result + " (expected " + str(ip1) + ")")

    print("\n=== DNS PTR (reverse) queries ===")
    ptr_for_ip2 = '.'.join(reversed(ip2.split('.'))) + '.in-addr.arpa'
    status, result = dns_query_from_host(h1, ptr_for_ip2, dns_ip, 12)
    check(status == 'OK' and 'h2' in result,
          "h1 reverse-lookup " + ip2 + " (PTR) -> " + result)

    ptr_for_ip1 = '.'.join(reversed(ip1.split('.'))) + '.in-addr.arpa'
    status, result = dns_query_from_host(h2, ptr_for_ip1, dns_ip, 12)
    check(status == 'OK' and 'h1' in result,
          "h2 reverse-lookup " + ip1 + " (PTR) -> " + result)

    print("\n=== DNS NXDOMAIN ===")
    status, result = dns_query_from_host(h1, 'unknown.host', dns_ip, 1)
    check(status == 'NXDOMAIN', "nslookup unknown -> " + status)

    status, result = dns_query_from_host(h1, '1.2.3.4.in-addr.arpa', dns_ip, 12)
    check(status == 'NXDOMAIN', "nslookup 4.3.2.1 (PTR) -> " + status)

    print("\n" + "=" * 70)
    print("Results: " + str(PASS) + " passed, " + str(FAIL) + " failed")
    print("=" * 70)

    net.stop()
    return FAIL == 0


if __name__ == '__main__':
    setLogLevel('info')
    success = run_tests()
    sys.exit(0 if success else 1)
