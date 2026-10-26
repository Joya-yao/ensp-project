# 把 PDF / Word 实验要求变成配置：先出地址表，确认后再生成

老师的很多要求是 PDF 或 Word，地址、网关、VLAN 散在正文和表格里。直接从原文生成命令风险高：网关错一个数，整套命令白配。

所以分两步走：

1. **阶段一**：AI 只读原文，输出「每台设备的 IP 与网关表」，不写 YAML，不写命令。
2. **人工确认**：对着原文核对这张表，错的直接改。
3. **阶段二**：把改好的表交给 AI，转成 `requirements.yaml`，再生成命令。

```text
PDF / Word 要求 ──阶段一──→ 地址与网关表 ──人工改──→ 阶段二 ──→ requirements.yaml ──→ 命令
```

---

## 阶段一提示词：只出地址表

把下面整段连同原文一起发给模型。**明确禁止它输出 YAML 和命令**，否则它会一步做到底，你就失去了检查机会。

````text
你是网络实验配置助手。我给你一份 PDF/Word 实验要求（可能有 OCR 错误、表格错位）。

现在只做一件事：提取每台设备的接口地址和网关，输出 Markdown 表格。不要输出 YAML，不要输出配置命令。

输出三张表：

表 1 网段与网关
| 网段 | 掩码 | 网关 | 网关在哪台设备 | 原文依据 |

表 2 每台设备的地址
| 设备 | 接口 | IP | 掩码 | VLAN | 网关 | 说明 |

表 3 终端地址
| 终端 | 接在哪 | VLAN | IP | 掩码 | 网关 |

规则：
1. 只写原文能推出来的值。原文没写、也推不出的，写 `?` 并在最后一节「待确认」里列出来，绝对不要自己编一个地址。
2. 网关优先按原文写；原文只说「用三层交换机做网关」没给具体地址时，写 `?`，不要默认 .254。
3. IP 一律 CIDR 与点分掩码都给出（IP 列写 `10.10.0.254`，掩码列写 `255.255.255.0`）。
4. 接口名用 VRP 写法：`GigabitEthernet0/0/1`、`Vlanif10`、`Eth-Trunk1`。原文只写「1 号口」就写 `GigabitEthernet0/0/1`，并在「待确认」里注明。
5. 表 3 的终端可以是空表：原文没给 PC 地址就留空，别造。
6. 表格后面加两节：
   - 「待确认」：逐条列出你拿不准的地方和原文出处
   - 「我推断的」：列出你按惯例补的值（比如按 .254 当网关），每条注明依据

原文：
<把 PDF/Word 里复制出来的要求贴这里。表格建议按行粘贴，别只贴图片。>
````

### 表格长什么样

阶段一输出的样子（示例，未确认前别直接用）：

| 网段 | 掩码 | 网关 | 网关在哪台设备 | 原文依据 |
| --- | --- | --- | --- | --- |
| 10.10.0.0 | 255.255.255.0 | 10.10.0.254 | LSW1 Vlanif10 | 原文 3.2 节「学生网段网关 .254」 |
| 10.20.0.0 | 255.255.255.0 | ? | ? | 原文只说「教师网段独立」，未给网关 |

| 设备 | 接口 | IP | 掩码 | VLAN | 网关 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| LSW1 | Vlanif10 | 10.10.0.254 | 255.255.255.0 | 10 | 本机 | 学生网段网关 |
| LSW1 | GigabitEthernet0/0/1 | — | — | 10 | — | 接 PC1 |

看到 `?` 就去原文找，找不到就问老师，别猜。

---

## 人工确认这一步怎么查

1. **网关和 VLAN 对得上**：每个 VLAN 只有一个网关；VRRP 场景下网关是虚拟 IP，不是某台设备的接口 IP。
2. **互联链路不该有网关**：两台路由器之间的 `10.0.1.0/24`，网关列应该是「—」。
3. **地址不重复**：同一网段里没有两个相同 IP。
4. **终端网关指向本 VLAN 的网关**，不是别的 VLAN。

---

## 阶段二提示词：表转 YAML

确认无误后，把「表 1 + 表 2 + 阶段一的待确认结论」贴进去，用这段：

````text
下面是我确认过的地址与网关表，请转成 requirements.yaml。

规则：
1. 只输出 YAML，不要解释，不要代码块围栏。
2. 严格使用「字段表」里的字段，不新造字段。
3. 表里每个 IP 都要落到对应设备的 interfaces；VLAN 必须先在设备的 vlans 里定义。
4. 网关是 Vlanif 就写成 `Vlanif<vlan号>` 接口；是 VRRP 虚拟 IP 就写进 protocols.vrrp，并在组里列出参与设备与优先级。
5. 表里标 `?` 的项一律不写，改用 `# TODO:` 注释标出来。
6. IP 用 CIDR 写法。
7. 我确认过的值不许改，包括大小写和描述文字。

字段表：
<把下面「字段表」整段贴进来>

我确认过的表：
<贴阶段一的三张表 + 待确认结论>
````

### 字段表

```yaml
experiment:
  name: 实验名
  notes: 备注（可省略）

departments:                     # ACL 里引用的部门/区域
  finance:
    name: 财务部
    subnet: 10.0.20.0/24

devices:
  <设备名>:
    role: router | switch
    department: 财务部            # 只进文档标题，不进命令
    layer: core | aggregation | access   # 只进文档
    vlans:                       # 交换机用
      - {id: 10, name: student}
    link_aggregation:            # 链路聚合（可选）
      - id: 1
        mode: lacp               # lacp | manual
        port_mode: trunk         # access | trunk
        allow_vlans: [10, 20]
        members: [GigabitEthernet0/0/3, GigabitEthernet0/0/4]
    interfaces:
      - name: Vlanif10           # 三层网关，需先定义 VLAN 10
        ip: 10.10.0.254/24
      - name: GigabitEthernet0/0/0
        ip: 10.0.1.1/24          # 三层接口才写
        description: to-R2
        mode: access | trunk     # 二层口才写
        vlan: 10                 # access 必填
        allow_vlans: [10, 20]    # trunk 必填
        edged_port: true         # 接终端的口可写

protocols:
  ospf:
    process: 1
    router_id: 1.1.1.1           # 可省略
    areas:
      - {area: 0}                # 只给 area，网段从接口 IP 推导
    auto_networks: true

  mstp:
    region: {name: RG-1, revision: 1}
    instances:
      - {instance: 1, vlans: [10]}
    devices:
      LSW1: {priorities: {1: 4096}}

  vrrp:
    groups:
      - vrid: 1
        interface: GigabitEthernet0/0/0
        virtual_ip: 10.0.1.254
        preempt_delay: 20
        devices:
          AR1: {priority: 120}
          AR2: {priority: 100}

  dhcp:
    pools:
      - {name: vlan10, network: 10.0.1.0/24, gateway: 10.0.1.1, dns: [114.114.114.114], lease_days: 1}
    devices:
      AR1: {pools: [vlan10], interfaces: [GigabitEthernet0/0/0]}

  acl:                            # 部门间访问控制
    - name: finance-guard
      device: AR1                 # 在哪台设备上配
      acl_number: 3000            # 可省略，默认 3000、3001…
      apply:                      # 二选一：单接口 interface，或一次挂多个 interfaces
        interfaces: [Vlanif10, Vlanif20, Vlanif40]
        direction: inbound        # inbound | outbound
      rules:
        - {action: permit, source: finance, destination: server}
        - {action: deny, protocol: icmp, icmp_type: echo, destination: finance}
        - {action: deny, protocol: tcp, tcp_flag: syn, destination: finance}
        - {action: permit, source: any, destination: any}
```

### ACL 只拦「发起包」，一条能做完就别写两条

无状态 ACL 分不清谁先发起，所以「别人进不来、财务出得去」不能去拦回程包，只能拦发起包：

| 目标 | 规则 |
| --- | --- |
| 别人 ping 不到财务 | `deny icmp icmp_type: echo destination: finance`（生成时转成 `icmp-type 8 0`，避免不同版本不认名字） |
| 别人连不上财务的 TCP 服务 | `deny tcp tcp_flag: syn destination: finance` |
| 财务能访问别人（回程放行） | 收尾 `permit ip`，echo-reply / ack 自然通过 |
| 双向都要挡、要会话状态 | 无状态 ACL 做不到，写 `# TODO:` 注明要防火墙 |

`apply.interfaces` 让一条 ACL 同时挂到多个 VLANIF，别按接口复制 ACL 编号。每台核心设备一条即可，不要让 ACL 条数随接口数增长。

**交换机上必须加 `expand: true`**：S5700 的 Vlanif 用的是 SACL，同一个 ACL 编号挂第二个 Vlanif 会报 `Sacl doesn't support config the same acl or rule repeatedly`。写了 `expand: true` 后，一条规则集会自动克隆成 3000/3001/3002 三条、每条挂一个接口，规则完全一样，YAML 里仍然只写一遍。

---

## 拿到 YAML 之后

1. 校验字段：
```
.\.venv\Scripts\python.exe run.py --validate --req 你的.yaml
```

2. **回读地址表**，和阶段一那张表逐行对比。AI 转 YAML 时最容易丢网关和改掩码：
```
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --req 你的.yaml --address-table
```
只输出 Markdown 表格，不生成命令。表对了再往下走。

3. 生成 Word 和逐设备 txt：
```
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --req 你的.yaml --out output\配置.docx
.\.venv\Scripts\python.exe scripts\export_configs.py 你的拓扑.topo 你的.yaml output\导出
```

## 已知的坑

- **PDF 转文字掉表格**：行列错位是常态，阶段一的「待确认」比表格本身更值钱。
- **原文只给网段没给 IP**：模型爱自己分配主机地址，所以规则 1 要求写 `?`。
- **VRRP 虚拟 IP 和接口 IP 撞车**：虚拟 IP 不能等于任何接口地址，确认时查一遍。
- **PC 地址不归本工具生成**：文档会给建议地址，实际配置在 eNSP 里手填。
- **AI 一次做到底**：它常忽略「不要输出 YAML」，真出现了就重发，只贴表 1 和表 2 让它接着做。
- **中文写进命令**：`description`、`vlan name` 用中文，eNSP 控制台可能乱码，粘到一半断在子视图里。这些字段只写 ASCII，中文留给 `department`、`experiment.name`。
- **txt 带 BOM**：带 BOM 的文件第一行会变成 `\ufeffsystem-view`，命令报错后一直停在用户视图，后面全失败。`export_configs.py` 默认写无 BOM 的 utf-8；控制台吃 GBK 时加 `--encoding gbk`。
