"""Automated firewall integration test."""
import time
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel
from test_network import FirewallTopo, disable_ipv6, send_arp, curl

setLogLevel("info")
topo = FirewallTopo()
net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
for h in net.hosts:
    disable_ipv6(h)
for s in net.switches:
    disable_ipv6(s)
net.start()
time.sleep(1)

h1 = net.get("h1")
h2 = net.get("h2")
h3 = net.get("h3")

for _ in range(3):
    for h in net.hosts:
        send_arp(h)
    time.sleep(1)

# Start HTTP servers
h2.cmd("pkill -f \"python3 -m http.server\" || true")
h2.cmd("python3 -m http.server 80 --bind 192.168.117.3 >/tmp/h2-http80.log 2>&1 &")
h2.cmd("python3 -m http.server 8080 --bind 192.168.117.3 >/tmp/h2-http8080.log 2>&1 &")
time.sleep(2)

print("=== Test 1: h1 -> h2 ICMP (should FAIL) ===")
out1 = h1.cmd("ping -c 2 -W 1 192.168.117.3")
print(out1)
t1_pass = "100% packet loss" in out1 or "0 received" in out1

print("=== Test 2: h1 -> h3 ICMP (should PASS) ===")
out2 = h1.cmd("ping -c 2 -W 1 192.168.117.4")
print(out2)
t2_pass = "0% packet loss" in out2

print("=== Test 3: h1 -> h2 TCP/80 (should FAIL) ===")
out3 = curl(h1, "http://192.168.117.3:80/")
print(out3)
t3_pass = "000" in out3 or "timed out" in out3.lower() or "Connection refused" in out3

print("=== Test 4: h1 -> h2 TCP/8080 (should PASS) ===")
out4 = curl(h1, "http://192.168.117.3:8080/")
print(out4)
t4_pass = "200" in out4 or "404" in out4 or "301" in out4

print()
result = "PASS" if t1_pass else "FAIL"
print("Test 1 (ICMP block h1->h2): " + result)
result = "PASS" if t2_pass else "FAIL"
print("Test 2 (ICMP allow h1->h3): " + result)
result = "PASS" if t3_pass else "FAIL"
print("Test 3 (TCP/80 block h1->h2): " + result)
result = "PASS" if t4_pass else "FAIL"
print("Test 4 (TCP/8080 allow h1->h2): " + result)

h2.cmd("pkill -f \"python3 -m http.server\" || true")
net.stop()
