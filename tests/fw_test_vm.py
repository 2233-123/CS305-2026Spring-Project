"""Run on VM: firewall integration test."""
import sys, time
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel
from test_network import FirewallTopo, disable_ipv6, send_arp, curl

setLogLevel("info")
topo = FirewallTopo()
net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
for h in net.hosts: disable_ipv6(h)
for s in net.switches: disable_ipv6(s)
net.start()
time.sleep(1)
h1, h2, h3 = net.get("h1"), net.get("h2"), net.get("h3")
for _ in range(3):
    for h in net.hosts: send_arp(h)
    time.sleep(1)
h2.cmd("pkill -f python3 || true")
h2.cmd("python3 -m http.server 80 --bind 192.168.117.3 >/tmp/h2-80.log 2>&1 &")
h2.cmd("python3 -m http.server 8080 --bind 192.168.117.3 >/tmp/h2-8080.log 2>&1 &")
time.sleep(2)

print("T1 h1->h2 ICMP (expect FAIL):")
r1 = h1.cmd("ping -c 2 -W 1 192.168.117.3"); print(r1)
t1 = "100% packet loss" in r1 or "0 received" in r1

print("T2 h1->h3 ICMP (expect PASS):")
r2 = h1.cmd("ping -c 2 -W 1 192.168.117.4"); print(r2)
t2 = "0% packet loss" in r2

print("T3 h1->h2 TCP/80 (expect FAIL):")
r3 = curl(h1, "http://192.168.117.3:80/"); print(r3)
t3 = "000" in r3 or "timed out" in r3.lower()

print("T4 h1->h2 TCP/8080 (expect PASS):")
r4 = curl(h1, "http://192.168.117.3:8080/"); print(r4)
t4 = "200" in r4 or "404" in r4

print(f"T1 ICMP-block: {'PASS' if t1 else 'FAIL'}")
print(f"T2 ICMP-allow: {'PASS' if t2 else 'FAIL'}")
print(f"T3 TCP80-block: {'PASS' if t3 else 'FAIL'}")
print(f"T4 TCP8080-allow: {'PASS' if t4 else 'FAIL'}")

h2.cmd("pkill -f python3 || true")
net.stop()
