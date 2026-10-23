# REQUIREMENTS — eNSP 配置生成器

## 1. 一句话目标

用户给出「已连好线的 eNSP 工程文件」和「实验要求（Word）」，工具输出一份 Word：按设备分节，每节是可直接粘进设备的 VRP 配置命令。

## 2. 用户流程

1. 在 eNSP 里连好拓扑，保存工程（`.topo`）。
2. 把老师给的实验要求整理成 Word 文档（协议、VLAN、IP 规划等）。
3. 运行工具：`labgen --topo lab.topo --req requirements.yaml --out 配置文档.docx`
4. 打开 Word，按「R1」「R2」分节，逐段复制到设备命令行。

## 3. 输入

| 输入 | 格式 | 说明 |
| --- | --- | --- |
| 拓扑 | `.topo`（XML） | eNSP 保存的工程文件，含设备与连线 |
| 要求 | `requirements.yaml` | 结构化配置意图（本文件第 6 节定义） |
| 要求原文 | `.docx` | 老师给的实验要求，供 AI 转换成 YAML，不参与运行 |

## 4. 输出

一份 `.docx`：

```
实验配置文档
├── 拓扑概览（设备数、连接关系表）
├── R1
│   ├── 设备角色 / 接口清单
│   └── 配置命令（代码块，可整段复制）
├── R2
└── ...
```

每节标题写明设备名，命令用等宽字体块，保证复制后不丢缩进。

## 5. 功能需求（模块）

### M1 拓扑解析（确定性，无 AI）

- 读 `.topo` XML，输出：
  - 设备列表：设备名、型号、设备类型（router / switch / pc / server）
  - 每台设备的接口列表：接口名、所属槽位、是否已连线
  - 连接关系：`(设备A, 接口A) <-> (设备B, 接口B)`，含线缆类型
- 输出为内部数据类 `Topology`，可被后续模块消费，也可单独 dump 成 JSON 供调试。
- 不做任何推断：文件里没有的信息就是没有。

### M2 结构化要求（YAML schema）

见第 6 节。原则：写「人的意图」，不写命令。
例：`vlan: {id: 10, name: student}`，而不是 `vlan 10` / `description student`。

### M3 配置生成（确定性）

- 输入：`Topology` + `Requirements`
- 输出：`dict[设备名, list[命令]]`
- 每一类配置一个生成器（Python 函数），互不依赖，按设备聚合。
- 首版只做两类：**接口 IP**、**OSPF**。其余留接口占位。

### M4 AI 转换入口（离线步骤，不进运行时）

- 运行时**不调用 AI**，只读 YAML。这样结果可复现、可测试。
- AI 负责把 Word 原文转成 YAML；输出允许人工修正。
- 交付物里提供一个 prompt 模板 + 一份示例（输入片段 → 输出 YAML）。

### M5 文档输出

- 用 `python-docx` 生成。
- 结构见第 4 节。
- 命令块用 Consolas、保留缩进、禁止自动换行破坏命令。

## 6. YAML schema（v0.1 草案）

```yaml
experiment:
  name: "实验三 单区域 OSPF"
  notes: "可选备注"

devices:
  R1:
    role: router
    interfaces:
      - name: GigabitEthernet0/0/0
        ip: 10.0.1.1/24
        description: to-R2
      - name: GigabitEthernet0/0/1
        ip: 10.0.2.1/24

  SW1:
    role: switch
    vlans:
      - {id: 10, name: student}
      - {id: 20, name: teacher}
    interfaces:
      - name: GigabitEthernet0/0/1
        mode: trunk
        allow_vlans: [10, 20]
      - name: GigabitEthernet0/0/2
        mode: access
        vlan: 10

protocols:
  ospf:
    process: 1
    router_id: 1.1.1.1          # 可省略，省略时自动取最大 loopback / 接口 IP
    areas:
      - area: 0
        networks: ["10.0.1.0/24", "10.0.2.0/24"]
    # 简化写法：只给 area，网络从接口 IP 自动推导
    auto_networks: true

  # 预留，v0.2 起支持
  mstp: {}
  vrrp: {}
  dhcp: {}
```

字段设计约束：

- VLAN、接口都用 `id`/`name` 语义字段，不用命令名。
- IP 一律 CIDR 写法，解析后拆成地址 + 掩码。
- 协议块可选；不写就不生成对应命令。
- Access 口必须给 `vlan`，Trunk 口必须给 `allow_vlans`；引用的 VLAN 必须先在设备的 `vlans` 里定义，否则直接报错并列出已定义 VLAN。
- 已实现：接口 IP、接口描述、VLAN、Access/Trunk、MSTP（域/实例/优先级/边缘端口）、VRRP（虚拟 IP/优先级/抢占）、OSPF 单区域。DHCP 仍是占位。

## 7. 验收标准

1. 给一个 3 设备拓扑，解析结果设备数、连线数与 eNSP 界面一致。
2. 同一输入跑两次，输出命令逐字节相同（确定性）。
3. 生成的接口 IP / OSPF 命令粘到 eNSP 设备上不报错，邻居能建立。
4. Word 中每台设备的命令可整段复制，缩进不丢。
5. 单元测试覆盖：拓扑解析、IP 格式化、OSPF 网络推导、文档分节。`pytest` 全绿。

## 8. 非目标（首版不做）

- 不做配置下发（不连设备执行命令）。
- 不解析 eNSP 的 `.zip` 工程包，只认 `.topo`。
- 不做配置校验/回滚。
- 不生成运维脚本、不做多厂商（华为 VRP 之外）。

## 9. 待定问题

1. `.topo` 的真实 XML 结构：需要一份用户实际保存的工程文件来定字段名。
2. Word 要求文档是否要程序直接读：当前方案是 AI 先转 YAML，程序只读 YAML。若必须直读 docx，需要额外解析 + 规则引擎。
3. 设备型号差异：不同型号接口命名/可用命令可能不同，首版假定都是 AR 系列路由器 + S5700 交换机。
