"""
NAT (SNAT) integration test -- non-interactive.
Run on the VM with the controller already started:

    Terminal 1:  osken-manager --observe-links controller.py
    Terminal 2:  sudo env "PATH=$PATH" python tests/nat_test/test_network.py
"""
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from nat import NATConfig

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
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    if out:
        node.cmd('arping -c %d -A -I %s-eth0 %s' % (count, node.name, out))


def get_ip(node):
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    return out if out else None


def send_dhcp(node):
    print(f'  Sending DHCP request: dhclient -v {node.name}-eth0')
    node.cmd('dhclient -v %s-eth0' % node.name)
    time.sleep(2)
    out = get_ip(node)
    if out:
        ip, mask = (out.split('/') + ['24'])[:2]
        node.setIP(ip, prefixLen=int(mask))
        return ip
    return None


def set_static_ip(node, ip, prefix=24):
    """Set a static IP on the node's eth0 interface."""
    node.cmd('ip addr flush dev %s-eth0' % node.name)
    node.cmd('ip addr add %s/%d dev %s-eth0' % (ip, prefix, node.name))
    node.cmd('ip link set %s-eth0 up' % node.name)
    node.setIP(ip, prefixLen=prefix)
    time.sleep(0.5)


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


class NATTestTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        h1 = self.addHost('h1', ip='no ip defined/8')
        h2 = self.addHost('h2', ip='no ip defined/8')
        h3 = self.addHost('h3', ip='no ip defined/8')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)


def run_tests():
    print("=" * 70)
    print("NAT (SNAT) -- Integration Tests")
    print("=" * 70)

    topo = NATTestTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for node in net.hosts:
        disable_ipv6(node)
    for node in net.switches:
        disable_ipv6(node)
    net.start()

    h1, h2, h3 = net.get('h1', 'h2', 'h3')

    # --- Internal hosts: DHCP ---
    print("\n=== Internal network: DHCP ===")
    ip1 = send_dhcp(h1)
    check(ip1 is not None, "h1 got IP: " + str(ip1))
    check(ip1 is not None and ip1.startswith('192.168.1.'),
          "h1 IP in internal subnet: " + str(ip1))

    ip3 = send_dhcp(h3)
    check(ip3 is not None, "h3 got IP: " + str(ip3))
    check(ip3 is not None and ip3.startswith('192.168.1.'),
          "h3 IP in internal subnet: " + str(ip3))
    check(ip1 != ip3, "h1 and h3 have different IPs")

    # Add default route via NAT gateway so TCP connect() can reach external IPs
    h1.cmd('ip route add default via 192.168.1.1 2>/dev/null || true')
    h3.cmd('ip route add default via 192.168.1.1 2>/dev/null || true')
    # Disable reverse-path filtering + TCP offloading so hosts accept external packets
    for node in [h1, h2, h3]:
        for iface in ['all', 'default', node.name + '-eth0']:
            node.cmd('sysctl -w net.ipv4.conf.%s.rp_filter=0 2>/dev/null' % iface)
        node.cmd('ethtool -K %s-eth0 tx off rx off 2>/dev/null || true' % node.name)
        node.cmd('iptables -I INPUT -i %s-eth0 -j ACCEPT 2>/dev/null || true' % node.name)

    # --- External host: static IP ---
    print("\n=== External network: static IP ===")
    ext_ip = '10.0.2.100'
    set_static_ip(h2, ext_ip, 24)
    check(get_ip(h2) == ext_ip, "h2 static IP set to " + ext_ip)

    do_arp_all(net)
    time.sleep(2)

    # --- Ping through NAT ---
    print("\n=== NAT: ping from h1 to h2 ===")
    result = h1.cmd('ping -c 3 -W 2 %s 2>&1' % ext_ip)
    received = '3 received' in result or '0% packet loss' in result
    check(received, "h1 -> %s ping success" % ext_ip)

    # --- Verify NAT translation on h2 ---
    print("\n=== Verify NAT source IP ===")
    # Run tcpdump on h2 to capture ICMP
    h2.cmd('timeout 3 tcpdump -i %s-eth0 -c 3 -n icmp > /tmp/dump.txt 2>&1 &' % h2.name)
    time.sleep(0.5)
    h1.cmd('ping -c 1 -W 1 %s > /dev/null 2>&1' % ext_ip)
    time.sleep(2)
    dump = h2.cmd('cat /tmp/dump.txt 2>/dev/null')
    nat_ip_seen = NATConfig.external_ip in dump
    check(nat_ip_seen,
          "h2 sees NAT IP %s in captured traffic" % NATConfig.external_ip)

    # --- Two hosts behind same NAT ---
    print("\n=== Two internal hosts behind NAT ===")
    result = h3.cmd('ping -c 2 -W 2 %s 2>&1' % ext_ip)
    both_work = '0% packet loss' in result
    check(both_work, "h3 -> %s ping success (multi-client NAT)" % ext_ip)

    # --- Test that internal traffic is NOT NAT'd ---
    print("\n=== Internal-to-internal: no NAT ===")
    if ip1 and ip3:
        result = h1.cmd('ping -c 2 -W 2 %s 2>&1' % ip3)
        internal_ping = '0% packet loss' in result
        check(internal_ping, "h1 -> h3 (internal) ping works directly")

    print("\n" + "=" * 70)
    print("Results: " + str(PASS) + " passed, " + str(FAIL) + " failed")
    print("=" * 70)

    net.stop()
    return FAIL == 0


if __name__ == '__main__':
    setLogLevel('info')
    success = run_tests()
    sys.exit(0 if success else 1)
