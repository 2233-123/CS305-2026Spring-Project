"""Unit tests for NAT — no controller needed."""

import unittest
import time
import socket
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from nat import (
    NATTable, NATConfig, _ip_to_int, _int_to_ip, _ip_in_network, _checksum,
    _parse_eth_ip, PROTO_TCP, PROTO_UDP, PROTO_ICMP,
    TCP_STATE_NEW, TCP_STATE_ESTABLISHED, TCP_STATE_CLOSING,
)


class TestIPHelpers(unittest.TestCase):
    def test_ip_to_int_and_back(self):
        ip = '192.168.1.2'
        self.assertEqual(_int_to_ip(_ip_to_int(ip)), ip)

    def test_ip_to_int_zero(self):
        self.assertEqual(_int_to_ip(0), '0.0.0.0')

    def test_ip_to_int_max(self):
        self.assertEqual(_int_to_ip(0xFFFFFFFF), '255.255.255.255')


class TestChecksum(unittest.TestCase):
    def test_basic_checksum(self):
        data = b'\x00\x01\x00\x02'
        result = _checksum(data)
        self.assertIsInstance(result, int)

    def test_checksum_ip_header(self):
        hdr = struct.pack('!BBHHHBBH',
                          0x45, 0, 20, 0, 0x4000,
                          64, 17, 0) + b'\xc0\xa8\x01\x01' + b'\xc0\xa8\x01\x02'
        csum = _checksum(hdr)
        self.assertIsInstance(csum, int)
        self.assertLess(csum, 0x10000)


class TestIPInNetwork(unittest.TestCase):
    def test_in_network(self):
        self.assertTrue(_ip_in_network('192.168.1.5', '192.168.1.0', 24))

    def test_not_in_network(self):
        self.assertFalse(_ip_in_network('10.0.2.100', '192.168.1.0', 24))

    def test_network_broadcast(self):
        self.assertTrue(_ip_in_network('192.168.1.255', '192.168.1.0', 24))


class TestParseEthIP(unittest.TestCase):
    def test_parse_valid_ip_packet(self):
        eth = struct.pack('!6s6sH',
                          bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x01]),
                          bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x02]),
                          0x0800)
        ip = struct.pack('!BBHHHBBH',
                         0x45, 0, 20, 0, 0x4000,
                         64, 6, 0) + socket.inet_aton('10.0.0.1') + socket.inet_aton('10.0.0.2')
        raw = eth + ip
        info = _parse_eth_ip(raw)
        self.assertIsNotNone(info)
        self.assertEqual(info['src_ip'], '10.0.0.1')
        self.assertEqual(info['dst_ip'], '10.0.0.2')
        self.assertEqual(info['proto'], PROTO_TCP)

    def test_parse_non_ip(self):
        eth = struct.pack('!6s6sH',
                          bytes(6), bytes(6), 0x0806)
        info = _parse_eth_ip(eth + bytes(20))
        self.assertIsNone(info)

    def test_parse_too_short(self):
        info = _parse_eth_ip(b'\x00' * 10)
        self.assertIsNone(info)


class TestNATTableBasics(unittest.TestCase):
    def setUp(self):
        NATTable._connections.clear()
        NATTable._port_index.clear()
        NATTable._next_port = 1024

    def test_create_entry(self):
        entry = NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip, bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x01])
        )
        self.assertEqual(entry['src_ip'], '192.168.1.2')
        self.assertEqual(entry['src_port'], 12345)
        self.assertEqual(entry['nat_ip'], NATConfig.external_ip)
        self.assertEqual(entry['proto'], PROTO_TCP)
        self.assertEqual(entry['state'], TCP_STATE_NEW)

    def test_entry_port_increment(self):
        e1 = NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )
        e2 = NATTable._create_entry(
            '192.168.1.3', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )
        self.assertEqual(e1['nat_port'], 1024)
        self.assertEqual(e2['nat_port'], 1025)

    def test_lookup_outbound(self):
        key_base = ('192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP)
        created = NATTable._create_entry(*key_base, NATConfig.external_ip)
        found = NATTable._lookup_outbound(*key_base)
        self.assertIsNotNone(found)
        self.assertEqual(found['nat_port'], created['nat_port'])

    def test_lookup_outbound_not_found(self):
        found = NATTable._lookup_outbound('192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP)
        self.assertIsNone(found)

    def test_lookup_inbound(self):
        NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )
        found = NATTable._lookup_inbound(NATConfig.external_ip, 1024, PROTO_TCP)
        self.assertIsNotNone(found)
        self.assertEqual(found['src_ip'], '192.168.1.2')

    def test_lookup_inbound_wrong_proto(self):
        NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )
        found = NATTable._lookup_inbound(NATConfig.external_ip, 1024, PROTO_UDP)
        self.assertIsNone(found)

    def test_inbound_not_found(self):
        found = NATTable._lookup_inbound(NATConfig.external_ip, 9999, PROTO_TCP)
        self.assertIsNone(found)


class TestNATTCPState(unittest.TestCase):
    def setUp(self):
        NATTable._connections.clear()
        NATTable._port_index.clear()

    def _create_tcp_entry(self):
        return NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )

    def test_initial_state(self):
        entry = self._create_tcp_entry()
        self.assertEqual(entry['state'], TCP_STATE_NEW)

    def test_syn_synack_established(self):
        entry = self._create_tcp_entry()
        NATTable._update_tcp_state(entry, 0x02)  # SYN
        self.assertEqual(entry['state'], TCP_STATE_NEW)
        NATTable._update_tcp_state(entry, 0x12)  # SYN+ACK
        self.assertEqual(entry['state'], TCP_STATE_ESTABLISHED)

    def test_fin_closing(self):
        entry = NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )
        NATTable._update_tcp_state(entry, 0x01)  # FIN
        self.assertEqual(entry['state'], TCP_STATE_CLOSING)

    def test_rst_closing(self):
        entry = NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_TCP,
            NATConfig.external_ip
        )
        NATTable._update_tcp_state(entry, 0x04)  # RST
        self.assertEqual(entry['state'], TCP_STATE_CLOSING)

    def test_non_tcp_no_state_change(self):
        entry = NATTable._create_entry(
            '192.168.1.2', 0, '10.0.2.100', 0, PROTO_ICMP,
            NATConfig.external_ip
        )
        original = entry['state']
        NATTable._update_tcp_state(entry, 0x01)
        self.assertEqual(entry['state'], original)


class TestNATGC(unittest.TestCase):
    def setUp(self):
        NATTable._connections.clear()
        NATTable._port_index.clear()
        NATTable._next_port = 1024

    def test_gc_removes_expired(self):
        entry = NATTable._create_entry(
            '192.168.1.2', 12345, '10.0.2.100', 80, PROTO_UDP,
            NATConfig.external_ip
        )
        entry['last_seen'] = 0  # force expiry
        self.assertEqual(len(NATTable._connections), 1)
        # Run GC manually (not as greenlet)
        now = time.time()
        to_remove = []
        for key, e in list(NATTable._connections.items()):
            if now - e['last_seen'] > NATConfig.udp_timeout:
                to_remove.append(key)
        for key in to_remove:
            ent = NATTable._connections.pop(key, None)
            if ent:
                NATTable._port_index.pop(ent['nat_port'], None)
        self.assertEqual(len(NATTable._connections), 0)
        self.assertEqual(len(NATTable._port_index), 0)


if __name__ == '__main__':
    unittest.main()
