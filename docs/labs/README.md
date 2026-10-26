# eNSP 实验指导书

配套本项目使用：指导书给拓扑 + 地址规划 + 步骤，`.topo` 自己搭，`requirements.yaml` 交给 `run.py` 出答案命令。

## 通用约定

| 项 | 约定 |
| --- | --- |
| 设备命名 | 路由器 `AR1/AR2`，交换机 `LSW1/LSW2`，终端 `PC1/PC2` |
| 网段 | `10.<VLAN号>.0.0/24`，网关固定 `.254`（与 `--build-req` 的展开规则一致） |
| 互联地址 | `10.0.<链路号>.0/24`，两端 `.1` / `.2` |
| 保存 | eNSP 里 `File → Save As`，文件名 `labNN.topo` |
| 命令文档 | `python run.py labNN.topo --req labNN.yaml --out labNN-答案.docx` |

## 实验清单

| 编号 | 主题 | 覆盖协议 | 指导书 | 要求文件 |
| --- | --- | --- | --- | --- |
| 01 | VLAN 划分、Trunk、VLANIF 三层互通 | 802.1Q / VLANIF | [lab01-vlan.md](lab01-vlan.md) | `lab01-vlan.yaml` |
| 02 | 单区域 OSPF | OSPF | 待写 | — |
| 03 | DHCP 全局地址池 | DHCP | 待写 | — |
| 04 | VRRP 网关冗余 | VRRP | 待写 | — |
| 05 | MSTP + Eth-Trunk | MSTP / LAG | 待写 | — |
| 06 | ACL 访问控制 | ACL | 待写 | — |
| 07 | 综合实验 | 全部 | 待写 | — |

## 怎么用

1. 读指导书，按拓扑在 eNSP 连好线，保存成 `.topo` 放进本目录。
2. 先自己做一遍，卡住再看答案。
3. 对答案：`python run.py labNN.topo --req labNN.yaml`，只打印命令；加 `--out` 出 Word。
4. 想加设备/改网段，直接改 `labNN.yaml`，不用改代码。
