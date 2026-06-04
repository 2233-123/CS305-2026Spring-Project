"""
DHCP Test — IP Pool Exhaustion

Creates m hosts where m > n (n = end_ip - start_ip + 1).
First n hosts get IPs, remaining m-n hosts get none.

This script modifies dhcp.py ON DISK to narrow the IP range,
because the controller reads config from dhcp.py directly.
The original dhcp.py is restored after the test.

Default after patch: start_ip='192.168.1.2', end_ip='192.168.1.5'
  -> 4 IPs available, 8 hosts created -> first 4 get IPs

Usage:
  Terminal 1: osken-manager --observe-links controller.py
  Terminal 2: sudo env "PATH=$PATH" python tests/dhcp_test/test_network_exhaust.py

  IMPORTANT: You MUST restart the controller after this script starts,
  because it modifies dhcp.py before launching Mininet.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../..')

from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
import time

DHCP_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'dhcp.py')

POOL_SIZE = 4
NUM_HOSTS = 8

EXHAUST_CONFIG = {
    "start_ip": "192.168.1.2",
    "end_ip": "192.168.1.5",
    "netmask": "255.255.255.0",
    "server_ip": "192.168.1.1",
    "dns": "192.168.1.1",
    "lease_time": 60,
}


def _backup_dhcp():
    with open(DHCP_PY, 'r') as f:
        return f.read()


def _patch_dhcp(config):
    """Modify dhcp.py in-place: replace DHCPConfig class attributes on exact lines."""
    content = _backup_dhcp()
    lines = content.split('\n')
    patched = []
    for line in lines:
        stripped = line.lstrip()
        matched = False
        for key, value in config.items():
            prefix = key + ' ='
            prefix_dhcp = key + ' = DHCPConfig.' + key
            if stripped.startswith(prefix) or stripped.startswith(prefix_dhcp):
                indent = line[:len(line) - len(line.lstrip())]
                new_line = indent + key + ' = ' + repr(value)
                patched.append(new_line)
                matched = True
                break
        if not matched:
            patched.append(line)
    patched_content = '\n'.join(patched)
    with open(DHCP_PY, 'w') as f:
        f.write(patched_content)
    print("[DHCP patch] Updated dhcp.py: start=%s end=%s" %
          (config['start_ip'], config['end_ip']))


def _restore_dhcp(original):
    with open(DHCP_PY, 'w') as f:
        f.write(original)
    print("[DHCP patch] Restored original dhcp.py")


def disable_ipv6(node):
    node.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")


def send_dhcp(node):
    node.cmd('rm -f /var/lib/dhcp/dhclient*.leases')
    node.cmd('dhclient -v %s-eth0 &' % node.name)
    time.sleep(3)
    # SIGKILL (-9) does NOT trigger DHCPRELEASE
    node.cmd('pkill -9 -f "dhclient.*%s-eth0" 2>/dev/null; true' % node.name)
    time.sleep(0.2)
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    return out


class ExhaustTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        s1 = self.addSwitch('s1')
        for i in range(1, NUM_HOSTS + 1):
            h = self.addHost('h%d' % i, ip='no ip defined/8')
            self.addLink(h, s1)


def run_mininet():
    topo = ExhaustTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for h in net.hosts:
        disable_ipv6(h)
    for h in net.switches:
        disable_ipv6(h)

    net.start()
    time.sleep(1)

    print("=== IP Pool: 192.168.1.2 -> 192.168.1.5 (%d IPs), %d hosts ===" %
          (POOL_SIZE, NUM_HOSTS))

    assigned = 0
    for h in net.hosts:
        print('Sending DHCP request dhclient -v %s-eth0' % h.name)
        ip = send_dhcp(h)
        if ip:
            print("  %s: %s (ASSIGNED)" % (h.name, ip))
            assigned += 1
        else:
            print("  %s: NO IP (POOL EXHAUSTED)" % h.name)

    print("\n=== Result: %d/%d hosts got IPs (expecting %d) ===" %
          (assigned, NUM_HOSTS, POOL_SIZE))
    if assigned == POOL_SIZE:
        print("PASS: exactly %d hosts received IPs as expected" % POOL_SIZE)
    else:
        print("FAIL: got %d instead of %d" % (assigned, POOL_SIZE))

    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')

    original = _backup_dhcp()
    _patch_dhcp(EXHAUST_CONFIG)

    print()
    print("=" * 60)
    print("  DHCP POOL EXHAUSTION TEST")
    print("  Pool: 192.168.1.2 - 192.168.1.5  (%d IPs)" % POOL_SIZE)
    print("  Hosts: %d  (m=%d > n=%d)" % (NUM_HOSTS, NUM_HOSTS, POOL_SIZE))
    print()
    print("  MAKE SURE the controller is STARTED with the modified dhcp.py.")
    print("  If already running, RESTART the controller NOW (Ctrl+C and re-run):")
    print("    osken-manager --observe-links controller.py")
    print("=" * 60)
    input(">>> Press ENTER when controller is ready... ")

    try:
        run_mininet()
    finally:
        _restore_dhcp(original)
