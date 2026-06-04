"""Run integration tests in Mininet VM — streamlined."""
import paramiko, time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.56.101", username="mininet", password="mininet", timeout=10)

# Start controller in background without waiting for output
chan = c.get_transport().open_session()
chan.exec_command(
    "export PATH=$HOME/.local/bin:$PATH && "
    "cd ~/CS305-2026Spring-Project && "
    "nohup osken-manager --observe-links controller.py > /tmp/ctrl.log 2>&1 &")
chan.close()
time.sleep(5)

# Verify controller
chan = c.get_transport().open_session()
chan.exec_command("ss -tlnp 2>/dev/null | grep -E '6653|6633'")
chan.settimeout(5)
out = b""
try:
    while True:
        chunk = chan.recv(4096)
        if not chunk: break
        out += chunk
except: pass
print("Controller:", "RUNNING" if b"LISTEN" in out else "WARNING — check /tmp/ctrl.log")
chan.close()

def run_cmd(cmd, timeout=60):
    """Run a command and return output."""
    chan = c.get_transport().open_session()
    chan.exec_command(cmd)
    chan.settimeout(timeout)
    out = b""
    try:
        while True:
            chunk = chan.recv(4096)
            if not chunk: break
            out += chunk
    except: pass
    chan.close()
    return out.decode("utf-8", errors="replace")

P = "export LANG=C.UTF-8 && export PATH=$HOME/.local/bin:$PATH && cd ~/CS305-2026Spring-Project"

# ----- DHCP Test -----
print("\n" + "="*60)
print("DHCP Integration Test")
print("="*60)

run_cmd(f"{P} && cat > /tmp/dhcp_test.py << 'PYEOF'\n"
         "import sys, time\n"
         "from mininet.net import Mininet\n"
         "from mininet.node import RemoteController\n"
         "from mininet.log import setLogLevel\n"
         "from test_network import TestTopo, disable_ipv6, send_arp, send_dhcp\n"
         "\n"
         "setLogLevel('info')\n"
         "topo = TestTopo()\n"
         "net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)\n"
         "for h in net.hosts: disable_ipv6(h)\n"
         "for s in net.switches: disable_ipv6(s)\n"
         "net.start()\n"
         "time.sleep(1)\n"
         "for h in net.hosts: send_dhcp(h)\n"
         "time.sleep(2)\n"
         "ok = True\n"
         "for h in net.hosts:\n"
         "    ip = h.IP()\n"
         "    print(f'{h.name} IP={ip}')\n"
         "    if not ip.startswith('192.168.1.'): ok = False\n"
         "print(f\"DHCP: {'PASS' if ok else 'FAIL'}\")\n"
         "net.stop()\n"
         "PYEOF\n", 5)

out = run_cmd(f"{P} && cd tests/dhcp_test && sudo env PATH=$PATH python3 /tmp/dhcp_test.py 2>&1", 120)
print(out[-600:])

run_cmd("sudo mn -c 2>/dev/null || true", 10)
time.sleep(2)

# ----- Firewall Test -----
print("\n" + "="*60)
print("Firewall Integration Test")
print("="*60)

run_cmd(f"{P} && cat > /tmp/fw_test.py << 'PYEOF'\n"
         "import sys, time\n"
         "from mininet.net import Mininet\n"
         "from mininet.node import RemoteController\n"
         "from mininet.log import setLogLevel\n"
         "from test_network import FirewallTopo, disable_ipv6, send_arp, curl\n"
         "\n"
         "setLogLevel('info')\n"
         "topo = FirewallTopo()\n"
         "net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)\n"
         "for h in net.hosts: disable_ipv6(h)\n"
         "for s in net.switches: disable_ipv6(s)\n"
         "net.start()\n"
         "time.sleep(1)\n"
         "h1, h2, h3 = net.get('h1'), net.get('h2'), net.get('h3')\n"
         "for _ in range(3):\n"
         "    for h in net.hosts: send_arp(h)\n"
         "    time.sleep(1)\n"
         "h2.cmd('pkill -f python3 || true')\n"
         "h2.cmd('python3 -m http.server 80 --bind 192.168.117.3 >/tmp/h2-80.log 2>&1 &')\n"
         "h2.cmd('python3 -m http.server 8080 --bind 192.168.117.3 >/tmp/h2-8080.log 2>&1 &')\n"
         "time.sleep(2)\n"
         "print('T1 h1->h2 ICMP (expect FAIL):')\n"
         "r1 = h1.cmd('ping -c 2 -W 1 192.168.117.3')\n"
         "print(r1)\n"
         "t1 = '100% packet loss' in r1 or '0 received' in r1\n"
         "print('T2 h1->h3 ICMP (expect PASS):')\n"
         "r2 = h1.cmd('ping -c 2 -W 1 192.168.117.4')\n"
         "print(r2)\n"
         "t2 = '0% packet loss' in r2\n"
         "print('T3 h1->h2 TCP/80 (expect FAIL):')\n"
         "r3 = curl(h1, 'http://192.168.117.3:80/')\n"
         "print(r3)\n"
         "t3 = '000' in r3 or 'timed out' in r3.lower()\n"
         "print('T4 h1->h2 TCP/8080 (expect PASS):')\n"
         "r4 = curl(h1, 'http://192.168.117.3:8080/')\n"
         "print(r4)\n"
         "t4 = '200' in r4 or '404' in r4\n"
         "print(f'T1 ICMP-block: {\"PASS\" if t1 else \"FAIL\"}')\n"
         "print(f'T2 ICMP-allow: {\"PASS\" if t2 else \"FAIL\"}')\n"
         "print(f'T3 TCP80-block: {\"PASS\" if t3 else \"FAIL\"}')\n"
         "print(f'T4 TCP8080-allow: {\"PASS\" if t4 else \"FAIL\"}')\n"
         "h2.cmd('pkill -f python3 || true')\n"
         "net.stop()\n"
         "PYEOF\n", 5)

out = run_cmd(f"{P} && cd tests/firewall_test && sudo env PATH=$PATH python3 /tmp/fw_test.py 2>&1", 120)
print(out[-800:])

run_cmd("sudo mn -c 2>/dev/null || true", 10)
time.sleep(2)

# ----- Switching Test -----
print("\n" + "="*60)
print("Switching Integration Test")
print("="*60)

run_cmd(f"{P} && cat > /tmp/sw_test.py << 'PYEOF'\n"
         "import sys, time\n"
         "from mininet.net import Mininet\n"
         "from mininet.node import RemoteController\n"
         "from mininet.log import setLogLevel\n"
         "from test_network import TriangleTopo, disable_ipv6, send_arp\n"
         "\n"
         "setLogLevel('info')\n"
         "topo = TriangleTopo()\n"
         "net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)\n"
         "for h in net.hosts: disable_ipv6(h)\n"
         "for s in net.switches: disable_ipv6(s)\n"
         "net.start()\n"
         "time.sleep(3)\n"
         "for h in net.hosts:\n"
         "    h.cmd('arping -c 2 -A -I ' + h.name + '-eth0 ' + h.IP())\n"
         "    time.sleep(1)\n"
         "time.sleep(5)\n"
         "result = net.pingAll()\n"
         "print(f'SWITCHING pingall: {\"PASS (0% loss)\" if result == 0 else \"FAIL (\" + str(result) + \"% loss)\"}')\n"
         "net.stop()\n"
         "PYEOF\n", 5)

out = run_cmd(f"{P} && cd tests/switching_test && sudo env PATH=$PATH python3 /tmp/sw_test.py 2>&1", 120)
print(out[-600:])

# ----- Controller Log -----
print("\n" + "="*60)
print("Controller Log (last 40 lines)")
print("="*60)
out = run_cmd("tail -40 /tmp/ctrl.log 2>/dev/null", 10)
print(out[-2000:])

run_cmd("pkill -f osken-manager 2>/dev/null || true", 5)
run_cmd("sudo mn -c 2>/dev/null || true", 10)

c.close()
print("\nAll tests complete!")
