# CS305-2026Spring-Project

**重要提示**：我们尽力使本规范尽可能清晰，并涵盖我们在测试过程中遇到的所有问题。然而，规范中仍可能存在遗漏的重要细节。如有任何不清楚之处，您应立即联系QQ群中的讲师和助教王宇航，而不是自行猜测要求。

## 简介
**SDN**：软件定义网络（Software-Defined Networking，SDN）是一种新型网络范式。一个网络可以分为控制平面和数据平面。控制平面是一组协议和配置，用于设置转发相关设备（主机、交换机和路由器），使其能够正确转发数据包。这包括ARP解析、DNS、DHCP、生成树协议、NAT以及所有路由协议，其中许多内容在我们的CS305课程中都有涵盖。SDN最重要的特征是控制平面与数据平面的分离。通过将控制逻辑集中在一个集中式控制器中，控制器可以以**可编程**的方式控制和管理网络流量。相比之下，传统网络将控制逻辑分布在各个网络设备中。在本项目中，我们将编写一个集中式控制器。为了构建本地SDN开发环境，我们使用以下两个软件工具。

**Mininet**：Mininet 是一个广泛使用的网络仿真器，可以在Linux主机上创建任意的虚拟网络环境。出于教学或软件验证目的，开发人员通常使用 Mininet 构建虚拟网络拓扑。开发人员可以模拟包含虚拟主机、虚拟交换机和其他网络组件的网络，并测试他们的SDN控制器。

**os-ken**：os-ken 是一个用于构建SDN控制器的开源框架。在使用 Mininet 构建虚拟SDN网络之后，我们使用 os-ken 编写和部署SDN控制器。os-ken 控制器可以与 Mininet 中的虚拟交换机通信，以控制虚拟网络的行为。下图展示了 os-ken 和 Mininet 的整体架构。os-ken 监控交换机中的网络流量以采取相应的动作（如如何转发），而 Mininet 负责网络流量的实际传输。

<p align="center">
  <img src="./img/arch.png" width="60%"/>
</p>

在本项目中，我们将编写一个 os-ken 控制器来支持两个主要功能：

- 作为简单的DHCP服务器
- 实现最短路径交换算法

**注意：** 我们将使用 Mininet 构建不同的网络拓扑来测试您编写的 os-ken 控制器的正确性。因此，您需要确保您的代码在自定义网络拓扑下能够正常工作。

## 环境搭建
环境搭建包括两个主要步骤。第一，安装 Mininet；第二，安装我们提供的实验框架（包括 os-ken）。

### 安装 Mininet
Mininet 需要在Linux环境下运行。我们强烈建议在个人电脑上安装虚拟机，然后在虚拟机中安装 Mininet。
为了获得更便捷的开发体验，我们建议使用 VS Code 中的 Remote - SSH 扩展连接虚拟机进行远程开发。

#### Windows 及其他 amd64 用户配置指南
1. 安装 VMware 或 VirtualBox。
2. 下载带有 mininet 的官方 Ubuntu 镜像 [mininet-2.3.0-210211-ubuntu-20.04.1](https://github.com/mininet/mininet/releases/download/2.3.0/mininet-2.3.0-210211-ubuntu-20.04.1-legacy-server-amd64-ovf.zip)。
3. 下载镜像后，解压并双击 ovf 文件，自动调用 VMware 或其他虚拟机软件进行创建。
4. 使用用户名 `mininet` 和密码 `mininet` 登录虚拟机。

#### macOS ARM 用户配置指南
如果您使用 M1 或其他 Apple 芯片，请按以下方式配置：

1. 安装 VMware Fusion 或 Parallel Desktop。
2. 安装 Ubuntu 20.04.01 ARM 版本（与芯片架构一致，建议搜索 macOS m1 安装 Ubuntu Server 20.04）。
3. 配置并运行虚拟机。
4. 安装 Mininet。
```
sudo apt-get update
sudo apt-get install mininet
```
5. 安装 Python、Pip 和 git
```
sudo apt-get install python3 python3-pip git
```

#### 检查 Mininet 是否正确安装
在虚拟机中打开终端（命令行），输入以下命令检查 Mininet 是否配置正确。
```
sudo mn --test pingall
```
如果您看到类似以下的输出，说明 Mininet 环境配置正确。

<p align="center">
  <img src="./img/mininet_success1.png" width="50%"/>
</p>

**Mininet 必须以 root 身份运行。使用时请务必使用 sudo 或直接以 root 身份运行。**

#### 实验框架安装
由于 Ubuntu 默认的 Python 版本过高，我们需要使用 miniconda 安装 Python 3.8 环境。
如果您是 Windows 下的 AMD64 Ubuntu 用户，可以直接使用以下命令安装 miniconda。
```
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
sh Miniconda3-latest-Linux-x86_64.sh -b -p ${HOME}/software/miniconda3
echo "export PATH=${HOME}/software/miniconda3/bin:\$PATH" >> ~/.bashrc
source ~/.bashrc
conda init bash
source ~/.bashrc
conda create -n cs305 python=3.8
conda activate cs305
python --version
```

如果您是 macOS 下的 ARM Ubuntu 用户，可以直接使用以下命令安装 miniconda。
```
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh
sh Miniconda3-latest-Linux-aarch64.sh -b -p ${HOME}/software/miniconda3
echo "export PATH=${HOME}/software/miniconda3/bin:\$PATH" >> ~/.bashrc
source ~/.bashrc
conda init bash
source ~/.bashrc
conda create -n cs305 python=3.8
conda activate cs305
python --version
```
安装 Python 环境后，您需要安装本项目的实验框架。

项目仓库位于 Blackboard。下载仓库后，使用以下命令安装 Python 包依赖。

```
cd CS305-2026Spring-Project
sudo apt install -y build-essential python3-dev libxml2-dev libxslt1-dev zlib1g-dev pkg-config
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple 


# 检查 os-ken 是否安装成功
osken-manager --version
# 如果看到 osken-manager 的版本信息，说明安装成功。
```

**您需要检查虚拟机中是否安装了 `arping`。在 Ubuntu 终端中输入 `arping`。如果显示 "command not found"，则需要输入 `sudo apt-get install arping` 安装 arping。**

## 任务
本项目的基础部分包括三个方面：简单的DHCP服务器、最短路径交换算法的实现以及防火墙的实现。为了简化实验，我们对网络拓扑结构施加了以下限制。
- Mininet 仅包含二层交换机和主机。这意味着我们的网络是一个大的本地子网，无需考虑多子网场景。
- Mininet 中的每个主机仅连接到一个交换机。

### 简单的DHCP服务器
DHCP，即动态主机配置协议（Dynamic Host Configuration Protocol），主要用于为内部网络或网络服务提供商中的用户自动分配IP地址。

虽然 Mininet 默认自动为每个主机分配IP地址，但我们将在测试脚本中关闭 Mininet 的IP初始化功能。您可以参考DHCP协议标准 [RFC 2131](https://www.rfc-editor.org/rfc/rfc2131) 来实现一个功能丰富且完整的DHCP服务器。无论如何，您只需要做到：

- **当主机加入子网时，您设计的控制器能够识别DHCP数据包并为该主机分配一个有效的IP地址。**

在下一节中，我们将介绍如何完成此任务以及如何测试您是否成功实现了DHCP服务器。

### 最短路径交换
您的任务是建立一个全局最短路径交换表，并在交换机上安装转发规则来实现这些路径。您将基于控制器收集的全局拓扑信息在控制器上构建此表。**目的是实现任意两个主机之间的最短路径。**

与传统的二层交换机或三层路由器不同，SDN交换机没有专用的MAC学习表（MAC-learning）或路由表。相反，SDN交换机使用更通用的*流表*结构，它可以替代这些及其他结构。流表中的每个条目或规则包含一组匹配条件（基于以太网、IP、TCP、UDP等头部字段），用于选择特定的数据包，并为每个匹配规则包含一系列要执行的动作。

您的交换模块应匹配目标MAC地址，并基于匹配规则执行相应的动作，将数据包发送到正确的端口以到达其目的地。

**如果您不熟悉 action 和 flow table 等术语，请参考我们的课件、课程教材以及 os-ken 的文档和 Openflow 协议的相关资料。**

匹配规则的目的与传统路由表中的目标和掩码字段相同，而动作的目的与传统路由表中的接口字段相同，指示数据包应发送到何处。需要注意的是，您的拓扑不限于树形结构，因为您已经收集了所有交换机的信息，环路不应成为问题。实际上，您必须测试您的交换功能在具有环路的拓扑中是否有效。

为了计算最短路径，您应使用 Bellman-Ford 算法或 Dijkstra 算法来计算任意两个主机之间的最短路径。在确定从主机A到主机B的最短路径后，控制器必须将规则和相应的动作安装到路径中每个交换机的流表中。当拓扑发生变化时，您应更新受影响的路径规则。

## 实现与测试
在本节中，我们将结合实验框架代码介绍上述功能的实现思路，并告诉您如何测试它们。
### 实验框架
我们提供了一些基础的入门程序来帮助您开始本项目。项目结构如下。
```
├── controller.py  # 控制器主文件
├── dhcp.py   # 在此实现DHCP服务器
├── firewall.py # 在此实现防火墙
├── ofctl_utilis.py # 无需修改此文件，它提供了构建和发送数据包的实用函数
├── requirements.txt 
└── tests
    ├── dhcp_test
    │   └── test_network.py
    └── switching_test
    │   └── test_network.py
    └── firewall_test
        └── test_network.py
```

- `controller.py`：此文件是项目的入口点。您应实现对SDN网络中网络组件的监控、添加和删除、流经交换机的数据流，并基于收集的信息触发DHCP或最短路径交换功能。
- `dhcp.py`：DHCP的实现细节应在此文件中呈现。`controller.py` 调用 dhcp.py 中的相关函数来触发DHCP功能。
- `firewall.py`：实现防火墙模块，包括解析防火墙规则和生成流表项。`controller.py` 使用此模块将防火墙规则安装到交换机的流表中。
- `tests`：用于构建 mininet 网络以测试 DHCP、交换和防火墙功能的脚本。

### 实现简单DHCP
在SDN中实现简单DHCP包括以下步骤：
1. 当主机加入网络时，它广播一个 DHCP DISCOVER 数据包。
2. 控制器收到 DHCP DISCOVER 数据包后，选择一个空闲的IP并构造一个 DHCP OFFER 数据包发送回主机。
3. 主机收到 OFFER 数据包后，广播 DHCP REQUEST 信息以确认其选择的DHCP服务器配置。
4. 控制器收到 DHCP REQUEST 信息后，构造一个 DHCP ACK 数据包并发送回主机。

**第一步和第三步在测试脚本中实现，您应着重实现第二步和第四步。**

#### 接收DHCP协议数据包
在 `controller.py` 文件中，我们提供了接收DHCP协议数据包的相关代码。当数据包进入交换机时会调用此函数。这里的 `Datapath` 是接收数据包的交换机，`inPort` 是数据包进入的端口。如果此数据包可以被DHCP协议解析，我们调用 `DHCPServer.handle_dhcp` 函数来处理它。如果无法被DHCP解析，您应判断它是否是其他协议数据包，并针对不同协议做不同的处理。
```
@set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
def packet_in_handler(self, ev):
    try:
        msg = ev.msg
        datapath = msg.datapath # 交换机
        pkt = packet.Packet(data=msg.data)
        pkt_dhcp = pkt.get_protocols(dhcp.dhcp)
        inPort = msg.in_port
        if not pkt_dhcp:
            # TODO: 处理其他协议，如 ARP 
            pass
        else:
            DHCPServer.handle_dhcp(datapath, inPort, pkt)      
        return 
    except Exception as e:
        self.logger.error(e)
```

#### 构建DHCP协议数据包

您需要在 `dhcp.py` 的 `handle_dhcp` 函数中区分接收到的DHCP数据包类型。根据接收到的数据包类型，决定发送 DHCP OFFER 数据包还是 DHCP ACK 数据包。在选择合法IP地址时，您需要结合 `dhcp.py` 中 `Config` 类定义的 `start_ip`、`end_ip` 和 `netmask` 属性。这三个属性共同决定了子网的大小——即可分配的IP地址数量。详情请参见 `dhcp.py` 中的注释。

#### 测试DHCP功能

假设您位于项目的目录中，首先在一个终端中执行以下命令：

```
osken-manager --observe-links controller.py 
```

打开另一个终端，执行以下命令：

```
cd ./tests/dhcp_test/
sudo env "PATH=$PATH" python test_network.py # 与sudo用户共享PATH环境变量
```

我们在 `dhcp.py` 中设置了默认的IP分配范围。您可以通过命令 `h1 ifconfig` 和 `h2 ifconfig` 来检查两个主机是否已被分配IP地址。
只要分配的IP地址在 `192.168.1.2` 到 `192.168.1.99` 的范围内，我们就认为基本的DHCP功能已正确实现。

<p align="center">
  <img src="./img/dhcp_success1.png" width="50%"/>
</p>   

### 实现最短路径交换

我们可以利用SDN的集中式架构来实现无需广播的最短路径交换，如下所示：

#### 实现最短路径交换

- 当添加或移除交换机以及建立或断开交换机之间的链路时，网络拓扑将发生变化，这意味着最短路径也将改变。相应地，您应更新受影响交换机上的流表，以确保数据包始终沿交换机之间的最短路径传输。为了实现此功能，您可能需要创建一个抽象数据结构来计算交换机之间的距离。

- 通常情况下，当主机想要发送数据包时，它会查询其路由表以确定目标是否在同一子网中（在本项目中始终为真）。这意味着主机将以发往目标MAC地址的以太网帧的形式发送IP数据包（而不是发往网关或路由器的MAC地址）。如果主机不知道目标的MAC地址，它会发出一个ARP请求。

- 当交换机收到ARP请求时，它会将请求作为 PacketIn 消息发送给控制器，而不是广播它。
- 控制器将接收 PacketIn 消息并查找目标主机的MAC地址，然后生成一个响应（在 PacketOut 消息中），让交换机发送回源主机。
- 收到响应后，主机将IP数据包发送到目标的MAC地址。
- 在沿路径到达目的地的每个交换机处（由您的代码事先确定），数据包将匹配目标MAC地址并在正确的端口上被转发。

为了让控制器知道每个主机的MAC地址，我们必须建立一个协议，让主机在连接时将其地址告知控制器。对于本项目，我们要求主机在连接时发送一个未经请求的ARP回复（也称为"免费ARP"或 arping）来告知网络其MAC和IP地址——我们已经配置了 Mininet 在启动仿真网络时自动执行此操作。
最后，由于我们不广播ARP消息，所有ARP请求将被发送到控制器。当您收到ARP请求时，您应生成一个适当的响应，以便主机可以填充其ARP表。

#### 测试最短路径交换
我们在 `tests/switching_test/test_network.py` 中提供了一个测试网络。其网络拓扑如下。

<p align="center">
  <img src="./img/topo_example.png" width="50%"/>
</p>       

在 `test_network.py` 中，通过向网络添加主机、交换机和链路来构建一个三角形网络。您需要使用 OpenFlow 协议监控这些事件，并在控制器中执行相应的处理以实现最短路径交换。在所有组件（主机、交换机、链路）初始化之后，我们在每个主机上执行 `arping` 命令。您需要识别这些 `arping` 数据包并告知主机如何确定目标MAC地址。在此测试中，您可以使用 mininet CLI 中的 `pingall` 命令测试网络连通性。
在此网络中，从 h1 到 h2 的最短路径是 h1->s1->s2->h2，从 h1 到 h3 的最短路径是 h1->s1->s3->h3：任意两个主机之间的数据传输经过的交换机数量不应超过两个。

在项目目录中，首先在一个终端中执行以下命令：
```
osken-manager --observe-links controller.py
```
在另一个终端中，执行以下命令：
```
cd ./tests/switching_test/
sudo env "PATH=$PATH" python test_network.py # 与sudo用户共享PATH环境变量
```
大约两秒后，您会发现已在第二个终端中进入了 mininet CLI。
**您应在此处输入 `pingall` 命令来测试网络的连通性。** **为了方便检查您的代码，请在控制器中实现显示最短路径的功能。** 下图显示了显示最短路径的示例。在 `pingall` 命令之后，它会在第一个终端中显示任意两个主机之间的路径及其长度。这里距离为3，表示从 h1->s1->s3->h3 的路径长度为3（3条边）。

<p align="center">
  <img src="./img/path_result.png" width="50%"/>
</p>   

您将在第二个终端中看到下图所示的结果。这表明没有数据包丢失，网络是连通的。

<p align="center">
  <img src="./img/ping_result1.png" width="50%"/>
</p>   


### 实现防火墙

我们可以利用SDN的集中式架构来实现防火墙功能。控制器解析防火墙规则并将相应的流表项安装到交换机中，而不是在每个主机上过滤数据包。当数据包匹配防火墙规则时，交换机会根据安装的流表项直接丢弃该数据包。

#### 实现防火墙规则

- 防火墙规则定义在 `firewall_rules.json` 中。每条规则可以指定源IP地址、目标IP地址、传输协议、源端口、目标端口和动作。在本项目中，防火墙主要支持 `deny`（拒绝）规则。

- 当控制器启动时，`firewall.py` 从规则文件加载防火墙规则。如果规则文件不存在，防火墙模块使用一组默认规则。每条规则表示为一个 `FirewallRule` 对象，包含 `src_ip`、`dst_ip`、`proto`、`src_port`、`dst_port` 和 `action` 等字段。

- 防火墙模块在安装规则之前对规则字段进行规范化处理。例如，空值、`*` 和 `any` 被视为通配字段。协议名称如 `icmp`、`tcp` 和 `udp` 被转换为相应的IP协议号。

- 防火墙规则被安装为丢弃规则。具体来说，流表项根据指定的IP地址、协议和端口匹配数据包，并使用空动作列表。因此，当数据包匹配规则时，交换机会丢弃该数据包而不是转发它。通过这种方式，防火墙实现了阻止指定网络数据包的目的。

- 对于网络中的每个交换机，`controller.py` 调用防火墙模块来安装防火墙规则。防火墙模块将每条 `deny` 规则转换为高优先级的 OpenFlow 流表项，并将其安装到交换机的流表中。

在此实现中，防火墙通过 OpenFlow 流表项由交换机直接执行。控制器负责解析防火墙策略并安装相应的规则，而交换机在运行时执行数据包过滤。

#### 测试防火墙

`test_firewall.py` 脚本构建了一个简单的 Mininet 拓扑，包含三个主机和一个交换机：

```text
h1 ---\
h2 ---- s1
h3 ---/
```

为了专注于防火墙功能的实现，三个主机的IP地址在测试脚本中手动配置。此测试的目的是检查防火墙是否能够根据指定的规则阻止网络数据包。

该脚本在 h2 上启动两个HTTP服务器，一个在端口80上，另一个在端口8080上。然后执行四个测试：

h1 -> h2 ICMP：应失败，因为从 h1 到 h2 的 ICMP 流量被阻止。

h1 -> h3 ICMP：应通过，因为没有防火墙规则阻止此流量。

h1 -> h2 TCP/80：应失败，因为从 h1 到 h2 的 TCP 端口80流量被阻止。

h1 -> h2 TCP/8080：应通过，因为端口8080未被阻止。

要使用 `test_firewall.py`，首先需要在一个终端中执行以下命令：
```
osken-manager --observe-links controller.py
```
在另一个终端中，执行以下命令：
```
cd ./tests/firewall_test/
sudo env "PATH=$PATH" python test_network.py # 与sudo用户共享PATH环境变量
```

如果结果与下方预期的行为一致，说明防火墙模块工作正常。
<p align="center">
  <img src="./img/firewall_success.png" width="50%"/>
</p>   

## 评分与提交

您需要在第16周的实验课上演示您的项目。演示项目后，您需要提交：

- `report.pdf` —— 请清晰说明您项目的架构，并描述您所做内容的实现细节。如有需要，可添加截图或代码。您需要提供一个复杂的测试用例来展示您程序的健壮性。
- `src.zip` —— 一个名为 src 的目录，包含您的源代码。

以下是项目的暂定评分规则：

- 环境搭建：10 分
- DHCP：20 分
- 最短路径交换：40 分
- 防火墙：20 分
- 报告：10 分
- 加分项：最高 20 分

### 加分项（最高20分）

您可以实现以下某些功能来获得加分。我们将根据您实现功能的完整性、复杂性和难度来决定您的加分。

- 实现 DHCP 租约期限功能。
- 根据 RFC 协议设计 DHCP 功能，确保 DHCP 不会重复分配IP。
- 实现不同的路由算法。
- 使用 os-ken 实现更多功能，如 DNS 和 NAT。
- 使用 Mininet 研究您在计算机网络课程中学到的更多网络特性，如 TCP 行为、TCP Reno 与 TCP Tahoe 的比较以及[Bufferbloat](https://en.wikipedia.org/wiki/Bufferbloat) 问题。
- 您能想到的更多内容。请先与讲师讨论。

请注意，对于加分项，您需要在报告中详细说明您做了什么、如何测试额外功能以及您的发现。您还需要在第16周的演示中想出一种展示加分功能的方式。

## 提示

### 代码同步

您可以使用 Visual Studio Code Remote 扩展通过 SSH 在虚拟机中编写代码。

### 有用的 Mininet 命令
我们建议每次构建新的网络拓扑时重新启动控制器和 Mininet。您可能需要使用
```
sudo mn -c
```
来清理之前配置的网络。

以下是一些可能有用的命令：
```
MN> arping h1  # 从 h1 发送 arping，生成ARP请求，识别 h1 的MAC和IP地址。触发 EventHostAdd 事件
MN> arping_all # 从所有主机发送 arping。此命令将在测试脚本中自动运行。您也可以自己运行——如果您想在不重启 Mininet 的情况下重启控制器，这很有用。
MN> h1 ping h2 -c 1 # 从 h1 向 h2 发送一个 ping 包
MN> pingall # Ping 所有主机
MN> net # 查看当前网络拓扑
MN> dpctl dump-flows # 显示所有交换机的流表
```

### 如何添加转发规则

您可以阅读 `ofctl_utils.py` 中的代码以了解更多细节。
```
# 使用 ofctl_utils.py 提供的函数
from ofctl_utils import OfCtl, VLANID_NONE

def add_forwarding_rule(self, datapath, dl_dst, port):
    ofctl = OfCtl.factory(datapath, self.logger)
    actions = [datapath.ofproto_parser.OFPActionOutput(port)] 
    
    ofctl.set_flow(cookie=0, priority=0,
        dl_type=ether_types.ETH_TYPE_IP,
        dl_vlan=VLANID_NONE,
        dl_dst=dl_dst,
        actions=actions)
```

### 有用的文档
1. os-ken 的 API 文档 https://docs.openstack.org/os-ken/latest/
2. Mininet 的文档 https://github.com/mininet/mininet/wiki/Documentation
3. Mininet 源代码 https://github.com/mininet/mininet
4. Openflow 快速入门 https://homepages.dcc.ufmg.br/~mmvieira/cc/OpenFlow%20Tutorial%20-%20OpenFlow%20Wiki.htm

## 致谢
本项目基于威斯康星大学麦迪逊分校 Aditya Akella 教授为 CS640 计算机网络课程设计的作业以及布朗大学 Rodrigo Fonseca 教授为 CS168 计算机网络课程设计的作业修改而成。
