# CS305-2026Spring-Project 项目介绍

## 一、项目概览

这是一个 **SDN（软件定义网络）控制器** 课程项目，基于 **os-ken**（OpenStack 版 Ryu 框架）和 **Mininet**（网络仿真器）构建。项目在 OpenFlow 1.0 协议上实现了一个集中式网络控制器，支持三大核心功能：DHCP 服务器、最短路径交换和防火墙。

### 背景概念

在传统网络中，控制逻辑（如路由选择、IP 分配、访问控制）分散在各网络设备中。SDN 将控制平面与数据平面分离，通过集中式控制器以**可编程**方式管理网络。os-ken 作为控制器的运行框架负责与交换机通信并下发流表规则，Mininet 则在 Linux 上创建虚拟主机和虚拟交换机来模拟真实网络的数据转发。

## 二、项目架构

```
CS305-2026Spring-Project/
├── controller.py          # 控制器入口，拓扑感知 + ARP 处理 + 流表安装
├── dhcp.py                # DHCP 服务器（DISCOVER/OFFER/REQUEST/ACK + 租约管理 + ARP 探测）
├── firewall.py            # 防火墙模块，解析规则文件并生成高优先级 DROP 流表项
├── ofctl_utilis.py        # OpenFlow 1.0/1.2/1.3 流表操作工具库（不可修改）
├── firewall_rules.json    # 防火墙规则定义文件
├── requirements.txt       # Python 依赖
├── docs/
│   └── bonus_demo.md      # Bonus 功能文档
└── tests/
    ├── dhcp_test/         # DHCP 测试（含基础测试、租约测试、ARP 探测测试）
    ├── switching_test/    # 最短路径交换测试（三角形拓扑）
    └── firewall_test/     # 防火墙测试（3 主机 1 交换机）
```

### 各模块职责

| 文件 | 职责 |
|------|------|
| `controller.py` | 项目入口，作为 os-ken 应用运行。负责：监听 OpenFlow 事件（交换机上线/下线、链路增删、Packet-In）、构建全局拓扑图（交换机邻接矩阵 + 主机位置表）、运行 Dijkstra 最短路径算法、为每台交换机安装目的 MAC 转发流表、ARP 代理（代答 ARP 请求）、触发 DHCP 和防火墙功能 |
| `dhcp.py` | 完整的 DHCP 服务器实现。包含：DISCOVER→OFFER→REQUEST→ACK 四步握手、IP 地址池管理（192.168.1.2 ~ 192.168.1.100）、租约生命周期管理（分配/续约/过期回收）、RFC 2131 ARP 探测防冲突、DHCPRELEASE/DHCPDECLINE/DHCPNAK 处理、后台绿程定期扫描回收过期租约 |
| `firewall.py` | 防火墙规则引擎。从 `firewall_rules.json` 加载 deny 规则，转换为高优先级（priority=60000）OpenFlow 流表项，通过低层 OFPFlowMod 消息下发到交换机实现硬件级丢包 |
| `ofctl_utilis.py` | 封装了 OpenFlow 1.0/1.2/1.3 的流表操作，提供 `set_flow()`、`set_packetin_flow()` 等便捷方法 |

### 流表优先级体系

| 优先级 | 用途 |
|--------|------|
| 60000 | 防火墙 DROP 规则（最先匹配，直接丢弃） |
| 65000 | 自定义探针（ethertype=0x9999）→ 送控制器 |
| 10 | 转发规则（目的 MAC → 输出端口） |
| 0 | Table-miss（未匹配 → 送控制器） |

## 三、三大核心功能

### 3.1 DHCP 服务器

当主机加入网络时，自动分配 IP 地址。完整实现 RFC 2131 协议的以下流程：

```
主机                    交换机                    控制器
  |                        |                        |
  |-- DHCPDISCOVER ------>|-- Packet-In ---------->|
  |                        |                        |-- 选空闲 IP
  |                        |                        |-- ARP Probe（防冲突）
  |                        |                        |-- 构造 DHCPOFFER
  |<-- DHCPOFFER ---------|<-- Packet-Out ---------|
  |                        |                        |
  |-- DHCPREQUEST ------->|-- Packet-In ---------->|
  |                        |                        |-- 校验 IP 匹配
  |                        |                        |-- 构造 DHCPACK
  |<-- DHCPACK -----------|<-- Packet-Out ---------|
  |                        |                        |
  |        （租约到期后）     |                        |-- 后台回收器自动释放
```

**配置参数**（`dhcp.py:26-35`）：

| 参数 | 值 | 说明 |
|------|-----|------|
| `start_ip` / `end_ip` | 192.168.1.2 ~ 192.168.1.100 | IP 地址池 |
| `netmask` | 255.255.255.0 | 子网掩码 |
| `lease_time` | 60s | 租约时长（测试用） |
| `reaper_interval` | 30s | 过期回收扫描间隔 |
| `probe_timeout` | 2s | ARP 探测等待时间 |
| `conflict_ttl` | 300s | 冲突 IP 黑名单缓存时间 |

**租约状态机**：

```
DISCOVER → PROBING → OFFERED → ALLOCATED → RELEASED
                  ↘ CONFLICTED
```

### 3.2 最短路径交换

利用全局拓扑信息，为每对主机计算最短转发路径并下发流表。

**工作原理**：

1. **拓扑发现**：通过两条并行路径获取全局拓扑
   - os-ken 内置的 LLDP 链路发现（需要 `--observe-links` 启动参数），触发 `EventLinkAdd`/`EventLinkDelete`
   - 自定义探针（ethertype=0x9999）作为 LLDP 的补充，直接填充真实的端口号

2. **主机发现**：主机通过 gratuitous ARP（`arping`）向网络宣告自己的 MAC 和 IP 地址，控制器在 `packet_in_handler` 中 `EventHostAdd` 事件里记录主机位置

3. **路径计算**：对每台交换机运行 Dijkstra 算法（以跳数为权重），构建到所有目的交换机的下一跳表

4. **流表安装**：为每台已知主机的目的 MAC 地址，在路径上的每台交换机安装匹配-转发规则。直连交换机输出到主机端口，中转交换机输出到下一跳端口

5. **ARP 代理**：当主机发起 ARP 请求查询目标 MAC 时，交换机不广播而是上报控制器，控制器查表后返回 ARP 应答

**适用拓扑**：支持任意 L2 拓扑（含环路）。三角形测试拓扑为 h1-s1-s2-h2 和 h1-s1-s3-h3。

### 3.3 防火墙

通过预定义的 deny 规则在交换机层面实现数据包过滤。

**规则格式**（`firewall_rules.json`）：

```json
{
  "rules": [
    {
      "src_ip": "192.168.117.2",
      "dst_ip": "192.168.117.3",
      "proto": "icmp",
      "action": "deny"
    },
    {
      "src_ip": "192.168.117.2",
      "dst_ip": "192.168.117.3",
      "proto": "tcp",
      "dst_port": 80,
      "action": "deny"
    }
  ]
}
```

每条 deny 规则被转换为高优先级（60000）的 OFPFlowMod 消息，action 列表为空，匹配的数据包被交换机直接丢弃。支持字段：`src_ip`、`dst_ip`、`proto`（icmp/tcp/udp）、`src_port`、`dst_port`，`*` 或空值表示通配。

## 四、Bonus 功能

### Bonus 1：DHCP 租约时长

- 每次分配 IP 时记录 `expires_at` 时间戳
- DHCPOFFER/DHCPACK 携带 Option 51 (IP Address Lease Time)
- 后台绿程（`hub.spawn`）每 30 秒扫描并回收过期租约
- 支持 DHCPRELEASE 主动释放和 DHCPREQUEST 续约

### Bonus 2：RFC 2131 ARP 探测防冲突

- 分配 IP 前广播 ARP Request 探测目标 IP 是否已被占用
- 等待 2 秒，若收到 ARP Reply 则标记冲突并尝试下一个 IP
- 冲突 IP 加入黑名单（300 秒 TTL）
- 支持 DHCPDECLINE（主机主动拒绝）和 DHCPNAK（IP 不匹配拒绝）

## 五、技术栈

| 组件 | 版本/说明 |
|------|-----------|
| Python | 3.8（conda 环境 `cs305`） |
| os-ken | <4（OpenStack SDN 框架，Ryu 的维护分支） |
| Mininet | 2.3.0.dev6（轻量级网络仿真器） |
| OpenFlow | 1.0（13 个位置参数的 OFPMatch） |
| eventlet | 0.29.1（os-ken 的协程依赖） |
| 运行环境 | Linux 虚拟机（Mininet 需 root，内核命名空间支持） |
