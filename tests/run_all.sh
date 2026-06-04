#!/bin/bash
# Run all integration tests on the Mininet VM
set -e
export LANG=C.UTF-8
export PATH=$HOME/.local/bin:$PATH
cd ~/CS305-2026Spring-Project
RESULTS=/tmp/test_results.txt
> $RESULTS

echo "=== STARTING CONTROLLER ===" | tee -a $RESULTS
osken-manager --observe-links controller.py &>/tmp/ctrl.log &
CTRL_PID=$!
sleep 5
if ss -tlnp | grep -q 6653; then
    echo "Controller running (PID $CTRL_PID)" | tee -a $RESULTS
else
    echo "ERROR: Controller failed to start" | tee -a $RESULTS
    cat /tmp/ctrl.log | tee -a $RESULTS
    exit 1
fi

# ----- DHCP Test -----
echo "" | tee -a $RESULTS
echo "=== DHCP INTEGRATION TEST ===" | tee -a $RESULTS
cd tests/dhcp_test
sudo env PATH=$PATH python3 -c "
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel
from test_network import TestTopo, disable_ipv6, send_arp, send_dhcp
import time
setLogLevel('info')
topo = TestTopo()
net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
for h in net.hosts: disable_ipv6(h)
for s in net.switches: disable_ipv6(s)
net.start()
time.sleep(1)
for h in net.hosts: send_dhcp(h)
time.sleep(2)
ok = True
for h in net.hosts:
    ip = h.IP()
    print(f'{h.name} IP={ip}')
    if not ip.startswith('192.168.1.'): ok = False
print(f\"DHCP: {'PASS' if ok else 'FAIL'}\")
net.stop()
" 2>&1 | tee -a $RESULTS
sudo mn -c 2>/dev/null || true
sleep 2

# ----- Firewall Test -----
echo "" | tee -a $RESULTS
echo "=== FIREWALL INTEGRATION TEST ===" | tee -a $RESULTS
cd ~/CS305-2026Spring-Project/tests/firewall_test
sudo env PATH=$PATH python3 -c "
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel
from test_network import FirewallTopo, disable_ipv6, send_arp, curl
import time
setLogLevel('info')
topo = FirewallTopo()
net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
for h in net.hosts: disable_ipv6(h)
for s in net.switches: disable_ipv6(s)
net.start()
time.sleep(1)
h1, h2, h3 = net.get('h1'), net.get('h2'), net.get('h3')
for _ in range(3):
    for h in net.hosts: send_arp(h)
    time.sleep(1)
h2.cmd('pkill -f python3 || true')
h2.cmd('python3 -m http.server 80 --bind 192.168.117.3 >/tmp/h2-80.log 2>&1 &')
h2.cmd('python3 -m http.server 8080 --bind 192.168.117.3 >/tmp/h2-8080.log 2>&1 &')
time.sleep(2)

print('T1 h1->h2 ICMP (expect FAIL):')
r1 = h1.cmd('ping -c 2 -W 1 192.168.117.3')
print(r1)
t1 = '100% packet loss' in r1 or '0 received' in r1

print('T2 h1->h3 ICMP (expect PASS):')
r2 = h1.cmd('ping -c 2 -W 1 192.168.117.4')
print(r2)
t2 = '0% packet loss' in r2

print('T3 h1->h2 TCP/80 (expect FAIL):')
r3 = curl(h1, 'http://192.168.117.3:80/')
print(r3)
t3 = '000' in r3 or 'timed out' in r3.lower()

print('T4 h1->h2 TCP/8080 (expect PASS):')
r4 = curl(h1, 'http://192.168.117.3:8080/')
print(r4)
t4 = '200' in r4 or '404' in r4

print(f'T1 ICMP-block: {\"PASS\" if t1 else \"FAIL\"}')
print(f'T2 ICMP-allow: {\"PASS\" if t2 else \"FAIL\"}')
print(f'T3 TCP80-block: {\"PASS\" if t3 else \"FAIL\"}')
print(f'T4 TCP8080-allow: {\"PASS\" if t4 else \"FAIL\"}')

h2.cmd('pkill -f python3 || true')
net.stop()
" 2>&1 | tee -a $RESULTS
sudo mn -c 2>/dev/null || true
sleep 2

# ----- Switching Test -----
echo "" | tee -a $RESULTS
echo "=== SWITCHING INTEGRATION TEST ===" | tee -a $RESULTS
cd ~/CS305-2026Spring-Project/tests/switching_test
sudo env PATH=$PATH python3 -c "
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.log import setLogLevel
from test_network import TriangleTopo, disable_ipv6, send_arp
import time
setLogLevel('info')
topo = TriangleTopo()
net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
for h in net.hosts: disable_ipv6(h)
for s in net.switches: disable_ipv6(s)
net.start()
time.sleep(3)
for h in net.hosts:
    h.cmd('arping -c 2 -A -I ' + h.name + '-eth0 ' + h.IP())
    time.sleep(1)
time.sleep(5)
result = net.pingAll()
print(f'SWITCHING pingall: {\"PASS (0% loss)\" if result == 0 else \"FAIL (loss: \" + str(result) + \"%)\"}')
net.stop()
" 2>&1 | tee -a $RESULTS

# ----- Final: Controller log summary -----
echo "" | tee -a $RESULTS
echo "=== CONTROLLER LOG (last 30 lines) ===" | tee -a $RESULTS
tail -30 /tmp/ctrl.log | tee -a $RESULTS

# Cleanup
kill $CTRL_PID 2>/dev/null || true
sudo mn -c 2>/dev/null || true

echo "" | tee -a $RESULTS
echo "=== ALL TESTS COMPLETE ===" | tee -a $RESULTS
