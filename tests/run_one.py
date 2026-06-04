#!/usr/bin/env python3
"""Orchestrate controller + one Mininet integration test."""
import subprocess, time, sys, os, signal

PROJ = "/mnt/d/Sustech/ComputerNetwork/CS305-2026Spring-Project"
CTL_LOG = os.path.join(PROJ, "tests/ctl_output.log")
os.chdir(PROJ)

def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, shell=True)

if len(sys.argv) < 2:
    print("Usage: python run_one.py <test_script>")
    sys.exit(1)

test_script = sys.argv[1]
test_name = os.path.basename(test_script)

# Kill stale
for cmd in ["pkill -9 -f osken-manager 2>/dev/null; true",
            "echo Sirius810975 | sudo -S mn -c 2>/dev/null || true",
            "echo Sirius810975 | sudo -S bash -c 'grep -q \"127.0.0.1.*h[0-9]\" /etc/hosts || echo 127.0.0.1 h1 h2 h3 h4 h5 h6 h7 h8 >> /etc/hosts' 2>/dev/null || true"]:
    try: run(cmd, timeout=5)
    except: pass
time.sleep(1)

# Start controller
ctl = subprocess.Popen(
    "osken-manager --observe-links controller.py",
    stdout=open(CTL_LOG, "w"), stderr=subprocess.STDOUT,
    shell=True, preexec_fn=os.setpgrp
)
time.sleep(4)

# Quick health check
with open(CTL_LOG) as f:
    for line in f:
        if "ERROR" in line:
            print("CTL ERROR:", line.strip())

print(f"[{test_name}] Controller PID={ctl.pid}, running test...")

# Run test
env = os.environ.copy()
env["PATH"] = "/home/zzshi/software/miniconda3/envs/cs305/bin:" + env.get("PATH","")
env["PYTHONPATH"] = "/home/zzshi/software/miniconda3/envs/cs305/lib/python3.8/site-packages"
cmd = f"echo Sirius810975 | sudo -S /home/zzshi/software/miniconda3/envs/cs305/bin/python {test_script}"
try:
    result = run(cmd, timeout=120)
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        lines = result.stderr.strip().split('\n')
        for l in lines:
            if not l.startswith("[sudo]") and "password" not in l:
                print("STDERR:", l[:200])
except subprocess.TimeoutExpired:
    print("TEST TIMEOUT")

# Controller logs
print(f"\n--- Controller {test_name} logs ---")
kw_list = ["DHCP", "ARP-Host", "HostAdd", "Topology", "DNS", "Routing", "Flow"]
with open(CTL_LOG) as f:
    for line in f:
        if any(kw in line for kw in kw_list):
            print(line.strip())

# Cleanup
try: os.killpg(os.getpgid(ctl.pid), signal.SIGTERM)
except: pass
try: ctl.wait(timeout=5)
except: pass
try: run("echo Sirius810975 | sudo -S mn -c 2>/dev/null || true", timeout=5)
except: pass
print("Done")
