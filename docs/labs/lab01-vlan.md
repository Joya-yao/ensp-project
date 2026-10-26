# 实验一 VLAN 划分、Trunk 与 VLANIF 三层互通

**难度**：入门　**预计用时**：40 分钟（搭拓扑 15 + 配置 15 + 验证 10）
**覆盖**：VLAN 创建、Access 口、Trunk 口、VLANIF 网关、ARP 与 MAC 学习

---

## 一、实验目标

1. 用 VLAN 把同一台交换机上的端口做广播域隔离。
2. 用 Trunk 让同一个 VLAN 跨两台交换机延伸。
3. 用 VLANIF 做三层网关，让不同 VLAN 的 PC 互相 ping 通。
4. 会用 `display vlan`、`display port vlan`、`display mac-address` 判断「不通」卡在哪一层。

---

## 二、拓扑

```
PC1 --- GE0/0/1 ┐
                ├ LSW1 ═══ GE0/0/3 ── trunk ── GE0/0/3 ═══ LSW2 ┬ GE0/0/1 --- PC3
PC2 --- GE0/0/2 ┘                                              └ GE0/0/2 --- PC4
```

| 设备 | 型号 | 说明 |
| --- | --- | --- |
| LSW1 | S5700 | 三层交换机，VLANIF 网关在这台 |
| LSW2 | S5700 | 纯二层 |
| PC1 / PC2 | PC | 挂在 LSW1 |
| PC3 / PC4 | PC | 挂在 LSW2 |

连线表：

| 本端 | 对端 | 线缆 |
| --- | --- | --- |
| LSW1 GE0/0/1 | PC1 Ethernet0/0/1 | Copper |
| LSW1 GE0/0/2 | PC2 Ethernet0/0/1 | Copper |
| LSW1 GE0/0/3 | LSW2 GE0/0/3 | Copper |
| LSW2 GE0/0/1 | PC3 Ethernet0/0/1 | Copper |
| LSW2 GE0/0/2 | PC4 Ethernet0/0/1 | Copper |

---

## 三、地址规划

| VLAN | 名称 | 端口 | 网段 | 网关 |
| --- | --- | --- | --- | --- |
| 10 | student | LSW1 GE0/0/1、LSW2 GE0/0/1 | 10.10.0.0/24 | 10.10.0.254 |
| 20 | teacher | LSW1 GE0/0/2、LSW2 GE0/0/2 | 10.20.0.0/24 | 10.20.0.254 |

PC 地址（eNSP 里双击 PC → IPv4 Configuration 手填，不配网关则跨 VLAN 不通）：

| PC | IP | 掩码 | 网关 | 所属 VLAN |
| --- | --- | --- | --- | --- |
| PC1 | 10.10.0.1 | 255.255.255.0 | 10.10.0.254 | 10 |
| PC2 | 10.20.0.1 | 255.255.255.0 | 10.20.0.254 | 20 |
| PC3 | 10.10.0.2 | 255.255.255.0 | 10.10.0.254 | 10 |
| PC4 | 10.20.0.2 | 255.255.255.0 | 10.20.0.254 | 20 |

---

## 四、实验步骤

### 步骤 1：搭拓扑、配 PC

按上面连线表连线，逐台 PC 填 IP/掩码/网关。先不配交换机，此时四台 PC 应该全都不通——记录这个基线。

### 步骤 2：LSW1 建 VLAN、划 Access 口

进系统视图，创建 VLAN 10 和 20，把 GE0/0/1 划进 VLAN 10、GE0/0/2 划进 VLAN 20（`port link-type access` + `port default vlan`）。

**此时验证**：`display vlan` 能看到 10/20 及各自端口；PC1 与 PC2 仍不通（不同广播域），PC1 ping 自己的网关 10.10.0.254 也不通（还没配 VLANIF）。

### 步骤 3：LSW1 配 Trunk 口

GE0/0/3 设为 `port link-type trunk`，`port trunk allow-pass vlan 10 20`。

**注意**：eNSP 里 trunk 默认只放行 VLAN 1，不 `allow-pass` 的 VLAN 直接丢弃，这是后面不通的最常见原因。

### 步骤 4：LSW2 建 VLAN、划口、配 Trunk

LSW2 上重复：建 VLAN 10/20，GE0/0/1 → VLAN 10，GE0/0/2 → VLAN 20，GE0/0/3 配 trunk 放行 10 20。

**此时验证**：`display mac-address` 在 LSW1 上应能学到 PC3 的 MAC 且 VLAN 标为 10。学到 MAC 说明二层通了。

### 步骤 5：LSW1 配 VLANIF 网关

创建 Vlanif10 配 10.10.0.254/24，Vlanif20 配 10.20.0.254/24。

**此时验证**：

```
PC1> ping 10.20.0.1     # 跨 VLAN，应通
PC1> ping 10.10.0.2     # 跨交换机同 VLAN，应通
```

---

## 五、验收清单

| # | 检查项 | 命令 | 期望 |
| --- | --- | --- | --- |
| 1 | VLAN 存在且端口正确 | LSW1/LSW2 `display vlan` | 10/20 均 UT 标出对应 access 口，GE0/0/3 为 TG |
| 2 | 端口类型 | `display port vlan` | GE0/0/1 access PVID 10，GE0/0/3 trunk PVID 1 |
| 3 | MAC 表跨交换机 | LSW1 `display mac-address` | 有 PC3/PC4 的 MAC，VLAN 分别 10/20 |
| 4 | 网关可达 | PC1 `ping 10.10.0.254` | 通 |
| 5 | 跨 VLAN 互通 | PC1 `ping 10.20.0.1` | 通 |
| 6 | 广播隔离 | PC2 `ping 10.10.0.1` 前先 `arp -d` | 通（经网关），但 ARP 广播出不了 VLAN |
| 7 | 接口状态 | `display interface brief` | 用到的口 UP，无 CRC 错包 |

---

## 六、常见故障对照

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 同交换机同 VLAN 不通 | access 口 PVID 配错，或 VLAN 没建 | `display port vlan`、`display vlan` |
| 跨交换机同 VLAN 不通 | Trunk 没放行该 VLAN | 两端 `display port vlan` 看 trunk VLAN 列表 |
| 同 VLAN 通、跨 VLAN 不通 | 缺 VLANIF 或 PC 没配网关 | `display ip interface brief` |
| ping 网关通、ping 远端 PC 不通 | 远端 PC 网关没配 | 查 PC 配置 |
| 一直 ARP 解析失败 | 两端 PVID 不一致，帧被丢 | 对比两端 trunk PVID |

---

## 七、思考题

1. Trunk 口的 PVID 默认是 1，如果两端 PVID 都改成 10，会有什么变化？
2. `port trunk allow-pass vlan all` 有什么风险？
3. 不配 VLANIF，只用路由器单臂路由（子接口）能不能实现同样效果？区别在哪？
4. 同一 VLAN 内 PC1 ping PC3，中间经过的交换机做了什么转发决策？

---

## 八、对答案

拓扑保存为 `lab01.topo` 后：

```powershell
.\.venv\Scripts\python.exe run.py lab01.topo --req lab01-vlan.yaml
.\.venv\Scripts\python.exe run.py lab01.topo --req lab01-vlan.yaml --out lab01-答案.docx
```

先在 eNSP 里手动配完再看，否则学不到排查过程。
