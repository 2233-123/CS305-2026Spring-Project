"""
DNS integration test — semi-automatic demo.
Run on the VM with the controller already started:

    Terminal 1:  osken-manager --observe-links controller.py
    Terminal 2:  sudo env "PATH=$PATH" python tests/dns_test/test_network.py
"""
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dns_server import DNSConfig


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
    node.cmd('rm -f /var/lib/dhcp/dhclient*.leases')
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
    print("DNS -- Semi-Automatic Demo")
    print("=" * 70)

    topo = TestTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for node in net.hosts:
        disable_ipv6(node)
    for node in net.switches:
        disable_ipv6(node)
    net.start()

    h1, h2 = net.get('h1', 'h2')

    print("\n=== Step 1: DHCP allocation ===")
    print("Controller log should show: [DNS] Registered h1 <-> 192.168.1.2")
    ip1 = send_dhcp(h1)
    print("  h1 -> %s %s" % (ip1, "[OK]" if ip1 else "[FAIL]"))

    print("Controller log should show: [DNS] Registered h2 <-> 192.168.1.3")
    ip2 = send_dhcp(h2)
    print("  h2 -> %s %s" % (ip2, "[OK]" if ip2 else "[FAIL]"))

    do_arp_all(net)
    time.sleep(1)

    # Configure Mininet hosts to use controller as DNS server
    for h in net.hosts:
        h.cmd("echo 'nameserver 192.168.1.1' > /etc/resolv.conf")

    dns_ip = DNSConfig.controller_ip

    print()
    print("=" * 70)
    print("  Step 2: Manual DNS queries in Mininet CLI")
    print("  DNS Server IP: %s" % dns_ip)
    print("=" * 70)
    print()
    print("  === A record (forward lookup) ===")
    print("  Query h1 for hostname 'h2':")
    print("    > h1 nslookup h2 %s" % dns_ip)
    print("    Expected: answer = %s" % ip2)
    print()
    print("  Query h2 for hostname 'h1':")
    print("    > h2 nslookup h1 %s" % dns_ip)
    print("    Expected: answer = %s" % ip1)
    print()
    print("  === PTR record (reverse lookup) ===")
    if ip2:
        ptr = '.'.join(reversed(ip2.split('.'))) + '.in-addr.arpa'
        print("  Reverse-lookup %s:" % ip2)
        print("    > h1 nslookup %s %s" % (ptr, dns_ip))
        print("    Expected: name = h2")
    print()
    print("  === NXDOMAIN ===")
    print("  Query non-existent hostname:")
    print("    > h1 nslookup unknown.host %s" % dns_ip)
    print("    Expected: ** server can't find unknown.host: NXDOMAIN")
    print()
    print("  Check controller terminal for:")
    print("    [DNS] Registered h1 <-> 192.168.1.2")
    print("    [DNS] Registered h2 <-> 192.168.1.3")
    print()
    print("  Enter 'exit' or Ctrl+D when done.")
    print("=" * 70)
    print()
    CLI(net)

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    run_tests()
