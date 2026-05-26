"""
Integration test for DHCP RFC ARP-probe conflict detection (Bonus #2).
Run on the VM with the controller already started:

    Terminal 1:  osken-manager --observe-links controller.py
    Terminal 2:  sudo env "PATH=$PATH" python tests/dhcp_test/test_lease_rfc.py

Key scenario: h1 has a static IP → h2 dhclient → ARP probe detects conflict → h2 gets different IP.
"""
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time
import sys


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
    time.sleep(3)
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    if out:
        ip = out
        node.setIP(ip, prefixLen=24)
        return ip
    return None


def get_ip(node):
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    return out if out else None


def set_static_ip(node, ip, netmask='255.255.255.0'):
    node.cmd('ifconfig %s-eth0 %s netmask %s' % (node.name, ip, netmask))
    node.setIP(ip, prefixLen=24)
    time.sleep(0.5)


def release_dhcp(node):
    node.cmd('dhclient -r %s-eth0' % (node.name))
    time.sleep(1)


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
    print("DHCP RFC — ARP Probe Conflict Detection  Integration Tests")
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
    # Test 1: Static IP on h1 → h2 dhclient → conflict → different IP
    # ---------------------------------------------------------------
    print("\n=== Test 1: ARP probe detects static IP conflict ===")
    STOLEN_IP = '192.168.1.2'
    print(f"  Setting static IP {STOLEN_IP} on h1...")
    set_static_ip(h1, STOLEN_IP)
    send_arp(h1)   # gratuitous ARP so switch learns h1's MAC
    time.sleep(1)

    print("  h2 requests DHCP...")
    ip2 = send_dhcp(h2)
    check(ip2 is not None, f"h2 got IP: {ip2}")
    check(ip2 != STOLEN_IP, f"h2 did NOT get stolen IP .2 (got {ip2} instead)")
    check(ip2.startswith('192.168.1.'), f"h2 IP in correct subnet: {ip2}")

    do_arp_all(net)
    time.sleep(1)

    # ---------------------------------------------------------------
    # Test 2: Normal DHCP still works after conflict resolution
    # ---------------------------------------------------------------
    print("\n=== Test 2: Normal DHCP on h3 (no conflict) ===")
    ip3 = send_dhcp(h3)
    check(ip3 is not None, f"h3 got IP: {ip3}")
    check(ip3.startswith('192.168.1.'), f"h3 IP in subnet: {ip3}")

    # ---------------------------------------------------------------
    # Test 3: Re-release and re-request
    # ---------------------------------------------------------------
    print("\n=== Test 3: DHCPRELEASE + re-request after conflict ===")
    release_dhcp(h2)
    after_rel = get_ip(h2)
    check(after_rel == '' or after_rel is None, f"h2 IP cleared after release: '{after_rel}'")

    ip2b = send_dhcp(h2)
    check(ip2b is not None, f"h2 got new IP after release: {ip2b}")

    # ---------------------------------------------------------------
    # Test 4: Conflict cache — re-probing .2 yields conflict (skip)
    # ---------------------------------------------------------------
    print("\n=== Test 4: Conflict cache prevents re-allocation of .2 ===")
    print("  * Manual check: controller log should show '[DHCP] IP 192.168.1.2 still in conflict list'")
    print("  * If you release h2 and re-request immediately, it should skip .2")
    release_dhcp(h2)
    ip2c = send_dhcp(h2)
    check(ip2c is not None and ip2c != STOLEN_IP,
          f"after re-request, .2 skipped: got {ip2c}")

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
