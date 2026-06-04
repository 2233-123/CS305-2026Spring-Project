"""
Integration test for weighted routing (Bonus 3).
Run on the VM with the controller already started:

    Terminal 1:  osken-manager --observe-links controller.py
    Terminal 2:  sudo env "PATH=$PATH" python tests/routing_test/test_weighted.py

The test uses a triangle topology with asymmetric link weights from link_weights.json.
Expected weighted paths (with config: s1-s2=5, s1-s3=10, s2-s3=1):
  - h1 -> h2: s1 -> s2  (cost=5 vs cost=11 via s3)
  - h1 -> h3: s1 -> s2 -> s3  (cost=6 vs cost=10 direct)
"""
from mininet.cli import CLI
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
    node.cmd('arping -c %s -A -I %s-eth0 %s' % (count, node.name, node.IP()))


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


class WeightedTriangleTopo(Topo):
    """
    Triangle topology for weighted routing demo:
        h2 -- s2 ==== s1 -- h1
               |        /
               |        /
               s3 ----+
               |
              h3

    Weights (from link_weights.json):
        s1-s2 = 5      (heavier)
        s1-s3 = 10     (heaviest)
        s2-s3 = 1      (lightest)
    """
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s3)
        self.addLink(s1, s2)
        self.addLink(s2, s3)
        self.addLink(s3, s1)


def run_mininet():
    print("\n" + "=" * 60)
    print("Weighted Routing Integration Test (Bonus 3)")
    print("=" * 60)
    print("Weights: s1-s2=5, s1-s3=10, s2-s3=1 (from link_weights.json)")
    print("Expected: h1->h3 via s1->s2->s3 (cost=6) not s1->s3 (cost=10)")
    print("Check controller logs for routing paths.")
    print("=" * 60 + "\n")

    topo = WeightedTriangleTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for h in net.hosts:
        disable_ipv6(h)
    for s in net.switches:
        disable_ipv6(s)

    net.start()
    time.sleep(1)
    do_arp_all(net)

    print("\n=== Network ready. Try these commands ===")
    print("  pingall              - test full connectivity")
    print("  h1 ping h3 -c 1      - single ping (check controller log for path)")
    print("  h1 ping h2 -c 1      - should use direct s1->s2")
    print("  dpctl dump-flows     - show installed flows")
    print("")

    CLI.do_arping_all = lambda self, line: do_arp_all(net)
    CLI(net)

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    run_mininet()
