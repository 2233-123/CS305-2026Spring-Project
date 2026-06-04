# Lab 15 现场演示流程说明

> 基于 https://github.com/TsingYiPainter/CS305-2026Spring-Project/blob/main/project-instructions.md

---

## 环境准备

```bash
# 进入项目目录
cd /mnt/d/Sustech/ComputerNetwork/CS305-2026Spring-Project

# 确保 conda 环境激活
conda activate cs305

# 安装依赖（如未安装）
pip install -r requirements.txt

# 确认 networkx 已安装
python -c "import networkx; print(networkx.__version__)"

# 确认 dhcp.py 为原始版本（未被之前测试修改过）
git checkout -- dhcp.py

# 每次 Mininet 运行后清理残留
sudo mn -c
```

---

## 第一部分：DHCP（动态主机配置协议）

### 1.1 基础测试 — 默认配置

**终端 1（启动控制器）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（运行测试）：**
```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_network.py
```

**预期结果：**
- 控制器日志显示 DHCP DISCOVER → OFFER → REQUEST → ACK 流程
- h1 获得 `192.168.1.2`，h2 获得 `192.168.1.3`
- `start_ip=192.168.1.2`, `end_ip=192.168.1.100`, `netmask=255.255.255.0`

**演示要点：**
- 在控制器终端中展示 DHCP 日志：`[DHCP] OFFER IP 192.168.1.2 -> MAC ...`
- 在 Mininet CLI 中运行 `h1 ifconfig` 验证 IP 地址
- 运行 `h2 ifconfig` 验证 IP 地址

**退出后清理：**
```bash
sudo mn -c
```

---

### 1.2 自定义配置 — 修改 IP 范围与子网掩码

**终端 2（运行测试 — 脚本会自动修改 dhcp.py）：**
```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_network_custom.py
```

脚本会：
1. 自动修改 `dhcp.py` 中的配置为 `10.0.0.10` ~ `10.0.0.20`
2. 提示你重启控制器

**终端 1（重启控制器 — 用新的 dhcp.py 配置）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（按回车继续）：**

**配置变化（脚本写入 dhcp.py）：**
- `start_ip = 10.0.0.10`
- `end_ip = 10.0.0.20`
- `netmask = 255.255.255.0`
- `server_ip = 10.0.0.1`

**预期结果：**
- 所有 6 台主机获得 `10.0.0.10` ~ `10.0.0.15` 范围内的地址
- 控制器日志显示新子网的 DHCP 分配

**演示要点：**
- 展示 h1: `10.0.0.10`，h3: `10.0.0.12`
- 运行 `pingall` 验证连通性

**退出后清理：**
```bash
# 脚本退出时自动恢复原始 dhcp.py
sudo mn -c
```

---

### 1.3 地址池耗尽 — 主机数超过可用IP数

**终端 2（运行测试 — 脚本会自动修改 dhcp.py 缩小 IP 池）：**
```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_network_exhaust.py
```

脚本会：
1. 自动修改 `dhcp.py`：`end_ip = 192.168.1.5`（仅有 4 个可用 IP）
2. 提示你重启控制器

**终端 1（重启控制器）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（按回车继续）：**

**配置：**
- `start_ip = 192.168.1.2`, `end_ip = 192.168.1.5` → 共 4 个可用 IP
- 创建 8 台主机（m=8, n=4）

**预期结果：**
- 前 4 台主机（h1~h4）获得 `192.168.1.2` ~ `192.168.1.5`
- 后 4 台主机（h5~h8）**未获得 IP**
- 控制器日志显示：`[DHCP] No free IP for MAC ...`

**演示要点：**
- 展示前 4 台主机的 IP
- 展示 h5~h8 无 IP（`ifconfig` 无 inet addr）
- 展示控制器日志中的 POOL EXHAUSTED 信息

**退出后清理：**
```bash
# 脚本退出时自动恢复原始 dhcp.py（end_ip 恢复为 192.168.1.100）
sudo mn -c
```

---

## 第二部分：最短路径交换

### 2.1 基础测试 — 三角拓扑 + pingall

**终端 1（启动控制器）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（运行测试）：**
```bash
sudo env "PATH=$PATH" python tests/switching_test/test_network.py
```

**拓扑：**
```
h1---s1---s2---h2
      \ /
      s3
       |
      h3
```

**控制器日志输出（每次拓扑变化时打印）：**
```
[HostAdd] handle_host_add: mac=... ip=192.168.1.2 dpid=1 port=1
[HostAdd] handle_host_add: mac=... ip=192.168.1.3 dpid=2 port=1
[HostAdd] handle_host_add: mac=... ip=192.168.1.4 dpid=3 port=1
[Topology] === Current Topology ===
[Topology] Switches: [1, 2, 3]
[Topology] Links: [(1,2), (1,3), (2,3)]
[Topology] Hosts: [('192.168.1.2', 1, 1), ...]
[Topology] === Switch-to-Switch Shortest Paths ===
[Topology]   s1 -> s2 : s1 -> s2, 1 edge
[Topology]   s1 -> s3 : s1 -> s3, 1 edge
[Topology]   s2 -> s3 : s2 -> s3, 1 edge
[Routing] === Host-to-Host Paths ===
[NetworkX] Graph: 6 nodes, 5 edges
```

**Mininet CLI操作：**
```
> pingall        # 验证所有主机可达
> pingall full   # 详细看ping结果
```

**演示要点：**
- 展示控制器终端中打印的拓扑结构和所有交换机对之间的最短路径
- 展示 networkx 模块输出的图信息
- 展示 `pingall` 结果：全部可达

**退出后清理：**
```bash
sudo mn -c
```

---

### 2.2 复杂测试 — 8台交换机 + 8台主机 + 动态拓扑变更

#### 2.2.1 初始化拓扑图

运行 `python tests/complex_test/visualize.py` 生成拓扑图 `topology.png`，
展示初始拓扑结构及标注的各主机对间最短路径。

**拓扑结构：**
```
        h1 --- s1 ---- s2 --- h2
                |  \  / |
                |   \/  |
                s3--s4--s5
               / \  |  / \
              /   \ | /   \
            h3     s6-s7    h4
                    | |     |
                    s8-h5  h8
                   /
                 h6
        h7 - s1

8 台交换机: s1-s8
8 台主机:   h1-h8  (IP由DHCP分配)
13 条交换机间链路 + 8 条主机-交换机链路 = 21 条边
```

#### 2.2.2 启动测试

**终端 1（启动控制器）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（运行测试）：**
```bash
sudo env "PATH=$PATH" python tests/complex_test/test_network.py
```

控制器控制台会自动打印：
- `[Topology] === Current Topology ===` — 交换机列表、链路列表、主机列表
- `[Topology] === Switch-to-Switch Shortest Paths ===` — 所有交换机对的最短路径
- `[Routing] === Host-to-Host Paths ===` — 所有主机对的最短路径
- `[NetworkX] Graph: XX nodes, XX edges` — networkx 图统计
- `[NetworkX] Switch-to-Switch shortest paths (networkx):` — networkx 计算的最短路径

#### 2.2.3 动态拓扑变更操作（在 Mininet CLI 中执行）

```
MN Step 1: > pingall
   # 验证所有主机可达（8台主机完全连通）
   # 此时 handle_host_add 已在初始化时触发（主机 ARP 发现）

MN Step 2: > switch s3 stop
   # 触发 handle_switch_delete
   # 控制器自动打印新的拓扑结构和最短路径
   # h3 与网络断开（因h3连在s3上）

MN Step 3: > pingall
   # 验证：除h3外的主机仍可达；h3不可达

MN Step 4: > switch s3 start
   # 触发 handle_switch_add
   # 控制器自动打印恢复后的拓扑和路径

MN Step 5: > arping_all
   # h3 重新发送 gratuitous ARP → 触发 handle_host_add
   # 控制器日志显示: [HostAdd] handle_host_add: mac=... ip=... dpid=3 port=...
   # 同时触发 _install_host_flows，打印更新后的拓扑和路径

MN Step 6: > pingall
   # 验证所有主机再次可达

MN Step 7: > link s1 s2 down
   # 触发 handle_link_delete
   # 观察 s1-s2 直接链路被移除后的路径变化

MN Step 8: > link s1 s2 up
   # 触发 handle_link_add

MN Step 9: > sh ovs-ofctl mod-port s6 1 down
   # 触发 handle_port_modify + EventOFPPortStatus
   # 如果s6的端口1连到s3，则s3-s6链路断开

MN Step 10: > pingall
   # 验证受影响的路径下主机连通性

MN Step 11: Ctrl+D 退出
```

**每次拓扑修改后控制器控制台自动输出：**
- `[Topology] === Current Topology ===` — 当前交换机、链路、主机
- `[Topology]   sX -> sY : sX -> ... -> sY, N edges` — 交换机间最短路径
- `[NetworkX]   sX -> sY : sX -> ... -> sY, N edges (nx)` — networkx 验证

**覆盖的拓扑修改操作：**
| 操作 | Mininet 命令 | 触发回调 | 何时触发 |
|---|---|---|---|
| `handle_switch_add` | `switch s3 start` | `EventSwitchEnter` | 启动/恢复交换机时 |
| `handle_switch_delete` | `switch s3 stop` | `EventSwitchLeave` | 停止交换机时 |
| `handle_host_add` | `arping_all` (host re-ARP) | `EventHostAdd` | 初始化时 + switch重启后 re-ARP |
| `handle_link_add` | `link s1 s2 up` | `EventLinkAdd` | 恢复/添加链路时 |
| `handle_link_delete` | `link s1 s2 down` | `EventLinkDelete` | 断开链路时 |
| `handle_port_modify` | `sh ovs-ofctl mod-port s6 1 down` | `EventPortModify` + `EventOFPPortStatus` | 端口状态变化时 |

**退出后清理：**
```bash
sudo mn -c
```

---

## 第三部分：防火墙

### 3.1 基础测试

确保 `firewall_rules.json` 包含默认规则：
```json
{
  "rules": [
    {
      "src_ip": "192.168.117.2",
      "dst_ip": "192.168.117.3",
      "proto": "icmp",
      "src_port": "*",
      "dst_port": "*",
      "action": "deny"
    },
    {
      "src_ip": "192.168.117.2",
      "dst_ip": "192.168.117.3",
      "proto": "tcp",
      "src_port": "*",
      "dst_port": 80,
      "action": "deny"
    }
  ]
}
```

**终端 1（启动控制器）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（运行测试）：**
```bash
sudo env "PATH=$PATH" python tests/firewall_test/test_network.py
```

**预期结果：**
- h1(`192.168.117.2`) → h2(`192.168.117.3`) ICMP：**BLOCKED**
- h1(`192.168.117.2`) → h3(`192.168.117.4`) ICMP：**PASS**
- h1 → h2 TCP/80：**BLOCKED**
- h1 → h2 TCP/8080：**PASS**

**演示要点：**
- 展示 ping 结果（blocked vs pass）
- 展示 curl 结果（HTTP 80 blocked, 8080 pass）
- 解释：防火墙规则仅阻止特定 IP 对 + 协议/端口组合

**退出后清理：**
```bash
sudo mn -c
```

---

### 3.2 复杂测试 — 防火墙 + 最短路径联合

此测试复用复杂拓扑（8交换机 + 8主机，使用静态 IP）。

**IP 分配：**
| 主机 | IP |
|---|---|
| h1 | 192.168.100.2 |
| h2 | 192.168.100.3 |
| h3 | 192.168.100.4 |
| h4 | 192.168.100.5 |
| ... | ... |
| h8 | 192.168.100.9 |

**防火墙规则（block h1->h2）：**
```json
{
  "rules": [
    {"src_ip": "192.168.100.2", "dst_ip": "192.168.100.3", "proto": "icmp", "action": "deny"},
    {"src_ip": "192.168.100.2", "dst_ip": "192.168.100.3", "proto": "tcp", "src_port": "*", "dst_port": 80, "action": "deny"}
  ]
}
```

**终端 1（启动控制器）：**
```bash
osken-manager --observe-links controller.py
```

**终端 2（运行测试 — 阶段一：防火墙启用）：**
```bash
sudo env "PATH=$PATH" python tests/complex_test/test_firewall.py
```

**阶段一预期结果（防火墙规则生效）：**
- h1 → h2 ICMP：**BLOCKED**（Ping 100% packet loss）
- h1 → h3 ICMP：**REACHABLE**（0% packet loss）
- h1 → h4, h1 → h7 ICMP：**REACHABLE**
- h1 → h2 TCP/80：**BLOCKED**

**阶段二（防火墙规则移除）：**
1. 按 Ctrl+C 退出 Mininet
2. 脚本自动恢复原始 firewall_rules.json（无规则）
3. 重启控制器：`osken-manager --observe-links controller.py`
4. 按回车运行阶段二
5. 验证：**h1 → h2 恢复可达**

**演示要点：**
- "之前可达的两台主机现在变得不可达" → h1 不能 ping h2（被防火墙阻止）
- 但 h1 可以 ping h3, h4, h5...（防火墙未阻止）
- 控制台仍打印交换机间最短路径（路径本身不变，但流表阻止了特定流量）
- 从控制器日志中验证网络拓扑结构与阶段一中无变化

**退出后清理：**
```bash
sudo mn -c
```

---

## 演示检查清单（评分点）

| 编号 | 检查项 | 测试脚本 | 关键验证 |
|---|---|---|---|
| 1 | DHCP 默认配置 | `tests/dhcp_test/test_network.py` | h1,h2 获得 `192.168.1.2~3` |
| 2 | DHCP 自定义配置 | `tests/dhcp_test/test_network_custom.py` | 主机获得 `10.0.0.x` |
| 3 | DHCP 地址池耗尽 | `tests/dhcp_test/test_network_exhaust.py` | 前4有IP，后4无IP |
| 4 | 最短路径基础 | `tests/switching_test/test_network.py` | `pingall` 全通 |
| 5 | 每次拓扑变化打印路径 | 所有 shortest path 测试 | 控制器日志有 `[Topology] sX -> sY` |
| 6 | 复杂拓扑（>6H + >6S + >10E） | `tests/complex_test/test_network.py` | 8H + 8S + 13S-S边 |
| 7 | 动态变更：switch stop/start | CLI: `switch s3 stop/start` | 路径自动更新 |
| 8 | 动态变更：link down/up | CLI: `link s1 s2 down/up` | 路径自动更新 |
| 9 | 动态变更：port modify | CLI: `sh ovs-ofctl mod-port s6 1 down` | 端口事件处理 |
| 10 | networkx 打印拓扑 | 控制器日志 | `[NetworkX] Graph:` 输出 |
| 11 | 防火墙基础 | `tests/firewall_test/test_network.py` | ICMP/TCP block |
| 12 | 防火墙+最短路径 | `tests/complex_test/test_firewall.py` | h1→h2 blocked, h1→h3 ok |
| 13 | 防火墙使可达变不可达 | 阶段一 vs 阶段二 | 阶段一 blocked, 阶段二 reachable |
| 14 | 拓扑图 | `tests/complex_test/visualize.py` | 提供 `topology.png` |

---

## 快速演示路线（总时间约 5-8 分钟）

如果时间有限，按以下顺序快速演示：

1. **DHCP 基础**（1分钟）：运行 `test_network.py`，展示控制器日志中 DHCP 分配
2. **DHCP 耗尽**（1分钟）：运行 `test_network_exhaust.py`，展示无IP主机
3. **最短路径复杂拓扑**（2分钟）：运行 `test_network.py`，展示 `pingall` → `switch s3 stop` → `pingall`，观察路径变化
4. **防火墙基础**（1分钟）：运行防火墙 `test_network.py`，展示 blocking
5. **防火墙+复杂拓扑**（2分钟）：运行阶段一展示 h1→h2 blocked，然后展示网络拓扑结构（networkx 输出）
6. 展示生成的 `topology.png` 拓扑图

---

## 常见问题处理

| 问题 | 解决方案 |
|---|---|
| 端口冲突 | `sudo mn -c` 清理 Mininet 残留 |
| 控制器未能连接 | 检查控制器在终端1中已启动且无报错 |
| DHCP 未分配 IP | 检查 IPv6 已禁用；尝试重新运行 `dhclient` |
| pingall 失败 | 先运行 `arping_all` 广播 ARP，再 pingall |
| 防火墙规则不生效 | 检查 `firewall_rules.json` 格式正确；控制器启动后才加载 |
| 路径打印不完整 | 确认拓扑已稳定（等待2-3秒让LLDP发现链路） |

---

## 演示前检查

- [ ] 终端1已启动 `osken-manager --observe-links controller.py`
- [ ] `firewall_rules.json` 已恢复为原始内容
- [ ] `sudo mn -c` 已执行过（无 Mininet 残留）
- [ ] conda 环境 `cs305` 已激活
- [ ] `networkx` 已安装（`pip install networkx`）
- [ ] `topology.png` 已生成（`python tests/complex_test/visualize.py`）
- [ ] 单元测试全部通过（`python tests/*/test_*_unit.py`）

---

## Bonus 1: DHCP 租约期限 (Lease Duration)

### B1.1 功能概述

实现了完整的 DHCP 租约生命周期管理：
- 分配时记录 `expires_at` 过期时间戳
- 后台 Greenlet 定时回收过期租约（`_lease_reaper`）
- 支持 DHCPRELEASE 主动释放
- 支持 DHCPREQUEST 续约 (RENEW)
- IP 回收后可重新分配

关键配置（`dhcp.py`）：
```
lease_time = 60         # 租约 60 秒
reaper_interval = 30    # 每 30 秒扫描一次过期租约
```

状态机：`PROBING → OFFERED → ALLOCATED → RELEASED`

### B1.2 单元测试（无需控制器）

```bash
# 运行：7 个测试, 15 条断言
python tests/dhcp_test/test_lease_unit.py
```

### B1.3 集成测试

**终端 1：**
```bash
osken-manager --observe-links controller.py
```

**终端 2：**
```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease.py
```

**演示步骤与预期：**

| 步骤 | 操作 | 控制器日志证据 |
|------|------|---------------|
| Test 1 | h1, h2 发送 DHCP | `[DHCP] ACK IP 192.168.1.2 -> MAC ... (state ALLOCATED)` |
| Test 2 | `dhclient -r h1-eth0` 释放 | `[DHCP] RELEASED IP 192.168.1.2` |
| | h1 重新请求 | 获得新 IP (可能相同) |
| Test 4 | h1 等待 65s 使租约过期 | `[DHCP] RELEASED`（由 reaper 触发） |
| | h3 请求 DHCP | 获得 h1 释放的 IP |
| Test 5 | h1 再次 `dhclient` | `[DHCP] RENEW IP 192.168.1.2 -> MAC ...`（刷新 expires_at） |

### B1.4 演示要点

- 强调租约到期自动回收：等待 65s 后观察控制器日志 `[DHCP] RELEASED`（reaper 触发）
- 强调 `hub.sleep()` 而非 `time.sleep()`：不阻塞 os-ken 事件循环
- DHCPRELEASE 主动释放 vs 过期被动回收的区别

---

## Bonus 2: RFC 2131 ARP Probe 防 IP 重复分配

### B2.1 功能概述

严格遵循 RFC 2131 §2.2：
- 分配 IP 前广播 ARP Request 探测是否已被占用
- 等待 `probe_timeout=2s`，若收到 ARP_REPLY 则标记冲突
- 冲突 IP 加入缓存，`conflict_ttl=300s` 内不再尝试
- 支持 DHCPDECLINE（主机主动拒绝）
- 支持 DHCPNAK（请求 IP 与分配 IP 不匹配）

跨模块协作：`controller.py` 处理所有 ARP_REPLY → 调用 `DHCPServer._mark_arp_conflict(ip)`

### B2.2 单元测试（无需控制器）

```bash
# 运行：10 个测试, 17 条断言
python tests/dhcp_test/test_lease_rfc_unit.py
```

### B2.3 集成测试

**终端 1：**
```bash
osken-manager --observe-links controller.py
```

**终端 2：**
```bash
sudo env "PATH=$PATH" python tests/dhcp_test/test_lease_rfc.py
```

**演示步骤与预期：**

| 测试 | 操作 | 预期 |
|------|------|------|
| Test 1 | h1 静态设置 `192.168.1.2`，h2 发送 DHCP | h2 跳过 .2，获得 .3 |
| Test 2 | h3 正常请求 DHCP | h3 获得下一个可用 IP |
| Test 3 | h2 释放后重新请求 | `.2` 仍在冲突列表 → 跳过 |
| Test 4 | 再次释放 h2 后请求 | 同上，`.2` 仍被跳过 |

### B2.4 演示要点

- **关键日志**：`[DHCP] ARP PROBE sent for IP 192.168.1.2 from 8 switches`
- **关键日志**：`[DHCP] ARP CONFLICT detected on IP 192.168.1.2`（如果冲突）
- **关键日志**：`[DHCP] IP 192.168.1.2 still in conflict list`
- 解释 ARP Probe 如何防止两台主机获得相同 IP
- 解释冲突缓存 TTL 作用：300s 后 IP 重新可用

---

## Bonus 3: 加权路由 / Bellman-Ford 算法

### B3.1 功能概述

- `link_weights.json` 配置链路权重（默认 1）
- `routing_config.json` 选择算法（`dijkstra` 或 `bellman-ford`）
- `_dijkstra_all()` 发现等代价多路径
- NetworkX 第三方库验证最短路径

### B3.2 单元测试（无需控制器）

```bash
# 46 条断言全部通过
python tests/routing_test/test_routing_unit.py
```

### B3.3 加权路由演示

**配置文件 `link_weights.json`：**
```json
{
  "weights": [
    {"switch_pair": [1, 2], "weight": 5},
    {"switch_pair": [1, 3], "weight": 10},
    {"switch_pair": [2, 3], "weight": 1}
  ]
}
```

**终端 1：**
```bash
osken-manager --observe-links controller.py
```
控制器启动时输出：`[Routing] Link weights: {(1, 2): 5, (2, 3): 1, (1, 3): 10}`

**终端 2：**
```bash
sudo env "PATH=$PATH" python tests/routing_test/test_weighted.py
```

**拓扑（三角）：**
```
h2---s2====5====s1---h1
       |        /
       1     10
       |    /
       s3--+
       |
      h3
```

**预期路径（加权后）：**
| 起点→终点 | 跳数路由 | 加权路由 |
|-----------|---------|---------|
| s1→s2 | s1→s2 (cost=1) | s1→s2 (cost=5) |
| s1→s3 | s1→s3 (cost=1) | s1→s2→s3 (cost=6) ✨ 绕路更短！|

### B3.4 算法切换演示

修改 `routing_config.json`：
```json
{"algorithm": "bellman-ford"}
```

重启控制器后输出：`[Routing] Algorithm: bellman-ford`
验证：Bellman-Ford 与 Dijkstra 在正权重图上求出一致的最短路径。

### B3.5 演示要点

- 重点展示加权后 `s1→s3` 从直接走（cost=10）变成绕路走 s2（cost=6）
- 展示 NetworkX 输出与 Dijkstra 一致的验证
- 展示算法切换：改 JSON → 重启控制器 → 路径不变（正权重图两者等价）

---

## Bonus 4: DNS 服务器

### B4.1 功能概述

- 手动实现 DNS 报文解析与组装（wire format，零外部依赖）
- 支持 A 记录（forward）和 PTR 记录（reverse）
- DHCP 分配 IP 时自动注册 DNS 记录
- DHCP 释放/过期时自动清理 DNS 记录
- NXDOMAIN 响应未知主机名查询

### B4.2 单元测试（无需控制器）

```bash
# 17 条测试全部通过
python tests/dns_test/test_dns_unit.py
```

### B4.3 集成测试（半自动演示）

**终端 1：**
```bash
osken-manager --observe-links controller.py
```

**终端 2：**
```bash
sudo env "PATH=$PATH" python tests/dns_test/test_network.py
```

脚本自动完成 DHCP 分配和 ARP 注册后进入 Mininet CLI，手动执行以下查询：

```
> h1 nslookup h2 192.168.1.1        ← A 记录：返回 h2 的 IP
> h2 nslookup h1 192.168.1.1        ← A 记录：返回 h1 的 IP
> h1 nslookup 3.1.168.192.in-addr.arpa 192.168.1.1  ← PTR：返回 h2
> h1 nslookup unknown.host 192.168.1.1  ← NXDOMAIN
```

> 如果 `nslookup` 未安装：`sudo apt-get install -y dnsutils`

**控制器终端同步展示：**
```
[DNS] Registered h1 <-> 192.168.1.2
[DNS] Registered h2 <-> 192.168.1.3
```

### B4.4 演示要点

- 展示 DHCP 完成后 DNS 自动注册：`[DNS] Registered h1 <-> 192.168.1.2`
- 在 Mininet CLI 中用 `nslookup` 手动验证 A / PTR / NXDOMAIN
- 强调 DHCPRELEASE / 租约过期时自动清理 DNS 记录（可在 Bonus 1 中联动演示）

---

## Bonus 5: NAT (SNAT)

### B5.1 功能概述

- Source NAT (Masquerading)：内部主机访问外部网络时替换源 IP
- 状态化连接追踪（TCP 状态机：NEW → ESTABLISHED → CLOSING）
- 双向 OpenFlow 流表卸载（首包到控制器，后续硬件转发）
- 后台 GC 清理过期连接

### B5.2 单元测试（无需控制器）

```bash
# 在 conda 环境中运行（需要 os_ken）
python tests/nat_test/test_nat_unit.py
```

### B5.3 集成测试

**终端 1：**
```bash
osken-manager --observe-links controller.py
```

**终端 2：**
```bash
sudo env "PATH=$PATH" python tests/nat_test/test_network.py
```

**拓扑：**
```
  内部网络 (192.168.1.0/24)        外部网络
  ┌─────────────────────┐          ┌──────────┐
  │ h1 (DHCP)           │          │ h2       │
  │ h3 (DHCP)           │  NAT     │ 10.0.2.100│
  │         \          / │  ────→   │(静态IP)  │
  │          s1 (switch) │          └──────────┘
  └─────────────────────┘
  NAT external IP: 10.0.2.15
```

**预期结果：**

| 测试 | 操作 | 预期 |
|------|------|------|
| SNAT | h1 → h2 ping | 成功（h2 看到源 IP 为 NAT IP） |
| 验证 NAT | h2 上 tcpdump 抓包 | 源 IP = `10.0.2.15`（非 h1 的 192.168.1.x） |
| 多客户端 | h3 → h2 ping | 成功（不同内部 IP 共用一个外部 IP） |
| TCP NAT | h1 → h2 TCP/8088 | h2 收到 `HELLO_FROM_H1` |
| 内部直连 | h1 → h3 ping | 直接通过（不被 NAT） |

### B5.4 演示要点

- 展示 NAT 翻译：h2 的 tcpdump 中源 IP 是 `10.0.2.15`
- 强调双向流表卸载：首包到控制器后安装硬件流表
- 强调内部流量不经过 NAT：`_ip_in_network()` 判断
- GC 机制：`NATTable._gc` 由 `hub.spawn` 启动，定期清理过期连接

---

## Bonus 检查清单

| 编号 | Bonus 功能 | 单元测试 | 集成测试 |
|---|---|---|---|
| B1 | DHCP 租约期限 | `test_lease_unit.py` (15 PASS) | `test_lease.py` |
| B2 | ARP Probe 冲突检测 | `test_lease_rfc_unit.py` (17 PASS) | `test_lease_rfc.py` |
| B3 | 加权路由 / Bellman-Ford | `test_routing_unit.py` (46 PASS) | `test_weighted.py` |
| B4 | DNS 服务器 | `test_dns_unit.py` (17 PASS) | `test_network.py` |
| B5 | NAT (SNAT) | `test_nat_unit.py` | `test_network.py` |

---

## 快速演示路线（含 Bonus）

1. **DHCP 基础**（1分钟）：`test_network.py`
2. **DHCP 租约期限**（1分钟）：`test_lease.py`，展示 RENEW 和 RELEASE 日志
3. **ARP Probe 冲突**（1分钟）：`test_lease_rfc.py`，展示跳过冲突 IP
4. **最短路径+加权路由**（2分钟）：`test_weighted.py`，展示绕路更短
5. **复杂拓扑+动态变更**（2分钟）：`switch s3 stop → pingall → switch s3 start → pingall`
6. **防火墙**（1分钟）：`test_network.py`，展示 block
7. **DNS**（1分钟）：`test_network.py`，展示 A/PTR/NXDOMAIN
8. **NAT**（1分钟）：`test_network.py`，展示 SNAT 源 IP 替换
9. 展示 `topology.png` 拓扑图
