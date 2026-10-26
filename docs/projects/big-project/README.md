# 大项目示例：双核心园区网

用一台出口路由器、两台核心交换机、四台接入交换机构成的双核心网络，覆盖本项目支持的绝大部分能力：

| 需求 | 用到的字段 |
| --- | --- |
| 两台核心做网关冗余、按 VLAN 分担流量 | `protocols.vrrp`（4 个组，优先级一主一备） |
| 二层防环 + 双实例负载分担 | `protocols.mstp`（instance 1 / 2，根桥优先级） |
| 核心与接入之间跑动态路由 | `protocols.ospf`（`auto_networks`） |
| 核心之间的链路聚合 | `link_aggregation`（LACP + trunk） |
| 部门网段隔离 | `departments` + `protocols.acl` |

## 目录

| 文件 | 说明 |
| --- | --- |
| `要求原文.md` | 用户给的自然语言需求，作为 AI 阶段的输入示例 |
| `groups.yaml` | 骨架：部门与设备归属，VLAN/网段由脚本推导 |
| `requirements.draft.yaml` | `--build-req` 展开出的草稿（演示脚本产物长什么样） |
| `requirements.yaml` | 人工补完协议后的最终要求，可直接生成命令 |

## 怎么跑

需要自己的 `.topo`：11 台设备（AR1、LSW1~LSW6、PC1~PC4），核心之间两根线。

```powershell
# 只看地址与网关表，先确认 VIP 和网段
python run.py 你的.topo --req docs/projects/big-project/requirements.yaml --address-table

# 出 Word
python run.py 你的.topo --req docs/projects/big-project/requirements.yaml --out output\大项目.docx

# 出逐设备 txt（自动按 40 行分段）
python scripts/export_configs.py 你的.topo docs/projects/big-project/requirements.yaml output\大项目
```

## 这个示例想说明的三件事

1. **ACL 只拦发起包**：`deny icmp icmp-type echo` + `deny tcp tcp-flag syn` + `permit ip`，财务部能出去、别人进不来；无状态 ACL 拦不了回程。
2. **交换机上要 `expand: true`**：同一个 ACL 编号不能挂多个 Vlanif（SACL 限制），展开后自动克隆成 3000/3001/3002。
3. **VLAN 10/20 主在 LSW1、30/40 主在 LSW2**：VRRP 与 MSTP 的根桥方向保持一致，避免主备角色打架。

## 已知前提

- 拓扑里的 PC 地址不在生成范围，按文档「终端建议地址」表在 eNSP 里手填。
- 核心之间的 Eth-Trunk 需要两根物理线；只有一根时聚合不成立。
