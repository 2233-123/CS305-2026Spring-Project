"""Non-interactive DHCP integration test — exits automatically."""
import time, sys
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
from mininet.log import setLogLevel

setLogLevel('info')

PASS = 0
FAIL = 0
def check(cond, msg):
    global PASS, FAIL
    if cond: PASS += 1; print("  [PASS]", msg)
    else: FAIL += 1; print("  [FAIL]", msg)

class TestTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        h1 = self.addHost('h1', ip='no ip defined/8')
        h2 = self.addHost('h2', ip='no ip defined/8')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)

net = Mininet(topo=TestTopo(), autoSetMacs=True, controller=RemoteController)
net.start()
time.sleep(3)

for h in net.hosts:
    h.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1")
    h.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1 >/dev/null 2>&1")
    print("DHCP on", h.name)
    h.cmd('dhclient -v %s-eth0 2>/tmp/dhclient_%s.log' % (h.name, h.name))
    time.sleep(3)
    out = h.cmd("ip addr show %s-eth0 | grep 'inet ' | awk '{print $2}' | cut -d/ -f1" % h.name).strip()
    if out:
        h.setIP(out, prefixLen=24)
        print("  %s -> %s" % (h.name, out))
        check(out.startswith('192.168.1.'), "%s IP in subnet: %s" % (h.name, out))
    else:
        check(False, "%s has NO IP" % h.name)

h1, h2 = net.get('h1', 'h2')
for h in net.hosts:
    ip = h.IP()
    if ip:
        h.cmd('arping -c 2 -A -I %s-eth0 %s' % (h.name, ip))
time.sleep(2)

if h1.IP() and h2.IP():
    result = h1.cmd('ping -c 2 -W 1 %s 2>&1' % h2.IP())
    success = '0% packet loss' in result
    check(success, "h1 -> h2 ping")
    print(result.strip())
else:
    check(False, "Cannot ping: h1=%s h2=%s" % (h1.IP(), h2.IP()))

print("\nResults: %d passed, %d failed" % (PASS, FAIL))
net.stop()
sys.exit(0 if FAIL == 0 else 1)
