"""Run on VM: switching integration test."""
import sys, time
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel
from test_network import TriangleTopo, disable_ipv6, send_arp

setLogLevel("info")
topo = TriangleTopo()
net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
for h in net.hosts: disable_ipv6(h)
for s in net.switches: disable_ipv6(s)
net.start()
time.sleep(3)
for h in net.hosts:
    h.cmd("arping -c 2 -A -I " + h.name + "-eth0 " + h.IP())
    time.sleep(1)
time.sleep(5)
result = net.pingAll()
print(f"SWITCHING pingall: {'PASS (0% loss)' if result == 0 else 'FAIL (loss: ' + str(result) + '%)'}")
net.stop()
