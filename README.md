# eNSP 配置生成器

[![CI](https://github.com/Joya-yao/ensp-project/actions/workflows/ci.yml/badge.svg)](https://github.com/Joya-yao/ensp-project/actions/workflows/ci.yml)

读 eNSP 工程文件和结构化的实验要求，输出每台设备可整段粘贴的 VRP 配置命令（Word 文档）。

不用手写命令，也不用一个个设备点开抄。拓扑解析是确定性的：同一个输入，两次生成的命令逐字节相同。

## 效果

先校验要求文件，字段错了当场报出来：

```text
$ python run.py --validate --req docs/labs/lab01-vlan.yaml
要求文件：lab01-vlan.yaml
实验：实验一 VLAN 划分、Trunk 与 VLANIF 三层互通
设备 2 台：LSW1、LSW2
接口 8 个，VLAN 4 个
协议：接口 IP、VLAN
校验通过。
```

再生成命令，每台设备一段，整段复制即可（节选）：

```text
$ python run.py lab01.topo --req lab01-vlan.yaml
===== LSW1 =====
system-view
sysname LSW1
vlan 10
 name student
return
system-view
interface GigabitEthernet0/0/1
 description to-PC1
 port link-type access
 port default vlan 10
return
system-view
interface Vlanif10
 description gateway-student
 ip address 10.10.0.254 255.255.255.0
return
...
```

每个块用 `return` + `system-view` 收尾，粘贴中断也不会掉进用户视图；`--out` 出 Word，`scripts/export_configs.py` 出逐设备 txt。

## 它解决什么问题

实验课上老师给一份要求，拓扑自己在 eNSP 里连好了，但每台设备该配什么命令要一个一个想。这个工具把「拓扑 + 要求」直接变成「每台设备一节命令」，复制粘贴就能用。

```
lab.topo  ─┐
           ├─→ 命令生成 ─→ 配置文档.docx（AR1 / AR2 / LSW1 各一节）
要求.yaml ─┘
```

## 设计原则

这个项目面向所有用 eNSP 做实验/课程设计的人，不是某一个人的脚本。改代码前先过一遍这四条：

1. **生成是确定性的**：同一份拓扑和要求，两次输出逐字节相同。不引入随机、时间戳、隐式网络请求；AI 只出现在「要求原文 → YAML」这一步，且完全可选。
2. **不猜**：原文没给的值不编，网关推不出来就写 `—` 或 `?`，让用户确认。错的配置比没有配置更浪费时间。
3. **粘贴即用**：产出的命令要能整段粘进 eNSP 跑通——无 BOM、不重复换行、按行数分段、顶层用 `return` + `system-view` 收尾、命令里不出现中文。
4. **通用优先**：不为一台设备的残留状态或某个实验的特殊情况打补丁。临时需求走命令行参数或 YAML 字段，默认值服务大多数场景，并且带测试。

## 桌面界面

不想敲命令时用本地网页界面，纯 Python 起服务，不装 Node、不打包：

```powershell
.\.venv\Scripts\python.exe run.py --ui
```

浏览器自动打开 `http://127.0.0.1:8765/?t=…`，页面上能做这些事：

| 区块 | 能做什么 |
| --- | --- |
| 拓扑文件 | 选文件即自动上传到中间目录并填入路径；也可以直接填已有路径 |
| 要求 YAML | 在浏览器里直接编辑，一键保存到中间目录；点中间目录里的文件可以载入继续改 |
| 地址表 | 点「地址表」就生成并写盘，页面显示完整路径；文本框里可以改，再点「保存地址表」 |
| 目录设置 | 中间文件（上传的 .topo、草稿 YAML、地址表）与最终产物（docx、分段 txt）分开指定，都限 `output/` 下 |
| AI 转换（可折叠） | 选本地或云端、填 base_url / model / key，贴要求原文，出 YAML 或只出地址表 |
| 结果与产物 | 每次操作都列出写出的文件：文件名 + 完整路径 + 大小，可点下载 |

想要独立窗口而不是浏览器标签页：

```powershell
.\.venv\Scripts\python.exe -m pip install pywebview
.\.venv\Scripts\python.exe run.py --ui --window
```

没装 pywebview 时会自动退回浏览器，功能一样。

安全边界：服务只监听 `127.0.0.1`，每次启动生成一次性 token；读取限制在项目目录内，写入和下载限制在项目的 `output/` 下。

## 支持范围

| 类别 | 已支持 |
| --- | --- |
| 二层 | VLAN、Access/Trunk、Vlanif 网关、Eth-Trunk（LACP/手工）、MSTP（域/实例/优先级/边缘口） |
| 三层与高可用 | 接口 IP、VRRP、OSPF（自动或手工宣告）、RIP v1/v2、BGP（邻居 + network） |
| 策略与出口 | 高级 ACL（五元组、icmp-type、tcp-flag）、前缀列表、路由策略、Easy IP 出方向 NAT |
| 其它 | DHCP 全局地址池、地址与网关表、终端建议地址、Word / 分段 txt 输出 |

暂不支持：OSPF 多区域明细、IS-IS、NAT Server、QoS、端口安全、802.1X、堆叠、IPv6、WLAN。

## 快速开始

需要 Python 3.10+。

```powershell
# 1. 准备环境（只需一次）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pyyaml python-docx

# 2. 校验要求文件
.\.venv\Scripts\python.exe run.py --validate --req samples\requirements-dhcp.yaml

# 3. 生成 Word（把 你的拓扑.topo 换成你从 eNSP 保存的文件）
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --req samples\requirements-dhcp.yaml --out output\配置文档.docx
```

macOS / Linux 下把 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python`。

只想看命令、不要 Word，去掉 `--out` 即可直接打印。

## 推荐流程：先出骨架，再展开

要求写得很粗、拓扑已经连好时，不要直接手写 requirements.yaml：

```powershell
# 1. 从拓扑 + 要求原文生成小骨架（只列分组和设备归属）
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --scaffold-out groups.yaml --req-text 课程设计要求.md

# 2. 改 groups.yaml 里的 TODO：分组名、人数、哪台设备承载哪个组

# 3. 展开成完整 requirements.yaml（自动分 VLAN、网段、网关）
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --build-req groups.yaml --build-out requirements.yaml

# 4. 校验并出文档
.\.venv\Scripts\python.exe run.py --validate --req requirements.yaml
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --req requirements.yaml --out 配置文档.docx
```

`--build-req` 不会覆盖已存在的文件，除非加 `--force`。展开结果里带 `# TODO:` 的行（优先级、根桥、物理口归属）需要人工确认。

## 输入从哪来

| 输入 | 怎么得到 |
| --- | --- |
| `.topo` | eNSP 里连好线，File → Save As |
| `requirements.yaml` | 人工写，或把老师的要求交给 AI 按 [提示词模板](docs/prompts/requirements-to-yaml.md) 转换 |

运行时不调用 AI，只读 YAML，所以结果可复现、可测试。AI 只在上面的转换步骤里用一次，且是可选步骤。

## AI 接入（可选）

复制配置模板，按你要用本地还是云端填：

```powershell
Copy-Item ai.example.yaml ai.yaml
```

`ai.yaml` 已在 `.gitignore` 里，不会被提交。

**本地模型**（Ollama、LM Studio 等任何 OpenAI 兼容端点）：

```yaml
provider: local
local:
  base_url: http://127.0.0.1:11434/v1
  model: qwen2.5:7b
```

**云端模型**（任意 OpenAI 兼容服务）：

```yaml
provider: cloud
cloud:
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  api_key: "sk-你的key"        # 或设环境变量 AI_API_KEY
```

然后一条命令把要求原文转成 YAML，并自动跑校验：

```powershell
.\.venv\Scripts\python.exe run.py `
  --ai-input 你的要求.md `
  --ai-config ai.yaml `
  --ai-out samples\generated.yaml
```

生成后如果校验不过，命令会打印具体哪个字段错了；改完再跑 `--validate` 复查。

**要求是 PDF / Word 时，先只出地址表**：让模型一步做到命令最容易把网关写错，所以分两步。

```powershell
# 第一步：只出三张表（网段与网关 / 每台设备地址 / 终端建议地址），不出命令
.\.venv\Scripts\python.exe run.py --ai-input 要求原文.md --ai-config ai.yaml --ai-table

# 人工核对、改完表格后，第二步：把确认过的表当输入，生成 YAML
.\.venv\Scripts\python.exe run.py --ai-input addresses.generated.md --ai-config ai.yaml --ai-out samples\generated.yaml
```

拿到 YAML 后想再核对一遍地址，不用生成命令：

```powershell
.\.venv\Scripts\python.exe run.py 你的拓扑.topo --req samples\generated.yaml --address-table
```

详细的提示词与核对清单见 [提示词模板](docs/prompts/requirements-to-yaml.md)。

## 支持的配置

| 类别 | YAML 字段 | 生成命令 |
| --- | --- | --- |
| 接口 IP | `interfaces[].ip` | `ip address` |
| 接口描述 | `interfaces[].description` | `description` |
| VLAN | `vlans[]` | `vlan` / `name` |
| 二层端口 | `interfaces[].mode` | `port link-type` / `port default vlan` / `port trunk allow-pass vlan` |
| MSTP | `protocols.mstp` | `stp mode mstp` / 域 / 实例 / 优先级 / `stp edged-port enable` |
| VRRP | `protocols.vrrp` | `vrrp vrid ... virtual-ip` / `priority` / `preempt-mode` |
| DHCP | `protocols.dhcp` | `dhcp enable` / `ip pool` / `dhcp select global` |
| OSPF | `protocols.ospf` | `ospf` / `area` / `network` |
| ACL | `protocols.acl` | `acl number` / `rule` / `traffic-filter` |
| 部门标注 | `devices[].department` | 只进文档，如「LSW1（财务部）」 |
| 层级标注 | `devices[].layer` | 只进文档：核心层 / 汇聚层 / 接入层 |
| 三层网关 | `interfaces[].name: Vlanif10` | `interface Vlanif10`（需先定义 VLAN 10） |
| 链路聚合 | `link_aggregation[]` | `interface Eth-Trunk` / `mode lacp` / 成员口 `eth-trunk` |

字段与校验规则的完整定义见 [REQUIREMENTS.md](REQUIREMENTS.md)，二次开发的接口说明见 [docs/API.md](docs/API.md)。

## 命令参考

```
run.py <topo> [选项]

  <topo>               .topo 文件路径
  --req <file>         requirements.yaml
  --out <file>         输出 .docx（需要 --req）
  --json               输出拓扑 JSON
  --validate           只校验 --req，不解析拓扑

  （无 --req 时打印设备、接口、连线表格）
```

## YAML 长什么样

```yaml
experiment:
  name: "实验八 综合组网"

departments:
  finance: {name: 财务部, subnet: 10.0.20.0/24}
  server:  {name: 服务器区, subnet: 10.0.30.0/24}

devices:
  AR1:
    role: router
    layer: core
    interfaces:
      - name: GigabitEthernet0/0/0
        ip: 10.0.1.1/24
        description: to-LSW1

  LSW1:
    role: switch
    department: 财务部
    layer: access
    vlans:
      - {id: 10, name: student}
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: access, vlan: 10}
      - {name: GigabitEthernet0/0/2, mode: trunk, allow_vlans: [10, 20]}

protocols:
  ospf:
    process: 1
    areas: [{area: 0}]
    auto_networks: true

  acl:
    - name: finance-guard
      device: AR1
      apply: {interface: GigabitEthernet0/0/0, direction: inbound}
      rules:
        - {action: permit, source: finance, destination: server}  # 财务可访问服务器
        - {action: deny, source: any, destination: finance}       # 其他部门不能访问财务
        - {action: permit, source: any, destination: any}         # 其余放行
```

生成后文档里设备标题会带部门，如「LSW1（财务部）」，设备表还会多出「部门」「层级」两列。这两项只是标注，不进设备命令。

更多样例在 `samples/`：`requirements.yaml`、`requirements-vlan.yaml`、`requirements-mstp.yaml`、`requirements-vrrp.yaml`、`requirements-dhcp.yaml`、`requirements-acl.yaml`。

## 项目结构

```
src/labgen/
  topo.py            .topo 解析：设备、接口、连线；接口序号 → 接口名
  requirements.py    YAML 读取与校验：字段类型、引用关系、取值范围
  ai.py              AI 接入：本地/云端 OpenAI 兼容端点，要求原文 → YAML
  generators.py      命令生成：每类配置一个纯函数，按设备聚合
  docx_writer.py     Word 输出：按设备分节、等宽命令块
  __main__.py        入口
run.py               免安装入口（把 src 加进路径）
tests/               pytest，85+ 用例
samples/             拓扑、要求、示例原文
docs/prompts/        AI 转换提示词
```

## 接口编号怎么来的

`.topo` 里只存 `srcIndex`/`tarIndex` 这类序号，不存接口名。换算规则按型号实测：

| 型号 | 规则 |
| --- | --- |
| AR2220 | 0 → GE0/0/0；1 → GE0/0/1；2 → GE0/0/2 |
| S5700 | 0 → GE0/0/1 … 23 → GE0/0/24 |
| S3700 | 0–21 → E0/0/1–22；22–23 → GE0/0/1–2 |

未知型号兜底：路由器从 0 起、交换机从 1 起。序号越界只记警告，不会崩。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

覆盖：拓扑解析（含编码、坏文件、越界）、YAML 校验（各字段非法值）、命令生成（逐行断言）、Word 结构、确定性。

## 已知限制

- 只支持华为 VRP 语法，不做配置下发（不连设备执行命令）。
- 只认 `.topo`，不解析 eNSP 打包的 `.zip` 工程。
- PC/STA 的 IP 不生成，工具只负责网络设备。
- 不做 IP 冲突、网段重叠检测（计划中）。
- eNSP 保存工程时会重排设备顺序，解析结果已按名字排序，不受影响。

## 环境

- Windows + PowerShell 5.1 及以上（脚本用了 `reconfigure` 输出 UTF-8）
- Python 3.10+
- 依赖：`PyYAML`、`python-docx`
