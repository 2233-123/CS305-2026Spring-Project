"""Non-interactive complex topology test — 8 switches + 8 hosts + 13 switch edges."""
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

class ComplexTopo(Topo):
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

net = Mininet(topo=ComplexTopo(), autoSetMacs=True, controller=RemoteController)
net.start()
time.sleep(8)  # Wait for LLDP + probe to discover all 13 inter-switch links

for h in net.hosts:
    h.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1")

print("DHCP for all 8 hosts...")
for h in net.hosts:
    h.cmd('dhclient -v %s-eth0' % h.name)
    time.sleep(2)
    out = h.cmd("ip addr show %s-eth0 | grep 'inet ' | awk '{print $2}' | cut -d/ -f1" % h.name).strip()
    if out:
        h.setIP(out, prefixLen=24)
        check(True, "%s -> %s" % (h.name, out))
    else:
        check(False, "%s NO IP" % h.name)

print("\nARP registration...")
for h in net.hosts:
    ip = h.IP()
    if ip:
        h.cmd('arping -c 2 -A -I %s-eth0 %s' % (h.name, ip))
time.sleep(3)

# Sample ping tests (don't test all 28 pairs, just key ones)
print("\nPing tests (sample)...")
hosts = net.hosts
tests = [(0,1), (0,3), (0,7), (2,5), (4,6)]  # Sample pairs
for i, j in tests:
    src, dst = hosts[i], hosts[j]
    r = src.cmd('ping -c 1 -W 2 %s 2>&1' % dst.IP())
    ok = '0% packet loss' in r
    check(ok, "%s -> %s" % (src.name, dst.name))

print("\nResults: %d passed, %d failed" % (PASS, FAIL))
net.stop()
sys.exit(0 if FAIL == 0 else 1)
