# API 参考

面向二次开发：所有公开接口都在 `src/labgen/` 下，纯函数为主，没有全局状态。

```python
from labgen.topo import parse_topo
from labgen.requirements import load_requirements
from labgen.generators import build_configs
from labgen.docx_writer import write_docx
```

---

## labgen.topo

### `parse_topo(path: str | Path) -> Topology`

解析 `.topo` 文件。编码按 `utf-8-sig` → `utf-16` → `gb18030` 依次尝试。

- 抛 `FileNotFoundError`：文件不存在
- 抛 `TopoError`：解码失败、XML 损坏、根节点不是 `<topo>`

```python
topo = parse_topo("samples/lab.topo")
topo.devices          # list[Device]，按设备名排序
topo.links            # list[Link]，按端点排序
topo.warnings         # list[str]，越界等非致命问题
```

### `load_topo(path) -> dict`

`parse_topo(path).to_dict()` 的快捷方式，结果可直接 `json.dumps`。

### `Topology`

| 成员 | 类型 | 说明 |
| --- | --- | --- |
| `version` | `str` | 文件里的 topo 版本 |
| `source` | `str` | 文件路径 |
| `devices` | `list[Device]` | 按名字排序 |
| `links` | `list[Link]` | 按端点排序 |
| `warnings` | `list[str]` | 解析告警 |

方法：`device(name) -> Device | None`、`links_of(name) -> list[Link]`、`to_dict() -> dict`。

### `Device`

字段：`id`、`name`、`model`、`mac`、`com_port`、`device_type`（`router` / `switch` / `pc`）、`ports`、`slot_count`。

方法：`port(index) -> Port | None`（越界返回 `None`，不抛异常）。

### `Port`

字段：`index`（全局序号，对应 `srcIndex`/`tarIndex`）、`name`（如 `GigabitEthernet0/0/1`）、`prefix`、`slot`、`number_in_block`。

### `Link` / `Endpoint`

`Link.src`、`Link.dst` 是 `Endpoint(device, port, index)`；`port` 为 `None` 表示序号超出设备接口清单。`Link.cable` 是线缆类型。

---

## labgen.requirements

### `load_requirements(path) -> Requirements`

读取并校验 YAML。所有字段错误统一抛 `RequirementError`，消息里带设备名/接口名/字段名。

```python
req = load_requirements("samples/requirements-dhcp.yaml")
req.experiment        # str
req.devices           # dict[str, DeviceSpec]
req.ospf / req.mstp / req.vrrp / req.dhcp   # 各自为 None 或配置对象
```

### 数据类

| 类 | 关键字段 |
| --- | --- |
| `InterfaceSpec` | `name`、`ip`、`description`、`mode`、`vlan`、`allow_vlans`、`edged_port` |
| `VlanSpec` | `id`、`name` |
| `DeviceSpec` | `name`、`role`、`interfaces`、`vlans` |
| `OspfSpec` | `process`、`router_id`、`areas`、`auto_networks` |
| `MstpSpec` | `region`、`devices`（设备名 → 优先级） |
| `VrrpSpec` | `groups` |
| `DhcpSpec` | `pools`（名字 → 地址池）、`devices` |

`InterfaceSpec.network` 是只读属性，返回 `IPv4Network`。

---

## labgen.generators

### `build_configs(topo, req) -> dict[str, list[str]]`

主入口：按拓扑顺序为每台设备生成完整命令块，键为设备名，值为命令行列表（含 `system-view` 与 `return`）。

先做交叉校验（`check_specs`），有问题抛 `RequirementError`，消息里逐条列出。

### `check_specs(topo, req) -> list[str]`

只校验不生成：设备是否存在于拓扑、接口是否存在、VRRP/DHCP 引用的设备与接口是否对得上。返回问题列表，空列表表示通过。

### 分类生成函数

| 函数 | 输入 | 输出 |
| --- | --- | --- |
| `vlan_commands(device, spec)` | 设备 + 要求 | VLAN 创建命令 |
| `mstp_commands(device, spec, req)` | 同上 + 全局 | MSTP 域/实例/优先级 |
| `ip_commands(device, spec, extras=None)` | `extras` 是「接口名小写 → 额外命令行」 | 接口块 |
| `vrrp_lines(device, req)` | 设备 + 全局 | `dict[接口名小写, 命令行]` |
| `dhcp_lines(device, req)` | 同上 | `dict[接口名小写, 命令行]` |
| `dhcp_pool_commands(device, req)` | 同上 | 地址池命令 |
| `ospf_commands(device, spec, req)` | 同上 | OSPF 进程与 network |

`ip_commands` 的 `extras` 用于把 VRRP、DHCP 的行合并进同一个接口块，避免重复进入接口视图。

---

## labgen.ai

### `load_ai_config(path) -> AiConfig`

读取 `ai.yaml`，校验 `provider`（`local` / `cloud`）、`base_url`、`model`。云端缺 `api_key` 时回退到环境变量 `AI_API_KEY`。

### `AiConfig`

字段：`provider`、`base_url`、`model`、`api_key`、`timeout`、`temperature`。
属性 `endpoint` 返回 `{base_url}/chat/completions`。

### `chat(config, requirement_text) -> str`

发一次 `/chat/completions` 请求，返回模型输出的原文。HTTP 错误统一包成 `AiError`。

### `convert_requirements(config, requirement_text) -> str`

`chat` + 去掉模型可能加的 Markdown 围栏，返回可写入文件的 YAML 文本（未校验）。

### `strip_code_fence(text) -> str`

去掉 ```` ```yaml ```` 这类围栏，纯函数。

---

## labgen.docx_writer

### `build_document(topo, req, configs) -> Document`

构建 `python-docx` 文档对象但不写盘，便于测试。

文档结构：标题 → 使用说明 → 拓扑概览（设备表、连线表）→ 每台设备一节 → 未生成配置的设备清单。

### `write_docx(topo, req, configs, path) -> Path`

调用 `build_document` 并保存，自动建父目录，返回实际路径。

---

## 错误处理约定

| 异常 | 何时抛 |
| --- | --- |
| `FileNotFoundError` | 输入文件不存在 |
| `TopoError` | 拓扑无法解码或结构不对 |
| `RequirementError` | YAML 字段非法，或与拓扑对不上 |

CLI 会把这三类异常转成中文错误信息打到 stderr，返回退出码 1；其余异常照常抛出，方便定位 bug。
