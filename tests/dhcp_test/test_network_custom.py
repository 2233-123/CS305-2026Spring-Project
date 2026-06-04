"""
DHCP Test — Custom IP range (changed start_ip, end_ip, netmask)

This script modifies dhcp.py ON DISK to change the DHCP configuration,
because the controller (osken-manager) runs in a separate process and
reads the config from dhcp.py directly.

The original dhcp.py is restored after the test exits.

Usage:
  Terminal 1: osken-manager --observe-links controller.py
  Terminal 2: sudo env "PATH=$PATH" python tests/dhcp_test/test_network_custom.py

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

EXPECTED_START = '10.0.0.'

CUSTOM_CONFIG = {
    "start_ip": "10.0.0.10",
    "end_ip": "10.0.0.20",
    "netmask": "255.255.255.0",
    "server_ip": "10.0.0.1",
    "dns": "10.0.0.1",
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
    print("[DHCP patch] Updated dhcp.py: %s" %
          {k: v for k, v in config.items() if k != 'lease_time'})


def _restore_dhcp(original):
    with open(DHCP_PY, 'w') as f:
        f.write(original)
    print("[DHCP patch] Restored original dhcp.py")


def disable_ipv6(node):
    node.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")


def send_arp(node, count=1):
    node.cmd('arping -c %d -A -I %s-eth0 %s' % (count, node.name, node.IP()))


def send_dhcp(node):
    node.cmd('rm -f /var/lib/dhcp/dhclient*.leases')
    node.cmd('ip addr flush dev %s-eth0 2>/dev/null' % node.name)
    node.cmd('dhclient -v %s-eth0 2>/tmp/dhclient_%s.log' % (node.name, node.name))
    time.sleep(4)
    out = node.cmd('ip addr show %s-eth0 | grep "inet " | awk \'{print $2}\' | cut -d/ -f1' % node.name).strip()
    if out:
        node.setIP(out, prefixLen=24)
    # Print DHCP server that responded
    log_out = node.cmd('grep -i "DHCPOFFER\|DHCPACK\|offer\|ack" /tmp/dhclient_%s.log 2>/dev/null | head -5' % node.name)
    if log_out.strip():
        print('    dhclient log: %s' % log_out.strip()[:200])
    return out


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


class TestTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)
        hosts = [self.addHost('h%d' % i, ip='no ip defined/8') for i in range(1, 7)]
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        self.addLink(hosts[0], s1)
        self.addLink(hosts[1], s1)
        self.addLink(hosts[2], s2)
        self.addLink(hosts[3], s2)
        self.addLink(hosts[4], s3)
        self.addLink(hosts[5], s3)
        self.addLink(s1, s2)
        self.addLink(s2, s3)


def run_mininet():
    topo = TestTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)
    for h in net.hosts:
        disable_ipv6(h)
    for h in net.switches:
        disable_ipv6(h)

    net.start()
    time.sleep(1)

    ips = {}
    for h in net.hosts:
        print('Sending DHCP request dhclient -v %s-eth0' % h.name)
        ip = send_dhcp(h)
        ips[h.name] = ip
        if ip:
            status = "OK" if ip.startswith(EXPECTED_START) else "WRONG SUBNET"
            print("  %s: %s [%s]" % (h.name, ip, status))
        else:
            print("  %s: NO IP" % h.name)

    do_arp_all(net)
    time.sleep(1)

    print("\n=== Ping test ===")
    h1 = net.get('h1')
    h3 = net.get('h3')
    ip_to_ping = ips.get('h3', '10.0.0.13')
    if ip_to_ping:
        print(h1.cmd('ping -c 2 -W 1 %s' % ip_to_ping))

    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')

    original = _backup_dhcp()
    _patch_dhcp(CUSTOM_CONFIG)

    print()
    print("=" * 60)
    print("  DHCP CUSTOM CONFIGURATION")
    print("  start_ip: 10.0.0.10    end_ip: 10.0.0.20")
    print("  netmask:  255.255.255.0")
    print()
    print("  MAKE SURE the controller is STARTED with the modified dhcp.py.")
    print("  If already running, RESTART the controller NOW (Ctrl+C and re-run):")
    print("    pkill -9 -f osken-manager")
    print("    find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null")
    print("    find . -name '*.pyc' -delete")
    print("    osken-manager --observe-links controller.py")
    print("=" * 60)
    input(">>> Press ENTER when controller is ready... ")

    try:
        run_mininet()
    finally:
        _restore_dhcp(original)
