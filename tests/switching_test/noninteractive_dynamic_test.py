"""Test dynamic topology operations: switch stop/start, link down/up, port modify.
Does NOT use Mininet CLI — uses programmatic OVS commands."""
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

class TestTopo(Topo):
    def __init__(self):
        super().__init__()
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(s1, s2)
        self.addLink(s2, s3)
        self.addLink(s3, s1)

net = Mininet(topo=TestTopo(), autoSetMacs=True, controller=RemoteController)
net.start()
time.sleep(3)

for h in net.hosts:
    h.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1")
for h in net.hosts:
    h.cmd('arping -c 2 -A -I %s-eth0 %s' % (h.name, h.IP()))
time.sleep(2)

# Baseline ping
h1, h2 = net.get('h1', 'h2')
r = h1.cmd('ping -c 1 -W 1 %s' % h2.IP())
check('0% packet loss' in r, "Baseline: h1->h2 ping OK")

# ---- handle_switch_delete: stop switch s2 ----
print("\n--- handle_switch_delete: stopping s2 ---")
s2 = net.get('s2')
s2.cmd('ovs-vsctl del-br s2 2>/dev/null || true')
time.sleep(3)
r = h1.cmd('ping -c 1 -W 1 %s' % h2.IP())
check('100% packet loss' in r, "handle_switch_delete: h1->h2 UNREACHABLE (s2 down)")

# ---- handle_switch_add: restart s2 ----
print("--- handle_switch_add: restarting s2 ---")
s2.cmd('ovs-vsctl add-br s2')
s2.cmd('ovs-vsctl set bridge s2 protocols=OpenFlow10')
s2.cmd('ovs-vsctl set-controller s2 tcp:127.0.0.1:6653')
# Re-add links
for intf in s2.intfNames():
    s2.attach(intf)
time.sleep(5)
# Re-ARP
h2.cmd('arping -c 3 -A -I %s-eth0 %s' % (h2.name, h2.IP()))
time.sleep(2)
r = h1.cmd('ping -c 2 -W 2 %s' % h2.IP())
check('0% packet loss' in r, "handle_switch_add: h1->h2 REACHABLE (s2 restarted)")

# ---- handle_link_delete: s1-s3 down ----
print("--- handle_link_delete: s1-s3 link down ---")
s1 = net.get('s1')
s3 = net.get('s3')
link_name = None
for l in net.links:
    if (l.intf1.node == s1 and l.intf2.node == s3) or (l.intf1.node == s3 and l.intf2.node == s1):
        s1.cmd('ip link set %s down' % l.intf1.name)
        s3.cmd('ip link set %s down' % l.intf2.name)
        break
time.sleep(3)
r = h1.cmd('ping -c 1 -W 1 %s' % h2.IP())
check('0% packet loss' in r, "handle_link_delete: h1->h2 still REACHABLE (s1-s2-s3 path)")

# ---- handle_link_add: s1-s3 up ----
print("--- handle_link_add: s1-s3 link up ---")
for l in net.links:
    if (l.intf1.node == s1 and l.intf2.node == s3) or (l.intf1.node == s3 and l.intf2.node == s1):
        s1.cmd('ip link set %s up' % l.intf1.name)
        s3.cmd('ip link set %s up' % l.intf2.name)
        break
time.sleep(3)
r = h1.cmd('ping -c 1 -W 1 %s' % h2.IP())
check('0% packet loss' in r, "handle_link_add: h1->h2 still REACHABLE")

# ---- handle_port_modify: s1 port down (host h1) ----
print("--- handle_port_modify: s1 port to h1 down ---")
for l in net.links:
    if l.intf1.node == s1 and l.intf2.node == h1:
        s1.cmd('ovs-ofctl mod-port s1 %s down' % l.intf1.name.split('-')[-1])
        break
time.sleep(3)
r = h1.cmd('ping -c 1 -W 1 %s' % h2.IP())
check('100% packet loss' in r, "handle_port_modify: h1->h2 UNREACHABLE (h1 port down)")

print("\nResults: %d passed, %d failed" % (PASS, FAIL))
net.stop()
sys.exit(0 if FAIL == 0 else 1)
