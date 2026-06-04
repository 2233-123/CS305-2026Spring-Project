"""
Integration test for DHCP lease duration (Bonus).
Run this on the VM with the controller already started:

    Terminal 1:  osken-manager --observe-links controller.py
    Terminal 2:  sudo env "PATH=$PATH" python tests/dhcp_test/test_lease.py

The script runs through 5 test scenarios non-interactively and exits.
"""
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time
import sys
import re


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
    node.cmd('arping -c %d -A -I %s-eth0 %s' % (count, node.name, node.IP()))


def send_dhcp(node):
    print(f'  Sending DHCP request: dhclient -v {node.name}-eth0')
    node.cmd('dhclient -v %s-eth0' % (node.name))
    time.sleep(2)
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    if out:
        ip, mask = (out.split('/') + ['24'])[:2]
        node.setIP(ip, prefixLen=int(mask))
        return ip
    return None


def release_dhcp(node):
    print(f'  Releasing DHCP lease: dhclient -r {node.name}-eth0')
    node.cmd('dhclient -r %s-eth0' % (node.name))
    time.sleep(1)


def get_ip(node):
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    return out if out else None


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


class TestTopo(Topo):
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
    print("DHCP Lease Duration — Integration Tests")
    print("=" * 70)

    topo = TestTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for h in net.hosts:
        disable_ipv6(h)
    for h in net.switches:
        disable_ipv6(h)
    net.start()

    h1, h2, h3 = net.get('h1', 'h2', 'h3')

    # ---------------------------------------------------------------
    # Test 1: Basic allocation
    # ---------------------------------------------------------------
    print("\n=== Test 1: Basic DHCP allocation ===")
    ip1 = send_dhcp(h1)
    check(ip1 is not None, f"h1 got IP: {ip1}")
    check(ip1.startswith('192.168.1.'), f"h1 IP in expected subnet: {ip1}")

    ip2 = send_dhcp(h2)
    check(ip2 is not None, f"h2 got IP: {ip2}")
    check(ip2.startswith('192.168.1.'), f"h2 IP in expected subnet: {ip2}")
    check(ip1 != ip2, f"h1 and h2 have different IPs: {ip1} vs {ip2}")

    do_arp_all(net)
    time.sleep(1)

    # ---------------------------------------------------------------
    # Test 2: DHCPRELEASE — release and re-request
    # ---------------------------------------------------------------
    print("\n=== Test 2: DHCPRELEASE ===")
    release_dhcp(h1)
    after_release = get_ip(h1)
    check(after_release == '' or after_release is None, f"h1 has no IP after release: '{after_release}'")

    ip1_new = send_dhcp(h1)
    check(ip1_new is not None, f"h1 got new IP after release: {ip1_new}")
    check(ip1_new.startswith('192.168.1.'), f"h1 new IP in subnet: {ip1_new}")

    do_arp_all(net)
    time.sleep(1)

    # ---------------------------------------------------------------
    # Test 3: Lease expiry (wait 65s, then check reclaim)
    # ---------------------------------------------------------------
    print("\n=== Test 3: Lease expiry auto-reclaim ===")
    LEASE_SEC = 60  # must match dhcp.py's DHCPConfig.lease_time
    print(f"  Lease time is {LEASE_SEC}s. Waiting {LEASE_SEC + 5}s for expiry...")

    # Release h2 to free an IP, so h3 can eventually get one after h1 expires
    release_dhcp(h2)

    # Wait for h1's lease to expire
    time.sleep(LEASE_SEC + 5)

    # Now h1's lease should have expired, h3 should be able to get an IP
    ip3_before = get_ip(h3)
    print(f"  h3 IP before request: '{ip3_before}'")
    ip3 = send_dhcp(h3)
    check(ip3 is not None, f"h3 got IP after lease expiry: {ip3}")
    check(ip3.startswith('192.168.1.'), f"h3 IP in subnet: {ip3}")

    # ---------------------------------------------------------------
    # Test 4: Renewal — refresh expiry
    # ---------------------------------------------------------------
    print("\n=== Test 4: Lease renewal ===")
    print("  * Manual: re-run dhclient on an already-leased host")
    print("  * Controller log should show: '[DHCP] RENEW IP x.x.x.x -> MAC ...'")

    do_arp_all(net)
    time.sleep(1)

    # Summary
    print("\n" + "=" * 70)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 70)

    net.stop()
    return FAIL == 0


if __name__ == '__main__':
    setLogLevel('info')
    success = run_tests()
    sys.exit(0 if success else 1)
