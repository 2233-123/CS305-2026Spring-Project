"""
Standalone unit test for DHCP lease management logic.
Does not require os-ken — tests the core data structures and algorithms.
"""
import struct
import socket
import time
import sys

# ---------------------------------------------------------------------------
# Replicate the lease logic from dhcp.py (without os-ken imports)
# ---------------------------------------------------------------------------

class DHCPConfig:
    dns = '8.8.8.8'
    start_ip = '192.168.1.2'
    end_ip = '192.168.1.3'       # narrow range for exhaustion test
    netmask = '255.255.255.0'
    lease_time = 3                # 3 seconds for fast testing

LEASE_OFFERED = 'OFFERED'
LEASE_ALLOCATED = 'ALLOCATED'
LEASE_RELEASED = 'RELEASED'


class DHCPServerStub:
    """Mirrors the logic of the real DHCPServer but without os-ken."""

    start_ip = DHCPConfig.start_ip
    end_ip = DHCPConfig.end_ip
    lease_time = DHCPConfig.lease_time

    mac_to_lease = {}
    ip_to_mac = {}

    @classmethod
    def _ip_to_int(cls, ip_str):
        return struct.unpack('!I', socket.inet_aton(ip_str))[0]

    @classmethod
    def _int_to_ip(cls, ip_int):
        return socket.inet_ntoa(struct.pack('!I', ip_int))

    @classmethod
    def _now(cls):
        return time.time()

    @classmethod
    def _release_lease(cls, mac_addr):
        if mac_addr in cls.mac_to_lease:
            info = cls.mac_to_lease[mac_addr]
            ip = info['ip']
            cls.mac_to_lease[mac_addr]['state'] = LEASE_RELEASED
            cls.mac_to_lease[mac_addr]['expires_at'] = 0
            if ip in cls.ip_to_mac:
                del cls.ip_to_mac[ip]

    @classmethod
    def _find_free_ip(cls, mac_addr):
        if mac_addr in cls.mac_to_lease:
            info = cls.mac_to_lease[mac_addr]
            if info['state'] == LEASE_ALLOCATED:
                return info['ip']

        now = cls._now()
        used = set()
        for mac, info in cls.mac_to_lease.items():
            if info['state'] == LEASE_ALLOCATED and now < info['expires_at']:
                used.add(info['ip'])

        start = cls._ip_to_int(cls.start_ip)
        end = cls._ip_to_int(cls.end_ip)
        for ip_int in range(start, end + 1):
            ip_str = cls._int_to_ip(ip_int)
            if ip_str not in used:
                cls.mac_to_lease[mac_addr] = {
                    'ip': ip_str,
                    'assigned_at': now,
                    'expires_at': now + cls.lease_time,
                    'state': LEASE_OFFERED,
                }
                return ip_str
        return None

    @classmethod
    def ack(cls, mac_addr):
        """Simulate ACK: transition OFFERED -> ALLOCATED or renew."""
        now = cls._now()
        lease = cls.mac_to_lease.get(mac_addr)
        if lease is not None and lease['state'] == LEASE_OFFERED:
            lease['state'] = LEASE_ALLOCATED
            lease['assigned_at'] = now
            lease['expires_at'] = now + cls.lease_time
            cls.ip_to_mac[lease['ip']] = mac_addr
            return lease['ip']
        elif lease is not None and lease['state'] == LEASE_ALLOCATED:
            lease['expires_at'] = now + cls.lease_time
            return lease['ip']
        else:
            ip = cls._find_free_ip(mac_addr)
            if ip is None:
                return None
            cls.mac_to_lease[mac_addr] = {
                'ip': ip,
                'assigned_at': now,
                'expires_at': now + cls.lease_time,
                'state': LEASE_ALLOCATED,
            }
            cls.ip_to_mac[ip] = mac_addr
            return ip

    @classmethod
    def _lease_reaper(cls):
        """One-off scan (not a loop for unit test)."""
        now = cls._now()
        expired = []
        for mac, info in cls.mac_to_lease.items():
            if info['state'] == LEASE_ALLOCATED and now >= info['expires_at']:
                expired.append(mac)
        for mac in expired:
            cls._release_lease(mac)
        return len(expired)

    @classmethod
    def reset(cls):
        cls.mac_to_lease.clear()
        cls.ip_to_mac.clear()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0


def check(condition, test_name):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅  PASS: {test_name}")
    else:
        FAIL += 1
        print(f"  ❌  FAIL: {test_name}")


# --- Test 1: Basic allocation (DISCOVER -> OFFER -> ACK) ---
def test_basic_allocation():
    print("\n=== Test 1: Basic allocation ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    ip = DHCPServerStub._find_free_ip(mac1)
    check(ip is not None, "OFFER: got an IP")
    check(DHCPServerStub.mac_to_lease[mac1]['state'] == LEASE_OFFERED, "state = OFFERED after offer")

    acked_ip = DHCPServerStub.ack(mac1)
    check(acked_ip == ip, "ACK: same IP returned")
    check(DHCPServerStub.mac_to_lease[mac1]['state'] == LEASE_ALLOCATED, "state = ALLOCATED after ACK")
    check(DHCPServerStub.ip_to_mac[acked_ip] == mac1, "ip_to_mac mapping correct")


# --- Test 2: Two hosts get different IPs ---
def test_two_hosts_different_ips():
    print("\n=== Test 2: Two hosts — different IPs ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'
    mac2 = b'\x00\x00\x00\x00\x00\x02'

    ip1 = DHCPServerStub._find_free_ip(mac1)
    DHCPServerStub.ack(mac1)
    ip2 = DHCPServerStub._find_free_ip(mac2)
    DHCPServerStub.ack(mac2)

    check(ip1 is not None and ip2 is not None, "both got IPs")
    check(ip1 != ip2, f"different IPs: {ip1} vs {ip2}")


# --- Test 3: IP pool exhaustion ---
def test_ip_exhaustion():
    print("\n=== Test 3: IP pool exhaustion ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'
    mac2 = b'\x00\x00\x00\x00\x00\x02'
    mac3 = b'\x00\x00\x00\x00\x00\x03'

    DHCPServerStub._find_free_ip(mac1)
    DHCPServerStub.ack(mac1)
    DHCPServerStub._find_free_ip(mac2)
    DHCPServerStub.ack(mac2)

    ip3 = DHCPServerStub._find_free_ip(mac3)
    check(ip3 is None, "3rd host gets None — pool exhausted")


# --- Test 4: DHCP Release ---
def test_dhcp_release():
    print("\n=== Test 4: DHCPRELEASE ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'
    mac2 = b'\x00\x00\x00\x00\x00\x02'

    ip1 = DHCPServerStub._find_free_ip(mac1)
    DHCPServerStub.ack(mac1)

    DHCPServerStub._release_lease(mac1)
    check(DHCPServerStub.mac_to_lease[mac1]['state'] == LEASE_RELEASED, "state = RELEASED")
    check(mac1 not in DHCPServerStub.ip_to_mac.values(), "removed from ip_to_mac")

    ip2 = DHCPServerStub._find_free_ip(mac2)
    DHCPServerStub.ack(mac2)
    check(ip2 is not None, "host 2 got IP after host 1 released")


# --- Test 5: Lease expiry and auto-reclaim ---
def test_lease_expiry():
    print("\n=== Test 5: Lease expiry auto-reclaim ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'
    mac2 = b'\x00\x00\x00\x00\x00\x02'
    mac3 = b'\x00\x00\x00\x00\x00\x03'

    DHCPServerStub._find_free_ip(mac1)
    DHCPServerStub.ack(mac1)
    DHCPServerStub._find_free_ip(mac2)
    DHCPServerStub.ack(mac2)

    print(f"  Waiting {DHCPConfig.lease_time + 1}s for leases to expire...")
    time.sleep(DHCPConfig.lease_time + 1)

    reclaimed = DHCPServerStub._lease_reaper()
    check(reclaimed >= 2, f"reaper reclaimed {reclaimed} leases (expect >= 2)")

    ip3 = DHCPServerStub._find_free_ip(mac3)
    DHCPServerStub.ack(mac3)
    check(ip3 is not None and ip3 == '192.168.1.2', "host 3 got reclaimed IP .2")


# --- Test 6: Renewal refreshes expiry ---
def test_renewal():
    print("\n=== Test 6: Lease renewal ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    DHCPServerStub._find_free_ip(mac1)
    DHCPServerStub.ack(mac1)
    first_expiry = DHCPServerStub.mac_to_lease[mac1]['expires_at']

    time.sleep(2)
    DHCPServerStub.ack(mac1)   # renew
    second_expiry = DHCPServerStub.mac_to_lease[mac1]['expires_at']

    check(second_expiry > first_expiry, f"expiry refreshed: {first_expiry:.1f} -> {second_expiry:.1f}")


# --- Test 7: Re-request gets same IP (idempotent) ---
def test_same_ip_repeat():
    print("\n=== Test 7: Re-request — same IP ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    ip1 = DHCPServerStub._find_free_ip(mac1)
    DHCPServerStub.ack(mac1)
    ip2 = DHCPServerStub._find_free_ip(mac1)

    check(ip1 == ip2, f"same MAC gets same IP: {ip1}")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=" * 60)
    print("DHCP Lease Duration — Unit Tests")
    print("=" * 60)

    test_basic_allocation()
    test_two_hosts_different_ips()
    test_ip_exhaustion()
    test_dhcp_release()
    test_lease_expiry()
    test_renewal()
    test_same_ip_repeat()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
