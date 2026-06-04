# CS305-2026Spring-Project 测试方案

## 一、环境前置检查

测试前需确认以下条件全部满足：

| 检查项 | 命令 | 预期 |
|--------|------|------|
| Python 版本 | `conda activate cs305 && python --version` | Python 3.8.x |
| os-ken 已安装 | `osken-manager --version` | 输出版本号 |
| Mininet 已安装 | `sudo mn --test pingall` | 0% packet loss |
| arping 已安装 | `which arping` | `/usr/sbin/arping` |
| 项目依赖已安装 | `pip list \| grep -E "os-ken\|mininet\|eventlet"` | 见 requirements.txt |

## 二、测试层次总览

```
测试体系
├── 单元测试（无需控制器，纯逻辑验证）
│   ├── test_lease_unit.py        # 租约状态机、过期回收、续约、释放
│   └── test_lease_rfc_unit.py    # ARP 探测、NAK、DECLINE、冲突黑名单
│
└── 集成测试（需要控制器运行 + Mininet）
    ├── DHCP 基础测试             # test_network.py（2 主机 1 交换机）
    ├── 最短路径交换测试           # test_network.py（3 主机 3 交换机三角形）
    ├── 防火墙测试                # test_network.py（3 主机 1 交换机）
    ├── 租约时长集成测试           # test_lease.py
    └── ARP 探测集成测试           # test_lease_rfc.py
```

## 三、通用测试流程

### 启动控制器（终端 1）

```bash
conda activate cs305
cd CS305-2026Spring-Project
osken-manager --observe-links controller.py
```

`--observe-links` 参数**必须**携带，否则 LLDP 链路发现不会启动。

### 每次测试后清理

```bash
sudo mn -c
```

### 运行测试（终端 2）

所有 Mininet 测试需以 root 权限运行，同时传递 conda PATH：

```bash
sudo env "PATH=$PATH" python <test_script>.py
```

## 四、单元测试（无需控制器）

### 4.1 租约时长单元测试

```bash
python tests/dhcp_test/test_lease_unit.py
```

| 编号 | 测试项 | 验证内容 |
|------|--------|----------|
| Test 1 | 基础分配 | OFFER → ACK 流程正确，状态转移 OFFERED → ALLOCATED |
| Test 2 | 不同 IP | 两台主机获得不同 IP 地址 |
| Test 3 | 池耗尽 | 仅 2 个 IP 时第 3 台主机返回 None |
| Test 4 | DHCPRELEASE | 释放后 IP 可立即重新分配 |
| Test 5 | 过期回收 | 等待 lease_time+1s 后租约被 Reaper 自动回收 |
| Test 6 | 续约 | DHCPREQUEST 刷新 expires_at 时间戳 |
| Test 7 | 同 MAC 复用 | 相同 MAC 地址再次请求获得相同 IP |

**预期结果**：15 条断言全部 PASS，0 失败。

### 4.2 ARP 探测防冲突单元测试

```bash
python tests/dhcp_test/test_lease_rfc_unit.py
```

| 编号 | 测试项 | 验证内容 |
|------|--------|----------|
| Test 1 | 基础分配 | 正常流程，IP 分配正确 |
| Test 2 | ARP Probe 无冲突 | 探测返回 True，IP 未加入冲突列表 |
| Test 3 | ARP Probe 有冲突 | 探测标志变为 False，IP 加入冲突列表 |
| Test 4 | 跳过冲突 IP | `_find_free_ip` 跳过被标记冲突的 IP，分配下一个 |
| Test 5 | 冲突 TTL 过期 | expired 时间后冲突 IP 重新可用 |
| Test 6 | NAK（OFFER 不匹配） | 请求 IP 与 OFFER 不一致时返回 DHCPNAK |
| Test 7 | NAK（续约不匹配） | 续约时请求 IP 与租约不一致时返回 DHCPNAK |
| Test 8 | DHCPDECLINE | 主机拒绝 IP → 标记冲突 → 从 ip_to_mac 移除 |
| Test 9 | 全池冲突 | 所有可用 IP 均被冲突时返回 None |
| Test 10 | 首 IP 冲突回退 | 第一个 IP 冲突 → 自动跳过 → 分配第二个 IP |

**预期结果**：17 条断言全部 PASS，0 失败。

## 五、DHCP 基础集成测试

### 测试拓扑

```
h1 ---- s1 ---- h2
```

### 运行

```bash
cd tests/dhcp_test
sudo env "PATH=$PATH" python test_network.py
```

### 验证步骤

进入 Mininet CLI 后，脚本会自动为 h1 和 h2 执行 `dhclient`。手动验证：

```
mininet> h1 ifconfig
mininet> h2 ifconfig
```

### 通过标准

| 检查项 | 预期 |
|--------|------|
| h1 获得 IP | 192.168.1.2 ~ 192.168.1.99 范围内 |
| h2 获得 IP | 192.168.1.2 ~ 192.168.1.99 范围内，且 ≠ h1 的 IP |
| 控制器日志 | 出现 `[DHCP] OFFER IP` 和 `[DHCP] ACK IP` |
| ARP 探测 | 出现 `[DHCP] ARP PROBE sent` 和 `ARP PROBE clear` |

## 六、最短路径交换集成测试

### 测试拓扑

```
        h1
         |
        s1
       /   \
     s2 --- s3
     |       |
    h2      h3
```

### 运行

```bash
cd tests/switching_test
sudo env "PATH=$PATH" python test_network.py
```

### 验证步骤

进入 Mininet CLI 后：

```
mininet> pingall
```

### 通过标准

| 检查项 | 预期 |
|--------|------|
| pingall 结果 | 0% packet loss（6/6 received） |
| 最短路径 h1↔h2 | h1 → s1 → s2 → h2（3 跳） |
| 最短路径 h1↔h3 | h1 → s1 → s3 → h3（3 跳） |
| 控制器日志 | 显示计算出的最短路径及其长度 |

### 额外验证

```
mininet> dpctl dump-flows    # 查看流表，应包含目的 MAC 匹配规则
mininet> net                 # 确认拓扑连接正确
mininet> h1 ping -c 3 h2     # 单点 ping 验证
```

## 七、防火墙集成测试

### 测试拓扑

```
h1 (192.168.117.2) ----\
h2 (192.168.117.3) ----- s1
h3 (192.168.117.4) ----/
```

### 防火墙规则（firewall_rules.json）

```json
{
  "rules": [
    { "src_ip": "192.168.117.2", "dst_ip": "192.168.117.3", "proto": "icmp", "action": "deny" },
    { "src_ip": "192.168.117.2", "dst_ip": "192.168.117.3", "proto": "tcp",  "dst_port": 80, "action": "deny" }
  ]
}
```

### 运行

```bash
cd tests/firewall_test
sudo env "PATH=$PATH" python test_network.py
```

### 四项核心测试

| 编号 | 测试 | 命令 | 预期结果 | 判定依据 |
|------|------|------|----------|----------|
| Test 1 | h1→h2 ICMP | `h1 ping -c 2 192.168.117.3` | **阻断** | 100% packet loss |
| Test 2 | h1→h3 ICMP | `h1 ping -c 2 192.168.117.4` | **放行** | 0% packet loss |
| Test 3 | h1→h2 TCP/80 | `curl http://192.168.117.3:80/` | **阻断** | 连接超时 / 000 |
| Test 4 | h1→h2 TCP/8080 | `curl http://192.168.117.3:8080/` | **放行** | HTTP 200 |

### 通过标准

4 项测试全部符合预期 = 防火墙模块正常工作。

## 八、Bonus 功能集成测试

### 8.1 租约时长（test_lease.py）

```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease.py
```

| 验证点 | 预期 |
|--------|------|
| 租约分配 | OFFER/ACK 携带 `expires in 60s` |
| 过期回收 | 等待 65s 后出现 `[DHCP] RELEASED IP` |
| 释放后重分配 | 释放的 IP 可被其他主机获取 |
| IP 池耗尽 | 3 台主机共享 2 个 IP 时第 3 台返回 None |

### 8.2 ARP 探测防冲突（test_lease_rfc.py）

```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease_rfc.py
```

| 验证点 | 预期 |
|--------|------|
| 静态 IP 冲突检测 | h1 已占用 .2 → h2 DHCP 探测到冲突 → 跳过 .2 分配 .3 |
| 冲突日志 | 依次出现 PROBE sent → CONFLICT flagged → CONFLICT detected → 跳过 → 分配到下一个 IP |
| 黑名单缓存 | 再次请求时日志显示 "still in conflict list, skipping" |
| 冲突 TTL 过期 | 300s 后 IP 重新可用 |

详细的 Bonus 人工测试步骤见 `tests/dhcp_test/MANUAL_TEST.md`。

## 九、已知问题：os-ken 版本兼容性 Bug

### 问题描述

`controller.py` 的 `handle_link_add`（第 285 行）和 `handle_link_delete`（第 297 行）中使用 `link.src.dp.id` / `link.dst.dp.id` 获取链路两端交换机的 DPID。但在当前 os-ken（3.1.1）中，LLDP 链路发现传递给 `EventLinkAdd`/`EventLinkDelete` 的 `link.src` / `link.dst` 是 `Port` 对象，而 `Port` 类的 DPID 直接存储在 `dpid` 属性中，没有 `dp` 这一层嵌套。

**根源**（os-ken 源码 `topology/switches.py:808`）：
```python
# LLDP 包处理中创建 Link：
link = Link(src, dst)  # src, dst 是 Port 对象
self.send_event_to_observers(event.EventLinkAdd(link))
```

**Port 类定义**（`switches.py:59-64`）：
```python
class Port(object):
    def __init__(self, dpid, ofproto, ofpport):
        self.dpid = dpid       # 直接属性，类型为 int
        # ... 注意：没有 self.dp
```

**错误调用链**：
```
LLDP Packet-In → Link(src=Port, dst=Port)
  → EventLinkAdd(link)
    → controller.py:handle_link_add()
      → link.src.dp.id        # AttributeError: 'Port' object has no attribute 'dp'
```

### 影响范围

| 测试 | 影响 | 原因 |
|------|------|------|
| DHCP 基础测试 | ✅ 不受影响 | 单交换机拓扑，无 inter-switch 链路，EventLinkAdd 不触发 |
| 最短路径交换测试 | ❌ 完全阻塞 | `handle_link_add` 崩溃 → 链路数据无法记录 → Dijkstra 无拓扑输入 → 转发流表不安装 → pingall 100% 丢包 |
| 防火墙测试 | ⚠️ 部分阻塞 | DROP 规则通过 `switch_features_handler` 正常安装（阻塞生效）；但转发流表不安装（h1→h3 放行失败） |
| Bonus 租约/ARP 测试 | ✅ 不受影响 | 单交换机拓扑 |

### 修复方案

将 `link.src.dp.id` 改为兼容写法，同时支持两种 os-ken 版本：

```python
# handle_link_add（第 284-285 行，原代码）
src_dpid = getattr(link.src, 'dpid', None) or link.src.dp.id
dst_dpid = getattr(link.dst, 'dpid', None) or link.dst.dp.id

# handle_link_delete（第 297-298 行，同理）
src_dpid = getattr(link.src, 'dpid', None) or link.src.dp.id
dst_dpid = getattr(link.dst, 'dpid', None) or link.dst.dp.id
```

逻辑：优先取 `link.src.dpid`（os-ken 3.x Port 对象直接属性），若不存在（值为 `None` 或 `0` 导致 `or` 短路）则回退到 `link.src.dp.id`（旧版 os-ken 中 LinkPort 有 `dp` 属性）。注意：DPID 为 0 在 OpenFlow 中是非法值，所以 `or` 短路不会造成误判。

---

## 十、常见问题与排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| `Unable to contact remote controller` | 控制器未启动或 `--observe-links` 缺失 | 检查终端 1 控制器是否 running |
| pingall 100% 丢包 | 大概率是第九节所述的 `dp.id` 兼容性 bug | 按第九节修复方案修改 `controller.py` 后重试 |
| pingall 100% 丢包（修复后） | LLDP 链路发现未触发 / 主机发现失败 / 等待时间不足 | 检查 `--observe-links`；确认 arping 已执行；等待 5s 再 pingall |
| DHCP 无响应 | dhclient 未安装或 PATH 未传递 | `sudo env "PATH=$PATH"` 或 `apt install isc-dhcp-client` |
| `sudo mn -c` 后仍有残留 | Mininet 未正确清理 | 手动 `pkill -9 ovs` 并重试 |
| conda 环境找不到 | sudo 重置了 PATH | 必须使用 `sudo env "PATH=$PATH"` 传递环境变量 |
| 控制器日志无输出 | os-ken 日志级别过滤 | 检查 logger 配置或在代码中用 `print()` 输出 |
| WSL2 环境下 pingall 全丢包 | WSL2 对网络命名空间支持有限，LLDP 包可能丢失 | 建议在原生 Linux VM（如 VirtualBox + Mininet 官方镜像）中测试 |

## 十一、自动化测试脚本参考

项目提供了以下可直接运行的测试入口：

```bash
# === 无需控制器 ===
python tests/dhcp_test/test_lease_unit.py          # 15 条断言
python tests/dhcp_test/test_lease_rfc_unit.py      # 17 条断言

# === 需要控制器（终端 1 先启动 osken-manager） ===
sudo env "PATH=$PATH" python tests/dhcp_test/test_network.py       # DHCP 基础
sudo env "PATH=$PATH" python tests/switching_test/test_network.py  # 最短路径交换
sudo env "PATH=$PATH" python tests/firewall_test/test_network.py   # 防火墙
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease.py         # 租约时长
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease_rfc.py     # ARP 探测
```

**推荐测试顺序**：单元测试 → DHCP 基础 → 防火墙 → 最短路径交换 → Bonus 功能。

## 十二、评分对照

| 模块 | 分值 | 测试方法 |
|------|------|----------|
| 环境搭建 | 10 | `mn --test pingall` + `osken-manager --version` |
| DHCP | 20 | `test_network.py` + 单元测试 |
| 最短路径交换 | 40 | `pingall` 0% 丢包 + 路径正确 |
| 防火墙 | 20 | 4 项测试全部通过 |
| 报告 | 10 | `report.pdf` |
| Bonus | ≤20 | `test_lease.py` + `test_lease_rfc.py` |
