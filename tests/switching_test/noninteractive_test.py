"""Non-interactive switching integration test — exits automatically."""
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

class TriangleTopo(Topo):
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

net = Mininet(topo=TriangleTopo(), autoSetMacs=True, controller=RemoteController)
net.start()
time.sleep(3)

for h in net.hosts:
    h.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1")

time.sleep(3)  # LLDP + probe detection
print("Topology settled, sending ARP...")

for h in net.hosts:
    h.cmd('arping -c 3 -A -I %s-eth0 %s' % (h.name, h.IP()))
time.sleep(3)

print("Testing pingall...")
hosts = net.hosts
all_ok = True
for i, src in enumerate(hosts):
    for dst in hosts[i+1:]:
        result = src.cmd('ping -c 1 -W 2 %s 2>&1' % dst.IP())
        ok = '0% packet loss' in result
        print("  %s -> %s: %s" % (src.name, dst.name, "OK" if ok else "FAIL"))
        if not ok: all_ok = False

check(all_ok, "pingall: all hosts reachable")

print("\nResults: %d passed, %d failed" % (PASS, FAIL))
net.stop()
sys.exit(0 if FAIL == 0 else 1)
