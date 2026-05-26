# AGENTS.md

## Overview
SDN controller using os-ken + Mininet. Implements DHCP server, shortest-path switching (Dijkstra), and a firewall on OpenFlow 1.0.

## Environment
- **Python 3.8** only — conda env `cs305`
- All commands must run inside the Mininet VM (Linux, root required for Mininet)
- Dependencies: `os-ken<4`, `mininet==2.3.0.dev6`, `eventlet==0.29.1`

## Project structure
| File | Role |
|---|---|
| `controller.py` | Main entrypoint — topology tracking, ARP handling, flow installation |
| `dhcp.py` | DHCP server (DISCOVER/OFFER/REQUEST/ACK), lease mgmt, ARP probe |
| `firewall.py` | Loads rules from `firewall_rules.json`, generates deny flow entries |
| `ofctl_utilis.py` | **Do NOT modify.** OpenFlow 1.0/1.2/1.3 flow helpers |
| `tests/` | Mininet test networks (integration tests requiring a running controller) |

## How to run

### Start the controller (terminal 1)
```
osken-manager --observe-links controller.py
```
The `--observe-links` flag is **required** — without it the controller won't detect links via LLDP and the probe fallback won't suffice.

### Run a test (terminal 2)
The tests are **integration tests** that launch a Mininet network connecting to the already-running controller. All require `sudo`:

```bash
# DHCP test
cd tests/dhcp_test && sudo env "PATH=$PATH" python test_network.py

# Switching test (enters Mininet CLI — run `pingall`)
cd tests/switching_test && sudo env "PATH=$PATH" python test_network.py

# Firewall test
cd tests/firewall_test && sudo env "PATH=$PATH" python test_network.py

# Bonus: Lease duration (non-interactive)
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease.py

# Bonus: ARP probe conflict detection (non-interactive)
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease_rfc.py
```

The `env "PATH=$PATH"` is necessary to pass the conda/venv PATH to the sudo subshell.

### Unit tests (no controller needed)
```bash
python tests/dhcp_test/test_lease_unit.py
python tests/dhcp_test/test_lease_rfc_unit.py
```

### Cleanup after Mininet
```
sudo mn -c
```

## Architecture notes

### OpenFlow version
The controller uses **OpenFlow 1.0** exclusively (`OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]` in `controller.py:29`). All flow matches must use the OFPMatch constructor with 13 positional args.

### Topology discovery
Two mechanisms work in parallel:
1. **os-ken's LLDP** (from `--observe-links`) — discovers switch links via `EventLinkAdd`/`EventLinkDelete`
2. **Custom probe** (ethertype `0x9999`) — fallback link discovery service installed only when LLDP support is missing. These are handled in `packet_in_handler` with a special code path at `controller.py:318-340`.

The link ports reported by LLDP (`EventLinkAdd`) are `0`; the custom probe populates the actual port numbers via `_parse_probe`.

### Host discovery
Hosts announce themselves via **gratuitous ARP** (`arping`). The controller records them in `handle_host_add` (from os-ken events) and in `packet_in_handler` for ARP replies (`controller.py:372-386`).

### DHCP
- `controller.py` spawns `DHCPServer._lease_reaper` as a greenlet (`hub.spawn`) at startup
- DHCP UDP packets are matched in `packet_in_handler` and delegated to `DHCPServer.handle_dhcp`
- The DHCP server uses an ARP probe mechanism (`_arp_probe`) before offering an IP — sends an ARP request and waits `probe_timeout` seconds for a reply
- `controller.py` calls `DHCPServer._mark_arp_conflict()` when it receives an ARP_REPLY for a probed IP

### Firewall
- Rules are loaded at startup from `firewall_rules.json` (defaults to empty list if file missing)
- Two copies of the rule file exist: `firewall_rules.json` and `firewall_rule.json` — they contain the same rules. `firewall.py` defaults to loading `firewall_rules.json` but accepts a configurable path.
- Rules are installed on each switch when it connects (`switch_features_handler` at `controller.py:230-234`)
- Firewall rule cookies use `0x305F` with priority `60000` (higher than forwarding rules at priority `10`)

### Flow installation
Forwarding flows use `OfCtl.set_flow()` from `ofctl_utilis.py` (priority `10`, cookie `0x10`). Firewall rules are installed directly via low-level OFPFlowMod messages with priority `60000`. The table-miss entry (priority `0`) sends all unmatched packets to the controller.

### Shortest path
- `_dijkstra()` runs Dijkstra on the switch adjacency graph (edges weighted by hop count)
- `_install_host_flows()` is called after every topology change — it installs destination-MAC-based flows on every switch for every known host
- Paths are MAC-based, not IP-based (host-to-host directly, no routing)

## Common pitfalls
- **Forgetting `--observe-links`**: The controller will miss LLDP-based link events and topology will be incomplete
- **Forgetting `sudo mn -c`** between runs: stale Mininet state causes port conflicts
- **OpenFlow 1.0 match field ordering**: The `OFPMatch` constructor takes 13 positional args in a specific order — don't use keyword args
- **`env "PATH=$PATH"` with sudo**: Without it, the test script may fail to find `dhclient` or Mininet
- **ARP probe and os-ken greenlet model**: `hub.sleep()` must be used (not `time.sleep()`) for the probe timeout in `dhcp.py` to avoid blocking the entire controller event loop
