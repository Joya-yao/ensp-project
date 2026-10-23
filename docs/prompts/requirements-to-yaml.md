# 把实验要求变成 requirements.yaml

给 AI 的提示词模板。用法：把老师的要求原文贴在「要求原文」后，让模型按这个格式输出 YAML；拿到后先跑 `labgen --validate --req`，再人工核对。

---

## 提示词

你是网络实验配置助手。把下面这段实验要求，转成项目约定的 YAML。

规则：

1. 只输出 YAML，不要解释，不要 Markdown 代码块围栏。
2. 严格使用下面的字段，不新造字段。字段含义与取值见「字段表」。
3. 要求里没提到的东西不要猜。缺什么就在 YAML 后面用 `# TODO:` 注释标出来，不要编造 IP 或 VLAN。
4. IP 一律 CIDR 写法（`10.0.1.1/24`），不要写掩码点分十进制。
5. 设备名照抄原文（R1/AR1/LSW1 等）；接口名用 VRP 写法（`GigabitEthernet0/0/0`），原文只说「1 号口」时写成 `GigabitEthernet0/0/1` 并在注释里标记待确认。
6. VLAN 必须先在该设备的 `vlans` 里定义，接口只能引用已定义的 VLAN。
7. 拿不准的字段宁可不写，也不要填错。

### 字段表

```yaml
experiment:
  name: 实验名
  notes: 备注（可省略）

devices:
  <设备名>:
    role: router | switch
    vlans:                       # 交换机用
      - {id: 10, name: student}
    interfaces:
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
```

### 要求原文

```
<把老师的要求粘贴到这里>
```

---

## 转换后怎么核对

1. 跑校验，字段写错会直接报错并指出位置：
```
.\.venv\Scripts\python.exe run.py --validate --req 你的.yaml
```
2. 看输出的设备数、接口数、协议列表，和原文对一遍。
3. 再跑一次生成，检查 Word 里的命令：
```
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --req 你的.yaml --out output\配置.docx
```

## 已知的坑

- 原文说「PC 接在交换机 1 号口」，这里只描述交换机侧；PC 的 IP 不归本工具生成。
- 原文只给网段没给具体 IP 时，模型容易自己分配主机地址。要求它留 `# TODO:`，人工补。
- 双机热备类题目常同时要求 VRRP 和 OSPF，注意 VRRP 的虚拟 IP 不能和接口 IP 相同。
