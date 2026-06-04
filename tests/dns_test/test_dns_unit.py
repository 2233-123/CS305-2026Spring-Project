"""Unit tests for DNS server — no controller needed."""

import unittest
import struct
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dns_server import DNSServer, DNSConfig, QTYPE_A, QTYPE_PTR, QCLASS_IN
from dns_server import RCODE_NOERROR, RCODE_NXDOMAIN, QR_MASK, AA_MASK


class TestDNSEncodeDecode(unittest.TestCase):
    def test_encode_simple(self):
        result = DNSServer._encode_domain('h1')
        expected = b'\x02h1\x00'
        self.assertEqual(result, expected)

    def test_encode_fqdn(self):
        result = DNSServer._encode_domain('h1.local')
        expected = b'\x02h1\x05local\x00'
        self.assertEqual(result, expected)

    def test_decode_simple(self):
        data = b'\x02h1\x00'
        name, offset = DNSServer._decode_domain(data, 0)
        self.assertEqual(name, 'h1')
        self.assertEqual(offset, 4)

    def test_decode_fqdn(self):
        data = b'\x02h1\x05local\x00'
        name, offset = DNSServer._decode_domain(data, 0)
        self.assertEqual(name, 'h1.local')
        self.assertEqual(offset, 10)

    def test_decode_with_pointer(self):
        data = b'\x02h1\x00\xc0\x00'
        name, offset = DNSServer._decode_domain(data, 4)
        self.assertEqual(name, 'h1')
        self.assertEqual(offset, 6)


class TestDNSIPPtRConversion(unittest.TestCase):
    def test_ip_to_ptr_name(self):
        result = DNSServer._ip_to_ptr_name('192.168.1.2')
        self.assertEqual(result, '2.1.168.192.in-addr.arpa')

    def test_ptr_name_to_ip(self):
        result = DNSServer._ptr_name_to_ip('2.1.168.192.in-addr.arpa')
        self.assertEqual(result, '192.168.1.2')

    def test_roundtrip(self):
        ip = '10.0.2.100'
        self.assertEqual(DNSServer._ptr_name_to_ip(DNSServer._ip_to_ptr_name(ip)), ip)


class TestDNSRecordManagement(unittest.TestCase):
    def setUp(self):
        DNSServer._records.clear()
        DNSServer._ip_to_hostname.clear()

    def test_add_record(self):
        DNSServer.add_record('h1', '192.168.1.2')
        self.assertEqual(DNSServer._records.get('h1'), '192.168.1.2')
        self.assertEqual(DNSServer._ip_to_hostname.get('192.168.1.2'), 'h1')

    def test_remove_by_hostname(self):
        DNSServer.add_record('h1', '192.168.1.2')
        DNSServer.remove_record(hostname='h1')
        self.assertNotIn('h1', DNSServer._records)
        self.assertNotIn('192.168.1.2', DNSServer._ip_to_hostname)

    def test_remove_by_ip(self):
        DNSServer.add_record('h1', '192.168.1.2')
        DNSServer.remove_record(ip='192.168.1.2')
        self.assertNotIn('h1', DNSServer._records)
        self.assertNotIn('192.168.1.2', DNSServer._ip_to_hostname)

    def test_overwrite_record(self):
        DNSServer.add_record('h1', '192.168.1.2')
        DNSServer.add_record('h1', '192.168.1.3')
        self.assertEqual(DNSServer._records['h1'], '192.168.1.3')
        self.assertNotIn('192.168.1.2', DNSServer._ip_to_hostname)
        self.assertEqual(DNSServer._ip_to_hostname['192.168.1.3'], 'h1')


class TestDNSBuildResponse(unittest.TestCase):
    def test_build_a_response(self):
        txid = 0x1234
        questions = [('h1', QTYPE_A, QCLASS_IN)]
        answers = [('h1', QTYPE_A, DNSConfig.ttl, '192.168.1.2')]
        resp = DNSServer._build_response(txid, questions, answers)

        self.assertEqual(len(resp), 12 + (4 + 2 + 2) + (2 + 2 + 2 + 4 + 2 + 4))
        # Parse and verify header
        parsed_txid = struct.unpack('!H', resp[0:2])[0]
        flags = struct.unpack('!H', resp[2:4])[0]
        qdcount = struct.unpack('!H', resp[4:6])[0]
        ancount = struct.unpack('!H', resp[6:8])[0]

        self.assertEqual(parsed_txid, txid)
        self.assertTrue(flags & QR_MASK)
        self.assertTrue(flags & AA_MASK)
        self.assertEqual(qdcount, 1)
        self.assertEqual(ancount, 1)

    def test_build_nxdomain_response(self):
        txid = 0x5678
        questions = [('unknown', QTYPE_A, QCLASS_IN)]
        resp = DNSServer._build_response(txid, questions, None)

        flags = struct.unpack('!H', resp[2:4])[0]
        ancount = struct.unpack('!H', resp[6:8])[0]
        rcode = flags & 0xF

        self.assertEqual(rcode, RCODE_NXDOMAIN)
        self.assertEqual(ancount, 0)

    def test_build_ptr_response(self):
        txid = 0xAA55
        ptr_name = DNSServer._ip_to_ptr_name('192.168.1.2')
        questions = [(ptr_name, QTYPE_PTR, QCLASS_IN)]
        answers = [(ptr_name, QTYPE_PTR, DNSConfig.ttl, 'h1')]
        resp = DNSServer._build_response(txid, questions, answers)

        flags = struct.unpack('!H', resp[2:4])[0]
        self.assertTrue(flags & QR_MASK)
        ancount = struct.unpack('!H', resp[6:8])[0]
        self.assertEqual(ancount, 1)


class TestDNSQueryParsing(unittest.TestCase):
    """Test parsing of complete DNS query packets."""
    def setUp(self):
        DNSServer._records.clear()
        DNSServer._ip_to_hostname.clear()

    def _build_query(self, name, qtype):
        txid = 0x42
        header = struct.pack('!HHHHHH', txid, 0x0100, 1, 0, 0, 0)
        question = DNSServer._encode_domain(name) + struct.pack('!HH', qtype, QCLASS_IN)
        return header + question

    def test_parse_a_query(self):
        data = self._build_query('h1', QTYPE_A)
        txid = struct.unpack('!H', data[0:2])[0]
        flags = struct.unpack('!H', data[2:4])[0]
        qdcount = struct.unpack('!H', data[4:6])[0]
        self.assertEqual(txid, 0x42)
        self.assertEqual(qdcount, 1)

        offset = 12
        qname, offset = DNSServer._decode_domain(data, offset)
        qtype = struct.unpack('!H', data[offset:offset + 2])[0]
        self.assertEqual(qname, 'h1')
        self.assertEqual(qtype, QTYPE_A)

    def test_parse_ptr_query(self):
        ptr_name = DNSServer._ip_to_ptr_name('192.168.1.2')
        data = self._build_query(ptr_name, QTYPE_PTR)
        offset = 12
        qname, offset = DNSServer._decode_domain(data, offset)
        ip = DNSServer._ptr_name_to_ip(qname)
        self.assertEqual(ip, '192.168.1.2')


if __name__ == '__main__':
    unittest.main()
