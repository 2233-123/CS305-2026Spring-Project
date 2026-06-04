"""Non-interactive firewall integration test — exits automatically."""
import time, sys
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
from mininet.log import setLogLevel

setLogLevel('info')

PASS = 0; FAIL = 0
def check(cond, msg):
    global PASS, FAIL
    if cond: PASS += 1; print("  [PASS]", msg)
    else: FAIL += 1; print("  [FAIL]", msg)

class FirewallTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        h1 = self.addHost('h1', ip='192.168.117.2/24')
        h2 = self.addHost('h2', ip='192.168.117.3/24')
        h3 = self.addHost('h3', ip='192.168.117.4/24')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)

net = Mininet(topo=FirewallTopo(), autoSetMacs=True, controller=RemoteController)
net.start()
time.sleep(2)

for h in net.hosts:
    h.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1")

for _ in range(3):
    for h in net.hosts:
        h.cmd('arping -c 1 -A -I %s-eth0 %s' % (h.name, h.IP()))
    time.sleep(1)

h1, h2, h3 = net.get('h1', 'h2', 'h3')

# Test 1: h1->h2 ICMP should FAIL (firewall blocks)
r = h1.cmd('ping -c 2 -W 1 192.168.117.3 2>&1')
blocked = '100% packet loss' in r
check(blocked, "h1->h2 ICMP BLOCKED (firewall)")

# Test 2: h1->h3 ICMP should PASS
r = h1.cmd('ping -c 2 -W 1 192.168.117.4 2>&1')
ok = '0% packet loss' in r
check(ok, "h1->h3 ICMP PASS (not in rules)")

print("\nResults: %d passed, %d failed" % (PASS, FAIL))
net.stop()
sys.exit(0 if FAIL == 0 else 1)
