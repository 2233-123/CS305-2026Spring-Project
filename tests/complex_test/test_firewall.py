"""
Firewall + Shortest Path Combined Test — Complex Topology

Reuses the complex topology (8 switches, 8 hosts, 13 edges).
Demonstrates that firewall rules make previously reachable hosts unreachable.

Two-phase demo:
  Phase 1 (firewall active):  h1 -> h2 blocked; other hosts reachable
  Phase 2 (firewall removed): all hosts reachable

Usage:
  Terminal 1: osken-manager --observe-links controller.py
  Terminal 2: sudo env "PATH=$PATH" python tests/complex_test/test_firewall.py

Firewall rules (written to firewall_rules.json before controller starts):
  - Deny ICMP from 192.168.100.2 (h1) to 192.168.100.3 (h2)
  - Deny TCP/80 from 192.168.100.2 (h1) to 192.168.100.3 (h2)
"""
import json
import os
import sys
import time

from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo


# static IP config for firewall test
HOST_IPS = {
    "h1": "192.168.100.2/24",
    "h2": "192.168.100.3/24",
    "h3": "192.168.100.4/24",
    "h4": "192.168.100.5/24",
    "h5": "192.168.100.6/24",
    "h6": "192.168.100.7/24",
    "h7": "192.168.100.8/24",
    "h8": "192.168.100.9/24",
}

FIREWALL_RULES = {
    "rules": [
        {
            "src_ip": "192.168.100.2",
            "dst_ip": "192.168.100.3",
            "proto": "icmp",
            "src_port": "*",
            "dst_port": "*",
            "action": "deny",
        },
        {
            "src_ip": "192.168.100.2",
            "dst_ip": "192.168.100.3",
            "proto": "tcp",
            "src_port": "*",
            "dst_port": 80,
            "action": "deny",
        },
    ]
}


def disable_ipv6(node):
    node.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
    node.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")


def send_arp(node, count=1):
    node.cmd("arping -c %d -A -I %s-eth0 %s" % (count, node.name, node.IP()))


def do_arp_all(net):
    for h in net.hosts:
        send_arp(h)


class FirewallComplexTopo(Topo):
    """Same topology as the shortest-path complex test, but with static IPs."""
    def __init__(self, **opts):
        Topo.__init__(self, **opts)

        hosts = {}
        for i in range(1, 9):
            ip = HOST_IPS.get("h%d" % i, "no ip defined/8")
            hosts[i] = self.addHost("h%d" % i, ip=ip)

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


def save_original_rules():
    if os.path.exists("firewall_rules.json"):
        with open("firewall_rules.json", "r") as f:
            return json.load(f)
    return {"rules": []}


def write_firewall_rules():
    with open("firewall_rules.json", "w") as f:
        json.dump(FIREWALL_RULES, f, indent=2)
    print("Written firewall_rules.json with rules blocking h1(192.168.100.2) -> h2(192.168.100.3)")


def restore_rules(rules):
    with open("firewall_rules.json", "w") as f:
        json.dump(rules, f, indent=2)


def curl(host, url):
    cmd = (
        "curl -sS --connect-timeout 2 -m 3 "
        "-o /dev/null -w 'HTTP_CODE=%%{http_code}\\n' "
        "%s 2>&1" % url
    )
    return host.cmd(cmd)


def run_mininet(phase):
    topo = FirewallComplexTopo()
    net = Mininet(topo=topo, autoSetMacs=True, controller=RemoteController)

    for h in net.hosts:
        disable_ipv6(h)
    for s in net.switches:
        disable_ipv6(s)

    net.start()
    time.sleep(1)

    h1, h2, h3 = net.get("h1", "h2", "h3")
    s1 = net.get("s1")

    for _ in range(3):
        do_arp_all(net)
        time.sleep(1)

    print()
    print("=" * 70)
    if phase == 1:
        print("  FIREWALL TEST — Phase 1: Firewall ACTIVE")
        print("  Rules: DENY ICMP + TCP/80 from 192.168.100.2 -> 192.168.100.3")
    else:
        print("  FIREWALL TEST — Phase 2: Firewall REMOVED")
        print("  No firewall rules — all hosts should be reachable")
    print("=" * 70)
    print()

    print("--- Test: h1(.2) -> h2(.3) ICMP ---")
    out = h1.cmd("ping -c 2 -W 1 192.168.100.3")
    print(out)
    if "100% packet loss" in out:
        print(">>> RESULT: h1 -> h2 BLOCKED (firewall denies ICMP)")
    elif "0% packet loss" in out:
        print(">>> RESULT: h1 -> h2 REACHABLE (no firewall blocking)")

    print("--- Test: h1(.2) -> h3(.4) ICMP ---")
    out = h1.cmd("ping -c 2 -W 1 192.168.100.4")
    print(out)
    if "0% packet loss" in out:
        print(">>> RESULT: h1 -> h3 REACHABLE (not blocked by firewall)")

    if phase == 1:
        print("--- Test: h1 -> h2 TCP/80 ---")
        h2.cmd("pkill -f 'python3 -m http.server' || true")
        h2.cmd("python3 -m http.server 80 --bind 192.168.100.3 >/tmp/h2-http80.log 2>&1 &")
        time.sleep(1)
        print(curl(h1, "http://192.168.100.3:80/"))
        print(">>> RESULT: h1 -> h2 TCP/80 BLOCKED (firewall denies)")
        h2.cmd("pkill -f 'python3 -m http.server' || true")

    print("--- Test: Other host reachability ---")
    print(h1.cmd("ping -c 1 -W 1 192.168.100.5"))
    print(h1.cmd("ping -c 1 -W 1 192.168.100.8"))

    print()
    print("Check controller console for:")
    print("  [Topology] Switch-to-Switch Shortest Paths")
    print("  [NetworkX] Graph info + nx paths")
    print()

    if phase == 2:
        print(">>> Now ALL hosts should be reachable (firewall removed).")
        print(">>> Compare with Phase 1 where h1 -> h2 was blocked.")
        print()

    CLI(net)

    h2.cmd("pkill -f 'python3 -m http.server' || true")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")

    original = save_original_rules()

    # Phase 1: With firewall rules
    write_firewall_rules()
    print()
    print("=" * 70)
    print("  PHASE 1 — START CONTROLLER WITH FIREWALL RULES ACTIVE")
    print("  Run: osken-manager --observe-links controller.py")
    print("  Then press ENTER in this terminal to start Mininet...")
    print("=" * 70)
    input(">>> Press ENTER to run Phase 1 (firewall active). Ctrl+C to skip.")

    run_mininet(phase=1)

    # Phase 2: Without firewall rules
    print()
    print("=" * 70)
    print("  PHASE 2 — RESTART CONTROLLER WITHOUT FIREWALL RULES")
    print("  1. Stop the controller (Ctrl+C in terminal 1)")
    print("  2. Wait for this script to remove firewall rules...")
    print("=" * 70)

    restore_rules(original)
    print("Firewall rules removed. firewall_rules.json restored to original.")

    input(">>> Press ENTER to run Phase 2 (firewall removed). Ctrl+C to skip.")

    print()
    print("=" * 70)
    print("  PHASE 2 — RESTART CONTROLLER, THEN PRESS ENTER")
    print("  Run: osken-manager --observe-links controller.py")
    print("  Then press ENTER here to start Mininet...")
    print("=" * 70)
    input(">>> Press ENTER to run Phase 2.")

    run_mininet(phase=2)

    print()
    print("Demo complete.")
