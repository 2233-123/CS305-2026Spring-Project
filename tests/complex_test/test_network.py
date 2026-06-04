r"""
Complex Topology Test — 8 switches, 8 hosts, 13 switch-to-switch edges

This is the complex test case for shortest path switching.
Requirements: >6 hosts, >6 switches, >10 edges.
Dynamic topology changes are executed in the Mininet CLI.

Topology graph (render with networkx: python tests/complex_test/visualize.py):

        h1 --- s1 ---- s2 --- h2
                |  \  / |
                |   \/  |
                s3--s4--s5
               / \  |  / \
              /   \ | /   \
            h3     s6-s7    h4
                    | |     |
                    s8-h5  h8
                   /
                 h6
        h7 - s1

Switch-to-switch edges:  s1-s2, s1-s3, s1-s4, s2-s3, s2-s5,
                          s3-s4, s3-s6, s4-s5, s4-s7,
                          s5-s6, s5-s8, s6-s7, s7-s8  (13 edges)

Usage:
  Terminal 1: osken-manager --observe-links controller.py
  Terminal 2: sudo env "PATH=$PATH" python tests/complex_test/test_network.py

  In Mininet CLI (after hosts have IPs):
    > pingall                                      # verify all reachable
    > switch s3 stop                                # triggers handle_switch_delete
    > pingall                                      # observe path changes, some unreachable
    > switch s3 start                               # triggers handle_switch_add
    > link s1 s2 down                               # triggers handle_link_delete
    > link s1 s2 up                                 # triggers handle_link_add
    > sh ovs-ofctl mod-port s6 1 down               # triggers handle_port_modify
"""
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time


def disable_ipv6(node):
    node.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")


def send_arp(node, count=1):
    node.cmd('arping -c %d -A -I %s-eth0 %s' % (count, node.name, node.IP()))


def send_dhcp(node):
    node.cmd('dhclient -v %s-eth0' % node.name)
    time.sleep(2)
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    if out:
        node.setIP(out, prefixLen=24)
    return out


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


class ComplexTopo(Topo):
    """8 hosts + 8 switches + 13 switch-to-switch edges + 8 host-switch edges = 21 total."""
    def __init__(self, **opts):
        Topo.__init__(self, **opts)

        hosts = {}
        for i in range(1, 9):
            hosts[i] = self.addHost("h%d" % i, ip="no ip defined/8")

        switches = {}
        for i in range(1, 9):
            switches[i] = self.addSwitch("s%d" % i)

        self.addLink(hosts[1], switches[1])
        self.addLink(hosts[2], switches[2])
        self.addLink(hosts[3], switches[3])
        self.addLink(hosts[4], switches[5])
        self.addLink(hosts[5], switches[8])
        self.addLink(hosts[6], switches[8])
        self.addLink(hosts[7], switches[1])
        self.addLink(hosts[8], switches[7])

        self.addLink(switches[1], switches[2])
        self.addLink(switches[1], switches[3])
        self.addLink(switches[1], switches[4])
        self.addLink(switches[2], switches[3])
        self.addLink(switches[2], switches[5])
        self.addLink(switches[3], switches[4])
        self.addLink(switches[3], switches[6])
        self.addLink(switches[4], switches[5])
        self.addLink(switches[4], switches[7])
        self.addLink(switches[5], switches[6])
        self.addLink(switches[5], switches[8])
        self.addLink(switches[6], switches[7])
        self.addLink(switches[7], switches[8])


def run_mininet():
    topo = ComplexTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)

    for h in net.hosts:
        disable_ipv6(h)
    for s in net.switches:
        disable_ipv6(s)

    net.start()

    # Wait for LLDP + probe to discover all switch-to-switch links.
    # os-ken LLDP sends ~1s per cycle; probe runs every 2s.
    print("Waiting for topology discovery (LLDP + probe)...")
    time.sleep(6)
    print("Topology should be ready — DHCP starting")

    ips = {}
    for h in net.hosts:
        print('Sending DHCP request dhclient -v %s-eth0' % h.name)
        ip = send_dhcp(h)
        if ip:
            ips[h.name] = ip
            print("  %s -> %s" % (h.name, ip))
        else:
            print("  %s -> NO IP" % h.name)

    # Wait for controller to process ARP and install flows
    time.sleep(2)
    print("\nSending gratuitous ARP from all hosts to register them...")
    for h in net.hosts:
        ip = h.IP()
        print("  %s arping -A (%s)" % (h.name, ip))
        h.cmd('arping -c 3 -A -I %s-eth0 %s' % (h.name, ip))
        time.sleep(0.3)
    time.sleep(2)

    print()
    print("=" * 70)
    print("  COMPLEX TOPOLOGY TEST — Shortest Path Switching")
    print("  8 switches, 8 hosts, 13 switch-to-switch edges (21 total)")
    print("=" * 70)
    print()
    print("  In controller console, observe:")
    print("    [Topology] Switches, Links, Hosts")
    print("    [Topology] Switch-to-Switch Shortest Paths")
    print("    [Routing] Host-to-Host Paths")
    print("    [NetworkX] Graph nodes/edges + nx shortest paths")
    print()
    print("  Mininet CLI commands to demonstrate dynamic topology changes:")
    print()
    print("  Step 1: > pingall                  # verify all hosts reachable")
    print("  Step 2: > switch s3 stop            # handle_switch_delete, watch paths")
    print("  Step 3: > pingall                   # some hosts unreachable")
    print("  Step 4: > switch s3 start           # handle_switch_add, watch paths")
    print("  Step 5: > pingall                   # all reachable again")
    print("  Step 6: > link s1 s2 down           # handle_link_delete, watch paths")
    print("  Step 7: > link s1 s2 up             # handle_link_add, watch paths")
    print("  Step 8: > sh ovs-ofctl mod-port s6 1 down  # handle_port_modify")
    print("  Step 9: > pingall")
    print("  Step 10: exit with Ctrl+D")
    print()

    CLI.do_arping_all = lambda self, line: do_arp_all(net)
    CLI(net)

    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run_mininet()
