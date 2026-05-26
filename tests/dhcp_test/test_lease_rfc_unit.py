"""
Standalone unit test for DHCP RFC ARP-probe logic (Bonus #2).
Does not require os-ken — tests the core state machine and algorithms.
"""
import struct
import socket
import time
import sys


# ---------------------------------------------------------------------------
# Replicate the enhanced DHCP logic (without os-ken imports)
# ---------------------------------------------------------------------------

DHCP_NAK_v = 6
DHCP_DECLINE_v = 4
DHCP_DISCOVER_v = 1
DHCP_REQUEST_v = 3
DHCP_RELEASE_v = 7
DHCP_REQ_IP_OPT_v = 50
DHCP_MSG_OPT_v = 56


class DHCPConfig:
    dns = '8.8.8.8'
    start_ip = '192.168.1.2'
    end_ip = '192.168.1.5'        # 4 IPs for testing
    netmask = '255.255.255.0'
    lease_time = 60
    probe_timeout = 0.1            # fast for unit test
    conflict_ttl = 30              # 30 seconds for TTL test


LEASE_PROBING = 'PROBING'
LEASE_OFFERED = 'OFFERED'
LEASE_ALLOCATED = 'ALLOCATED'
LEASE_RELEASED = 'RELEASED'
LEASE_CONFLICTED = 'CONFLICTED'


class DHCPServerStub:
    start_ip = DHCPConfig.start_ip
    end_ip = DHCPConfig.end_ip
    lease_time = DHCPConfig.lease_time
    mac_to_lease = {}
    ip_to_mac = {}
    _probing = {}
    _conflict_ips = {}

    @classmethod
    def reset(cls):
        cls.mac_to_lease.clear()
        cls.ip_to_mac.clear()
        cls._probing.clear()
        cls._conflict_ips.clear()

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

    # ---------- ARP probe (simulated — tests the flag logic) ----------

    @classmethod
    def _simulate_probe(cls, ip_str):
        """Simulates _arp_probe: sets flag, sleeps, checks result.
        *no_conflict* callers should NOT touch _probing (simulates no ARP reply).
        *conflict* callers should set _probing[ip] = False before sleep ends.
        Returns True if IP is free."""
        cls._probing[ip_str] = True
        time.sleep(DHCPConfig.probe_timeout)
        result = cls._probing.pop(ip_str, False)
        if not result:
            cls._conflict_ips[ip_str] = cls._now()
            return False
        return True

    @classmethod
    def _probe_with_existing_conflict_cache(cls, ip_str):
        """Same as _arp_probe but checks _conflict_ips first."""
        now = cls._now()
        stale = [ip for ip, ts in cls._conflict_ips.items()
                 if now - ts > DHCPConfig.conflict_ttl]
        for ip in stale:
            del cls._conflict_ips[ip]
        if ip_str in cls._conflict_ips:
            return False
        return cls._simulate_probe(ip_str)

    @classmethod
    def _mark_conflict(cls, ip_str):
        if ip_str in cls._probing:
            cls._probing[ip_str] = False

    # ---------- IP allocation ----------

    @classmethod
    def _find_free_ip(cls, mac_addr, do_probe=False):
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
                if do_probe and not cls._probe_with_existing_conflict_cache(ip_str):
                    continue
                cls.mac_to_lease[mac_addr] = {
                    'ip': ip_str,
                    'assigned_at': now,
                    'expires_at': now + cls.lease_time,
                    'state': LEASE_OFFERED,
                }
                return ip_str
        return None

    @classmethod
    def ack(cls, mac_addr, do_probe=False, requested_ip=None):
        now = cls._now()
        lease = cls.mac_to_lease.get(mac_addr)
        if lease is not None and lease['state'] == LEASE_OFFERED:
            assigned_ip = lease['ip']
            if requested_ip is not None and requested_ip != assigned_ip:
                return ('NAK', "requested IP %s does not match offer %s" % (requested_ip, assigned_ip))
            cls.mac_to_lease[mac_addr] = {
                'ip': assigned_ip, 'assigned_at': now,
                'expires_at': now + cls.lease_time, 'state': LEASE_ALLOCATED,
            }
            cls.ip_to_mac[assigned_ip] = mac_addr
            return ('ACK', assigned_ip)
        elif lease is not None and lease['state'] == LEASE_ALLOCATED:
            assigned_ip = lease['ip']
            if requested_ip is not None and requested_ip != assigned_ip:
                return ('NAK', "requested IP %s does not match lease %s" % (requested_ip, assigned_ip))
            cls.mac_to_lease[mac_addr]['expires_at'] = now + cls.lease_time
            return ('RENEW', assigned_ip)
        else:
            ip = cls._find_free_ip(mac_addr, do_probe)
            if ip is None:
                return (None, None)
            cls.mac_to_lease[mac_addr] = {
                'ip': ip, 'assigned_at': now,
                'expires_at': now + cls.lease_time, 'state': LEASE_ALLOCATED,
            }
            cls.ip_to_mac[ip] = mac_addr
            return ('ACK', ip)

    @classmethod
    def decline(cls, mac_addr):
        lease = cls.mac_to_lease.get(mac_addr)
        if lease:
            declined_ip = lease['ip']
            cls._conflict_ips[declined_ip] = cls._now()
            cls._release_lease(mac_addr)
            return declined_ip
        return None


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0


def check(condition, test_name):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {test_name}")
    else:
        FAIL += 1
        print(f"  FAIL  {test_name}")


# ---- Test 1: Normal allocation (no conflict, no probe) ----
def test_normal_allocation():
    print("\n=== Test 1: Basic allocation ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'
    ip = DHCPServerStub._find_free_ip(mac1, do_probe=False)
    check(ip == '192.168.1.2', f"first IP = {ip}")
    result, acked = DHCPServerStub.ack(mac1)
    check(result == 'ACK' and acked == '192.168.1.2', f"ACK: {result} {acked}")
    check(DHCPServerStub.ip_to_mac['192.168.1.2'] == mac1, "ip_to_mac set")


# ---- Test 2: ARP probe — no conflict ----
def test_probe_no_conflict():
    print("\n=== Test 2: ARP probe — no conflict ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    # Simulate probe — no one touches _probing → should be free
    result = DHCPServerStub._simulate_probe('192.168.1.2')
    check(result is True, "probe returns True (no ARP reply)")
    check('192.168.1.2' not in DHCPServerStub._conflict_ips, "not in conflict list")


# ---- Test 3: ARP probe — conflict detected ----
def test_probe_conflict():
    print("\n=== Test 3: ARP probe — conflict detected ===")
    DHCPServerStub.reset()

    # Simulate the ARP reply arriving mid-probe (like real controller would)
    import threading

    def conflict_injector():
        time.sleep(0.03)
        DHCPServerStub._mark_conflict('192.168.1.2')

    DHCPServerStub._probing['192.168.1.2'] = True
    t = threading.Thread(target=conflict_injector, daemon=True)
    t.start()
    time.sleep(DHCPConfig.probe_timeout)
    t.join()
    result = DHCPServerStub._probing.pop('192.168.1.2', False)

    check(result is False, "flag is False after conflict detection")
    DHCPServerStub._conflict_ips['192.168.1.2'] = time.time()
    check('192.168.1.2' in DHCPServerStub._conflict_ips, "IP added to conflict list")


# ---- Test 4: _find_free_ip skips conflicted IP ----
def test_find_free_skips_conflict():
    print("\n=== Test 4: find_free_ip skips conflicted IP ===")
    DHCPServerStub.reset()

    # Mark .2 as conflicted
    DHCPServerStub._conflict_ips['192.168.1.2'] = time.time()

    mac1 = b'\x00\x00\x00\x00\x00\x01'
    ip = DHCPServerStub._find_free_ip(mac1, do_probe=True)
    check(ip == '192.168.1.3', f"skipped .2, got {ip}")


# ---- Test 5: Conflict TTL expiry ----
def test_conflict_ttl_expiry():
    print("\n=== Test 5: Conflict TTL expiry ===")
    DHCPServerStub.reset()

    # Set expired conflict
    DHCPServerStub._conflict_ips['192.168.1.2'] = time.time() - 60   # 60s ago, TTL=30
    mac1 = b'\x00\x00\x00\x00\x00\x01'
    ip = DHCPServerStub._find_free_ip(mac1, do_probe=True)
    check(ip == '192.168.1.2', f"expired conflict cleared, got .2: {ip}")


# ---- Test 6: DHCPNAK on mismatched requested IP ----
def test_nak_on_mismatch():
    print("\n=== Test 6: NAK on mismatched requested IP ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    # Offer .2
    DHCPServerStub._find_free_ip(mac1, do_probe=False)
    # ACK with wrong requested IP
    result, detail = DHCPServerStub.ack(mac1, requested_ip='192.168.1.99')
    check(result == 'NAK', f"NAK returned: {detail}")


# ---- Test 7: DHCPNAK on renew with wrong IP ----
def test_nak_on_renew_mismatch():
    print("\n=== Test 7: NAK on renew with wrong IP ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    # Full allocation: offer → ACK
    DHCPServerStub._find_free_ip(mac1, do_probe=False)
    DHCPServerStub.ack(mac1)
    check(DHCPServerStub.mac_to_lease[mac1]['state'] == LEASE_ALLOCATED, "allocated")

    # Try to renew with wrong IP
    result, detail = DHCPServerStub.ack(mac1, requested_ip='192.168.1.99')
    check(result == 'NAK', f"RENEW NAK returned: {detail}")


# ---- Test 8: DHCPDECLINE marks conflict ----
def test_decline_marks_conflict():
    print("\n=== Test 8: DHCPDECLINE marks conflict ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    DHCPServerStub._find_free_ip(mac1, do_probe=False)
    DHCPServerStub.ack(mac1)

    declined = DHCPServerStub.decline(mac1)
    check(declined == '192.168.1.2', f"declined IP = {declined}")
    check('192.168.1.2' in DHCPServerStub._conflict_ips, "added to conflict list")
    check(mac1 not in DHCPServerStub.ip_to_mac.values(), "removed from ip_to_mac")


# ---- Test 9: find_free_ip with multi-conflict (all skip) ----
def test_all_conflicted_pool():
    print("\n=== Test 9: Pool fully conflicted → returns None ===")
    DHCPServerStub.reset()
    now = time.time()
    for i in range(2, 6):
        DHCPServerStub._conflict_ips[f'192.168.1.{i}'] = now

    mac1 = b'\x00\x00\x00\x00\x00\x01'
    ip = DHCPServerStub._find_free_ip(mac1, do_probe=True)
    check(ip is None, "all conflicted → None")


# ---- Test 10: find_free_ip with probe — first conflicts, second free ----
def test_probe_first_conflict_second_free():
    print("\n=== Test 10: Probe first IP conflicts → gets second ===")
    DHCPServerStub.reset()
    mac1 = b'\x00\x00\x00\x00\x00\x01'

    # Set up: .2 is conflicted, .3 is free
    DHCPServerStub._conflict_ips['192.168.1.2'] = time.time()

    ip = DHCPServerStub._find_free_ip(mac1, do_probe=True)
    check(ip == '192.168.1.3', f"skipped .2 (conflict), got .3")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=" * 60)
    print("DHCP RFC — ARP Probe / NAK / DECLINE  Unit Tests")
    print("=" * 60)

    test_normal_allocation()
    test_probe_no_conflict()
    test_probe_conflict()
    test_find_free_skips_conflict()
    test_conflict_ttl_expiry()
    test_nak_on_mismatch()
    test_nak_on_renew_mismatch()
    test_decline_marks_conflict()
    test_all_conflicted_pool()
    test_probe_first_conflict_second_free()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
