# eNSP 配置生成器

[![CI](https://github.com/Joya-yao/ensp-project/actions/workflows/ci.yml/badge.svg)](https://github.com/Joya-yao/ensp-project/actions/workflows/ci.yml)

读 eNSP 工程文件和结构化的实验要求，输出每台设备可整段粘贴的 VRP 配置命令（Word 文档）。

不用手写命令，也不用一个个设备点开抄。拓扑解析是确定性的：同一个输入，两次生成的命令逐字节相同。

## 它解决什么问题

实验课上老师给一份要求，拓扑自己在 eNSP 里连好了，但每台设备该配什么命令要一个一个想。这个工具把「拓扑 + 要求」直接变成「每台设备一节命令」，复制粘贴就能用。

```
lab.topo  ─┐
           ├─→ 命令生成 ─→ 配置文档.docx（AR1 / AR2 / LSW1 各一节）
要求.yaml ─┘
```

## 快速开始

```powershell
# 1. 准备环境（只需一次）
C:\Python310\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install pyyaml python-docx

# 2. 校验要求文件
.\.venv\Scripts\python.exe run.py --validate --req samples\requirements-dhcp.yaml

# 3. 生成 Word
.\.venv\Scripts\python.exe run.py samples\lab.topo --req samples\requirements-dhcp.yaml --out output\配置文档.docx
```

只想看命令、不要 Word，去掉 `--out` 即可直接打印。

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
  --ai-input samples\teacher-requirements.md `
  --ai-config ai.yaml `
  --ai-out samples\generated.yaml
```

生成后如果校验不过，命令会打印具体哪个字段错了；改完再跑 `--validate` 复查。

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

devices:
  AR1:
    role: router
    interfaces:
      - name: GigabitEthernet0/0/0
        ip: 10.0.1.1/24
        description: to-LSW1

  LSW1:
    role: switch
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
```

更多样例在 `samples/`：`requirements.yaml`、`requirements-vlan.yaml`、`requirements-mstp.yaml`、`requirements-vrrp.yaml`、`requirements-dhcp.yaml`。

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
