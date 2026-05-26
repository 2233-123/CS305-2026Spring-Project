# DHCP Bonus — 人工测试流程

---

## 前置准备

### 1. 确认测试配置

编辑 `dhcp.py` 第 21-22 行：

```python
lease_time = 60          # 60秒过期，便于观察
reaper_interval = 30     # 30秒扫描一次
end_ip = '192.168.1.3'   # ★ 临时改为 .3，只有 2 个可用 IP（用于测耗尽）
```

> 测试完毕后恢复 `end_ip = '192.168.1.100'`

### 2. 清理残留状态

```bash
sudo mn -c
```

### 3. 启动控制器

```bash
# 终端 1
conda activate cs305
osken-manager --observe-links controller.py
```

看到 `loading app controller.py` 和 `instantiating app ... of ControllerApp` 即为启动成功。

### 4. 启动测试拓扑（交互模式）

```bash
# 终端 2
conda activate cs305
sudo env "PATH=$PATH" python tests/dhcp_test/test_network.py
```

> 注：用 test_network.py（原本 2 台主机）或自己写一个 3 台主机的 Mininet 脚本均可。

进入 `mininet>` 提示符后开始以下测试。

---

## 一、租约时长 (Lease Duration) — 4 项测试

---

### Test L1: 基本分配 + Option 51 验证

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | `h1 arping -c 1 -A -I h1-eth0 0.0.0.0` | 触发控制器学习 h1 | — |
| 2 | `h1 dhclient -v h1-eth0` | h1 获得 IP | □ |
| 3 | `h1 ifconfig` | 显示 `inet 192.168.1.2` | □ 通过 / □ 失败 |
| 4 | 回终端1看日志 | 出现 `[DHCP] OFFER IP 192.168.1.2`<br>`[DHCP] ACK IP 192.168.1.2 (state ALLOCATED, expires in 60s)` | □ 通过 / □ 失败 |

**Packet trace 验证（终端 3）：**

```bash
sudo tcpdump -i any port 67 or port 68 -vvv 2>&1 | grep -i "lease.time\|option 51"
```

应看到 `option 51 (lease-time), length 4: 60`

| 5 | tcpdump 输出 | 包含 `option 51` 且值为 `60` | □ 通过 / □ 失败 |

---

### Test L2: 租约过期自动回收

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 确认 h1 已拿到 `192.168.1.2`，h2 已拿到 `192.168.1.3` | — | □ |
| 2 | `pingall` | h1 ↔ h2 通 | □ |
| 3 | **等待 65 秒**（lease_time=60 + 缓冲5s） | — | — |
| 4 | 回终端1看日志 | 出现 `[DHCP] RELEASED IP 192.168.1.2 from MAC xx:xx:xx:xx:xx:x1`<br>出现 `[DHCP] RELEASED IP 192.168.1.3 from MAC xx:xx:xx:xx:xx:x2` | □ 通过 / □ 失败 |
| 5 | `h1 dhclient -v h1-eth0` | h1 重新获得 IP（`.2` 或 `.3`） | □ |
| 6 | `h1 ifconfig` | IP 已分配 | □ 通过 / □ 失败 |

---

### Test L3: DHCPRELEASE 主动释放

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 确保 h1 有 IP | — | □ |
| 2 | `h1 dhclient -r h1-eth0` | 释放租约 | — |
| 3 | 回终端1看日志 | 出现 `[DHCP] RELEASED IP 192.168.1.X from MAC xx:xx:xx:xx:xx:x1` | □ 通过 / □ 失败 |
| 4 | `h1 ifconfig` | 不再有 `inet 192.168.1.x` | □ 通过 / □ 失败 |
| 5 | `h1 dhclient -v h1-eth0` | h1 重新获得 IP | □ 通过 / □ 失败 |

---

### Test L4: IP 池耗尽

> 前置：`end_ip = '192.168.1.3'`（仅 2 个 IP）

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 确保 h1, h2 各占一个 IP (.2 和 .3) | — | □ |
| 2 | **h3 没有** IP（只 2 个可用） | — | □ |
| 3 | `h3 dhclient -v h3-eth0` | 超时或报错 | — |
| 4 | 回终端1看日志 | 出现 `[DHCP] No free IP for MAC xx:xx:xx:xx:xx:x3` | □ 通过 / □ 失败 |
| 5 | 等待 65s（两个租约过期） | — | — |
| 6 | `h3 dhclient -v h3-eth0` | h3 获得 IP（回收后的） | □ 通过 / □ 失败 |

---

## 二、ARP Probe 防重复分配 — 5 项测试

---

### Test A1: ARP Probe 检测静态 IP 冲突

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 重启 controller + Mininet（确保干净） | — | — |
| 2 | `h1 ifconfig h1-eth0 192.168.1.2 netmask 255.255.255.0` | 手动绑静态 IP | — |
| 3 | `h1 arping -c 2 -A -I h1-eth0 192.168.1.2` | 免费 ARP，让 switch 学习 | — |
| 4 | `h2 dhclient -v h2-eth0` | h2 发起 DHCP | — |
| 5 | 回终端1看日志 | **必须**依次出现：<br>① `[DHCP] ARP PROBE sent for IP 192.168.1.2`<br>② `[DHCP] ARP CONFLICT flagged for IP 192.168.1.2`<br>③ `[DHCP] ARP CONFLICT detected on IP 192.168.1.2`<br>④ `[DHCP] ARP PROBE sent for IP 192.168.1.3`<br>⑤ `[DHCP] ARP PROBE clear for IP 192.168.1.3`<br>⑥ `[DHCP] OFFER IP 192.168.1.3 -> MAC ...` | □ 通过 / □ 失败 |
| 6 | `h2 ifconfig` | IP ≠ `192.168.1.2` | □ 通过 / □ 失败 |
| 7 | `h2 ifconfig` | IP = `192.168.1.3` | □ 通过 / □ 失败 |

> **这是最关键的测试用例**，必须同时出现步骤5的全部6条日志。

---

### Test A2: 正常分配不触发冲突（回归验证）

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 重启 Mininet（或清理 h2） | — | — |
| 2 | h1 **不设静态 IP** | — | — |
| 3 | `h1 dhclient -v h1-eth0` | 获得 192.168.1.2 | □ |
| 4 | 回终端1看日志 | ① `ARP PROBE sent for IP 192.168.1.2`<br>② `ARP PROBE clear for IP 192.168.1.2`<br>③ `OFFER IP 192.168.1.2` | □ 通过 / □ 失败 |

---

### Test A3: 冲突黑名单缓存

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 执行 Test A1（h1 绑 .2，h2 拿到 .3） | — | □ |
| 2 | `h2 dhclient -r h2-eth0` | 释放 IP | — |
| 3 | `h2 dhclient -v h2-eth0` | 重新请求 | — |
| 4 | 回终端1看日志 | 出现 `[DHCP] IP 192.168.1.2 still in conflict list (XXs ago), skipping`<br>h2 跳过 .2，直接拿到 .3 | □ 通过 / □ 失败 |

---

### Test A4: DHCPDECLINE 手动触发（高级）

> 此测试需要用 scapy 构造 DHCPDECLINE 包，或手动向控制器注入。以下给出两种方法。

#### 方法 A：scapy 构造 DECLINE

```bash
# 在 Mininet 终端（或 Mininet host 上）
# 需要先安装 scapy: pip3 install scapy

h1 python3 << 'EOF'
from scapy.all import *
# 构造 DHCPDECLINE
pkt = Ether(dst="ff:ff:ff:ff:ff:ff")/IP(src="0.0.0.0",dst="255.255.255.255")/UDP(sport=68,dport=67)/BOOTP(chaddr=get_if_hwaddr("h1-eth0"))/DHCP(options=[("message-type","decline"),("server_id","192.168.1.1"),("requested_addr","192.168.1.2"),"end"])
sendp(pkt, iface="h1-eth0")
EOF
```

#### 方法 B：直接验证代码逻辑（备选）

如果无法发 DECLINE 包，可在控制器代码验证：

| 步骤 | 预期 | 判定 |
|------|------|------|
| 1 | 查看 dhcp.py `handle_dhcp` 中 DEBCLINE 分支存在 | □ |
| 2 | 查看 `_conflict_ips` 更新逻辑 | □ |
| 3 | 查看 `_release_lease` 调用 | □ |

> **判定标准**：步骤1-3 全部存在即可认为此功能已实现，报告中写明"代码已支持，scapy 可触发测试"。

---

### Test A5: Conflict Blacklist TTL 过期

| 步骤 | 命令 | 预期 | 判定 |
|------|------|------|------|
| 1 | 执行 Test A1（.2 进入黑名单） | — | □ |
| 2 | 确认日志中有冲突记录 | — | □ |
| 3 | 等待 **300+ 秒**（conflict_ttl=300） | — | — |
| 4 | 终端1日志出现 stale conflict 清理 | — | □ |
| 5 | 释放现有 DHCP 租约后重新请求 | .2 重新可用 | □ 通过 / □ 失败 |

> 300 秒等待时间较长，Demo 时可将 `conflict_ttl` 临时改为 `60`。

---

## 三、测试结果汇总表

| 编号 | 测试项 | 状态 | 备注 |
|------|--------|------|------|
| L1 | 基本分配 + Option 51 | □ | |
| L2 | 租约过期自动回收 | □ | |
| L3 | DHCPRELEASE 主动释放 | □ | |
| L4 | IP 池耗尽 | □ | |
| A1 | ARP Probe 检测静态IP冲突 | □ | ★ 最关键 |
| A2 | 正常分配不触冲突 | □ | |
| A3 | 冲突黑名单缓存 | □ | |
| A4 | DHCPDECLINE 处理 | □ | 需 scapy |
| A5 | Conflict TTL 过期 | □ | 可选 (300s) |

---

## 四、快速 Demo 流程（Week 16, ~3 分钟）

```
1. 启动 controller + Mininet
2. 终端1 保持可见，日志滚动
3. h1 静态绑 192.168.1.2
   → h1 ifconfig h1-eth0 192.168.1.2 netmask 255.255.255.0
   → h1 arping -c 2 -A -I h1-eth0 192.168.1.2

4. h2 dhclient -v h2-eth0
   ★ 重点：指终端1的日志 ALIGN [DHCP] ARP PROBE / CONFLICT / OFFER
   → h2 拿到 192.168.1.3（不是 .2！）

5. h2 dhclient -r h2-eth0  → 指 RELEASED 日志（租约释放）

6. h2 dhclient -v h2-eth0  → 指 RENEW 或 OFFER 日志（续约/重分配）

7. 等待 60s → 指自动 RELEASED（后台回收）

8. tcpdump 截图 Option 51 = 60
```

---

## 五、关键日志速查表

| 场景 | 日志关键字 |
|------|-----------|
| 分配 IP | `[DHCP] OFFER IP` + `[DHCP] ACK IP` |
| 续约 | `[DHCP] RENEW IP` |
| 释放 | `[DHCP] RELEASED IP` |
| ARP 探测 | `[DHCP] ARP PROBE sent for IP` |
| ARP 无冲突 | `[DHCP] ARP PROBE clear for IP` |
| ARP 有冲突 | `[DHCP] ARP CONFLICT flagged` → `ARP CONFLICT detected` |
| 冲突缓存中 | `[DHCP] IP X still in conflict list` |
| 拒绝请求 | `[DHCP] NAK sent to MAC` |
| 客户端拒接 | `[DHCP] DECLINE received` |
| 池耗尽 | `[DHCP] No free IP for MAC` |
