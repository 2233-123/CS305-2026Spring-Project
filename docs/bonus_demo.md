# Bonus 功能演示文档

## Bonus 1: DHCP 租约期限 (Lease Duration)

### 1.1 功能概述

实现完整的 DHCP 租约生命周期管理，包括：
- 每次分配 IP 时记录 `expires_at` 过期时间戳
- 后台绿程定时扫描并回收过期租约
- 支持 DHCPRELEASE 主动释放
- 支持 DHCPREQUEST 续约 (RENEW)
- IP 地址池回收后再分配

### 1.2 配置参数

```python
# dhcp.py:26-35
class DHCPConfig:
    lease_time = 60          # 租约时长 (秒)，测试用60s，生产环境86400s
    reaper_interval = 30     # 回收器扫描间隔 (秒)
```

### 1.3 状态机

租约经历以下状态流转 (`dhcp.py:41-45`)：

```
DISCOVER → PROBING → OFFERED → ALLOCATED → RELEASED
                          ↘ CONFLICTED
```

| 状态 | 含义 |
|------|------|
| `PROBING` | ARP 探测中 |
| `OFFERED` | 已发送 OFFER，等待 REQUEST |
| `ALLOCATED` | 已分配，可使用 |
| `RELEASED` | 主机发送 RELEASE 或过期自动回收 |
| `CONFLICTED` | IP 冲突 |

### 1.4 关键实现

#### (a) IP 分配时记录过期时间

```python
# dhcp.py:189-194 (OFFER 阶段)
cls.mac_to_lease[mac_addr] = {
    'ip': ip_str,
    'assigned_at': now,
    'expires_at': now + cls.lease_time,    # <-- 过期时间
    'state': LEASE_OFFERED,
}
```

```python
# dhcp.py:333-338 (ACK 阶段)
cls.mac_to_lease[mac_bytes] = {
    'ip': assigned_ip,
    'assigned_at': now,
    'expires_at': now + cls.lease_time,
    'state': LEASE_ALLOCATED,
}
```

#### (b) DHCPOFFER / DHCPACK 中携带 `option 51` (IP Address Lease Time)

```python
# dhcp.py:237-238 (OFFER)
dhcp.option(tag=dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT,
            value=struct.pack('!I', cls.lease_time)),

# dhcp.py:373-374 (ACK)
dhcp.option(tag=dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT,
            value=struct.pack('!I', cls.lease_time)),
```

#### (c) 后台租约回收器 (`_lease_reaper`)

```python
# dhcp.py:467-476
@classmethod
def _lease_reaper(cls):
    while True:
        hub.sleep(DHCPConfig.reaper_interval)          # 每30秒执行一次
        now = cls._now()
        expired = []
        for mac, info in cls.mac_to_lease.items():
            if info['state'] == LEASE_ALLOCATED and now >= info['expires_at']:
                expired.append(mac)
        for mac in expired:
            cls._release_lease(mac)                    # 回收过期租约
```

- 使用 `hub.sleep()` (os-ken 绿程) 而非 `time.sleep()`，避免阻塞整个控制器事件循环
- 在 `controller.py:43` 通过 `hub.spawn(DHCPServer._lease_reaper)` 启动
- 只回收状态为 ALLOCATED 且已过期的租约

#### (d) DHCPRELEASE 主动释放

```python
# dhcp.py:444-448
elif msg_type == bytes([dhcp.DHCP_RELEASE]):
    eth = pkt.get_protocol(ethernet.ethernet)
    mac_bytes = addrconv.mac.text_to_bin(eth.src)
    if mac_bytes:
        cls._release_lease(mac_bytes)
```

释放后清理 IP→MAC 映射，IP 可供后续主机使用。

#### (e) 续约 (RENEW)

```python
# dhcp.py:342-349
elif lease is not None and lease['state'] == LEASE_ALLOCATED:
    assigned_ip = lease['ip']
    if requested_ip is not None and requested_ip != assigned_ip:
        return cls.assemble_nak(pkt, datapath, port, ...)  # IP不匹配→NAK
    cls.mac_to_lease[mac_bytes]['expires_at'] = now + cls.lease_time  # 刷新过期时间
```

主机在租约到期前重新发送 DHCPREQUEST，控制器识别已存在的 ALLOCATED 租约，仅刷新 `expires_at`，不重新分配。

---

## Bonus 2: RFC 2131 ARP Probe 防 IP 重复分配

### 2.1 功能概述

严格遵循 RFC 2131 §2.2 规范，在分配 IP 前使用 ARP Probe 检测冲突：
- 发送 ARP 请求探测目标 IP 是否已被占用
- 等待 `probe_timeout` 秒，若收到 ARP_REPLY 则标记冲突
- 冲突 IP 加入缓存表，在 `conflict_ttl` 秒内不再尝试分配
- 支持 DHCPDECLINE (主机主动拒绝 IP)
- 支持 DHCPNAK (请求 IP 与分配 IP 不匹配时)

### 2.2 配置参数

```python
# dhcp.py:34-35
class DHCPConfig:
    probe_timeout = 2         # ARP 探测等待时间 (秒)
    conflict_ttl = 300        # 冲突 IP 缓存时间 (秒)
```

### 2.3 关键实现

#### (a) ARP Probe 发送

```python
# dhcp.py:93-125
@classmethod
def _send_arp_probe(cls, datapath, target_ip):
    """广播 ARP Request 检测 target_ip 是否已被占用"""
    e = ethernet.ethernet(dst='ff:ff:ff:ff:ff:ff', src=src_mac,
                          ethertype=ethernet.ether.ETH_TYPE_ARP)
    a = arp.arp(opcode=arp.ARP_REQUEST,
                src_mac=src_mac, src_ip=cls.server_ip,
                dst_mac='00:00:00:00:00:00', dst_ip=target_ip)
    # 通过 OFPP_ALL 广播到所有端口
    actions = [parser.OFPActionOutput(port=ofproto.OFPP_ALL)]
    datapath.send_msg(out)
```

#### (b) ARP Probe 等待与判断

```python
# dhcp.py:127-157
@classmethod
def _arp_probe(cls, ip_str, datapath):
    """发送 ARP 探测并等待 PROBE_TIMEOUT 秒。
    返回 True 表示 IP 空闲，False 表示冲突。"""

    # 1. 清理过期的冲突缓存 (conflict_ttl 已过期)
    stale = [ip for ip, ts in cls._conflict_ips.items()
             if now - ts > DHCPConfig.conflict_ttl]
    for ip in stale:
        del cls._conflict_ips[ip]

    # 2. 如果 IP 仍在冲突列表中，直接返回 False
    if ip_str in cls._conflict_ips:
        return False

    # 3. 发送 ARP 探测
    cls._send_arp_probe(datapath, ip_str)
    cls._probing[ip_str] = True          # 设置探测标志

    # 4. 使用 hub.sleep() 等待 (不阻塞控制器)
    hub.sleep(DHCPConfig.probe_timeout)

    # 5. 检查探测标志：True=无冲突，False=有冲突
    result = cls._probing.pop(ip_str, False)
    if not result:
        cls._conflict_ips[ip_str] = now  # 加入冲突缓存
        return False
    return True
```

- 使用 `hub.sleep()` 而非 `time.sleep()`，保证控制器事件循环不会阻塞
- 探测期间，若收到 ARP_REPLY(对目标 IP)，`_mark_arp_conflict()` 会将标志置为 `False`

#### (c) 冲突标记 (跨模块协作)

```python
# dhcp.py:159-164
@classmethod
def _mark_arp_conflict(cls, ip_str):
    """由 controller.py 在收到 ARP_REPLY 时调用"""
    if ip_str in cls._probing:
        cls._probing[ip_str] = False     # 标记冲突

# controller.py:372-373 (调用点)
elif pkt_arp.opcode == arp.ARP_REPLY:
    DHCPServer._mark_arp_conflict(pkt_arp.src_ip)
```

`controller.py` 在处理所有 `packet_in` 的 ARP_REPLY 时，会调用 `_mark_arp_conflict()`。如果该 IP 正处于探测中 (`_probing[ip_str]` 存在)，则将其标志设为 `False`，表明 IP 已被占用。

#### (d) DHCPDECLINE 处理

```python
# dhcp.py:451-461
elif msg_type == bytes([_DHCP_DECLINE]):
    eth = pkt.get_protocol(ethernet.ethernet)
    mac_bytes = addrconv.mac.text_to_bin(eth.src)
    if mac_bytes:
        lease = cls.mac_to_lease.get(mac_bytes)
        if lease:
            declined_ip = lease['ip']
            cls._conflict_ips[declined_ip] = cls._now()  # 加入冲突缓存
            cls._release_lease(mac_bytes)                 # 释放租约
```

主机发送 DHCPDECLINE 表示它检测到 IP 已被占用(通过自己的 ARP 检查)。控制器将该 IP 加入冲突缓存并释放租约。

#### (e) DHCPNAK 处理 (IP 不匹配)

```python
# dhcp.py:326-332 (OFFERED → ACK 时校验)
if lease is not None and lease['state'] == LEASE_OFFERED:
    assigned_ip = lease['ip']
    if requested_ip is not None and requested_ip != assigned_ip:
        return cls.assemble_nak(pkt, datapath, port,
            "requested IP %s does not match offer %s" %
            (requested_ip, assigned_ip))

# dhcp.py:342-347 (ALLOCATED → RENEW 时校验)
elif lease is not None and lease['state'] == LEASE_ALLOCATED:
    assigned_ip = lease['ip']
    if requested_ip is not None and requested_ip != assigned_ip:
        return cls.assemble_nak(pkt, datapath, port,
            "requested IP %s does not match lease %s" %
            (requested_ip, assigned_ip))
```

主机 DHCPREQUEST 中的 requested IP (Option 50) 与已分配 IP 不匹配时，返回 DHCPNAK。

### 2.4 完整分配流程 (含 ARP Probe)

```
主机发送 DHCPDISCOVER
    │
    ▼
controller.py packet_in_handler → 识别 DHCP 包
    │
    ▼
dhcp.py handle_dhcp() → 发现 DHCPDISCOVER
    │
    ▼
assemble_offer() → _find_free_ip()
    │
    ├── 遍历 IP 池 (192.168.1.2 ~ 192.168.1.100)
    │     │
    │     ├── 检查冲突缓存 (_conflict_ips) → 在缓存中? → 跳过
    │     │
    │     ├── 发送 ARP Probe (_send_arp_probe)
    │     │     │
    │     │     ├── 广播 ARP REQUEST (who-has target_ip?)
    │     │     │
    │     │     ├── controller.py 收到 ARP_REPLY?
    │     │     │     ├── 是 → _mark_arp_conflict() → _probing[ip]=False
    │     │     │     └── 否 → hub.sleep(2s) → _probing[ip] 仍为 True
    │     │     │
    │     │     └── 探测结果:
    │     │           ├── True=IP空闲 → 分配 Lease → 发送 DHCPOFFER
    │     │           └── False=冲突  → 加入 _conflict_ips → 尝试下一个IP
    │     │
    │     └── 全部冲突? → 返回 None (无可用IP)
    │
    ▼
主机收到 DHCPOFFER → 发送 DHCPREQUEST (携带 Option 50)
    │
    ▼
assemble_ack() → 校验 requested_ip
    │
    ├── OFFERED 状态 + IP匹配 → ALLOCATED → 发送 DHCPACK
    ├── ALLOCATED 状态 + IP匹配 → RENEW (刷新expires_at) → 发送 DHCPACK
    ├── IP不匹配 → 发送 DHCPNAK
    └── 无租约 → 新分配 → ALLOCATED → 发送 DHCPACK
```

---

## 单元测试验证

所有测试文件位于 `tests/dhcp_test/`。

### 运行方法

```bash
# Bonus 1: 租约期限单元测试 (无需 controller)
python tests/dhcp_test/test_lease_unit.py

# Bonus 2: ARP Probe / NAK / DECLINE 单元测试 (无需 controller)
python tests/dhcp_test/test_lease_rfc_unit.py

# Bonus 1: 租约期限集成测试 (需要 controller 运行)
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease.py

# Bonus 2: ARP Probe 冲突检测集成测试 (需要 controller 运行)
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease_rfc.py
```

### Bonus 1 单元测试结果 (7 个测试, 15 条断言, 全部通过)

| 测试 | 验证内容 | 结果 |
|------|----------|------|
| Test 1 | 基础分配 (OFFER → ACK, 状态正确) | ✅ PASS |
| Test 2 | 两台主机获得不同 IP | ✅ PASS |
| Test 3 | IP 池耗尽 (仅2个IP时第3台主机返回None) | ✅ PASS |
| Test 4 | DHCPRELEASE (释放后IP可重新分配) | ✅ PASS |
| Test 5 | 租约过期自动回收 (等待 lease_time+1s 后 IP 被回收) | ✅ PASS |
| Test 6 | 续约 (RENEW 刷新 expires_at) | ✅ PASS |
| Test 7 | 重复请求相同 MAC 返回相同 IP | ✅ PASS |

### Bonus 2 单元测试结果 (10 个测试, 17 条断言, 全部通过)

| 测试 | 验证内容 | 结果 |
|------|----------|------|
| Test 1 | 基础分配正常 | ✅ PASS |
| Test 2 | ARP Probe 无冲突 → 返回 True | ✅ PASS |
| Test 3 | ARP Probe 冲突检测 (标志变为 False) | ✅ PASS |
| Test 4 | `_find_free_ip` 跳过冲突 IP | ✅ PASS |
| Test 5 | 冲突 TTL 过期后 IP 重新可用 | ✅ PASS |
| Test 6 | NAK: 请求IP与 OFFER 不匹配 | ✅ PASS |
| Test 7 | NAK: 续约时请求IP与租约不匹配 | ✅ PASS |
| Test 8 | DHCPDECLINE 标记冲突 | ✅ PASS |
| Test 9 | 池全部冲突 → 返回 None | ✅ PASS |
| Test 10 | 首个IP冲突 → 自动跳过到第二个IP | ✅ PASS |

---

## 代码文件索引

| 功能 | 文件 | 关键行号 |
|------|------|----------|
| DHCP 配置 | `dhcp.py` | 26-35 |
| 租约状态机 | `dhcp.py` | 41-45 |
| IP 分配 (_find_free_ip) | `dhcp.py` | 170-196 |
| DHCPOFFER 构建 | `dhcp.py` | 216-269 |
| DHCPACK / RENEW / NAK | `dhcp.py` | 318-405 |
| DHCPNAK 构建 | `dhcp.py` | 271-315 |
| DHCPRELEASE 处理 | `dhcp.py` | 80-88, 444-448 |
| DHCPDECLINE 处理 | `dhcp.py` | 451-461 |
| 租约回收器 | `dhcp.py` | 467-476 |
| ARP Probe 发送 | `dhcp.py` | 93-125 |
| ARP Probe 等待 | `dhcp.py` | 127-157 |
| 冲突标记 (cross-module) | `dhcp.py:159-164` / `controller.py:372-373` |
| 回收器启动 | `controller.py` | 43 |
