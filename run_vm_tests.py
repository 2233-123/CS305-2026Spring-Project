"""Run tests in Mininet VM via SSH."""
import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.56.101", username="mininet", password="mininet", timeout=10)

PREFIX = "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8 && export PATH=$HOME/.local/bin:$PATH"

tests = [
    ("Unit: Lease", "cd ~/CS305-2026Spring-Project && python3 tests/dhcp_test/test_lease_unit.py 2>&1", 30),
    ("Unit: ARP Probe", "cd ~/CS305-2026Spring-Project && python3 tests/dhcp_test/test_lease_rfc_unit.py 2>&1", 30),
]

for name, cmd, timeout in tests:
    print(f"\n{'='*60}")
    print(f"RUNNING: {name}")
    print(f"{'='*60}")
    stdin, stdout, stderr = c.exec_command(PREFIX + " && " + cmd, timeout=timeout)
    out = stdout.read()
    err = stderr.read()
    # Try UTF-8 first, then fallback
    try:
        text = out.decode("utf-8")
    except:
        text = out.decode("latin-1")
    print(text)
    if err:
        try:
            print("STDERR:", err.decode("utf-8"))
        except:
            print("STDERR:", err.decode("latin-1"))

c.close()
