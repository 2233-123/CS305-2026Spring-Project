# firewall.py

import json
import os
from dataclasses import dataclass

from os_ken.ofproto import ether, inet


@dataclass(frozen=True)
class FirewallRule:
    src_ip: str = None
    dst_ip: str = None
    proto: str = None
    src_port: object = None
    dst_port: object = None
    action: str = "deny"


class Firewall:
    COOKIE = 0x305F
    PRIORITY = 60000

    PROTO_MAP = {
        None: 0,
        "": 0,
        "*": 0,
        "any": 0,
        "icmp": inet.IPPROTO_ICMP,
        "tcp": inet.IPPROTO_TCP,
        "udp": inet.IPPROTO_UDP,
    }

    def __init__(self, rule_file="firewall_rules.json"):
        self.rule_file = rule_file
        self.rules = self._load_rules(rule_file)
        self.installed = set()

    def _normalize_any(self, value):
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() in ["", "*", "any"]:
            return None
        return value

    def _normalize_proto(self, proto):
        proto = self._normalize_any(proto)
        if proto is None:
            return None
        return str(proto).lower()

    def _proto_to_number(self, proto):
        proto = self._normalize_proto(proto)
        return self.PROTO_MAP.get(proto, 0)

    def _normalize_port(self, value):
        value = self._normalize_any(value)
        if value is None:
            return 0
        return int(value)

    def _load_rules(self, rule_file):
        rules = []
        if not os.path.exists(rule_file):
            return rules
        with open(rule_file, 'r') as f:
            data = json.load(f)
        for item in data.get('rules', []):
            rule = FirewallRule(
                src_ip=self._normalize_any(item.get('src_ip')),
                dst_ip=self._normalize_any(item.get('dst_ip')),
                proto=self._normalize_proto(item.get('proto')),
                src_port=self._normalize_any(item.get('src_port')),
                dst_port=self._normalize_any(item.get('dst_port')),
                action=item.get('action', 'deny'),
            )
            rules.append(rule)
        return rules

    def install_rules(self, ofctls):
        for dpid, ofctl in ofctls.items():
            for rule in self.rules:
                if rule.action != 'deny':
                    continue

                proto_num = self._proto_to_number(rule.proto)
                src_port = self._normalize_port(rule.src_port)
                dst_port = self._normalize_port(rule.dst_port)

                # Build a unique key for dedup
                rule_key = (rule.src_ip or '*', rule.dst_ip or '*',
                           proto_num, src_port, dst_port, dpid)
                if rule_key in self.installed:
                    continue
                self.installed.add(rule_key)

                # Set dl_type based on protocol
                if proto_num == 0:
                    dl_type = 0
                elif proto_num == inet.IPPROTO_ICMP:
                    dl_type = ether.ETH_TYPE_IP
                else:
                    dl_type = ether.ETH_TYPE_IP

                # For ICMP, no port matching
                if proto_num == inet.IPPROTO_ICMP:
                    ofctl.set_flow(
                        cookie=self.COOKIE, priority=self.PRIORITY,
                        dl_type=dl_type,
                        nw_src=rule.src_ip or 0,
                        src_mask=32 if rule.src_ip else 0,
                        nw_dst=rule.dst_ip or 0,
                        dst_mask=32 if rule.dst_ip else 0,
                        nw_proto=proto_num,
                        actions=[],
                    )
                elif proto_num == 0:
                    # No specific protocol - just IP-based
                    ofctl.set_flow(
                        cookie=self.COOKIE, priority=self.PRIORITY,
                        dl_type=ether.ETH_TYPE_IP,
                        nw_src=rule.src_ip or 0,
                        src_mask=32 if rule.src_ip else 0,
                        nw_dst=rule.dst_ip or 0,
                        dst_mask=32 if rule.dst_ip else 0,
                        actions=[],
                    )
                else:
                    # TCP/UDP with or without ports
                    if src_port == 0 and dst_port == 0:
                        ofctl.set_flow(
                            cookie=self.COOKIE, priority=self.PRIORITY,
                            dl_type=dl_type,
                            nw_src=rule.src_ip or 0,
                            src_mask=32 if rule.src_ip else 0,
                            nw_dst=rule.dst_ip or 0,
                            dst_mask=32 if rule.dst_ip else 0,
                            nw_proto=proto_num,
                            actions=[],
                        )
                    else:
                        ofctl.set_flow(
                            cookie=self.COOKIE, priority=self.PRIORITY,
                            dl_type=dl_type,
                            nw_src=rule.src_ip or 0,
                            src_mask=32 if rule.src_ip else 0,
                            nw_dst=rule.dst_ip or 0,
                            dst_mask=32 if rule.dst_ip else 0,
                            nw_proto=proto_num,
                            tp_src=src_port,
                            tp_dst=dst_port,
                            actions=[],
                        )
