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
topo = parse_topo("你的拓扑.topo")
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
req.departments       # dict[str, Department]，ACL 引用的部门网段
req.acls              # tuple[AclSpec, ...]
```

### 数据类

| 类 | 关键字段 |
| --- | --- |
| `InterfaceSpec` | `name`、`ip`、`description`、`mode`、`vlan`、`allow_vlans`、`edged_port` |
| `VlanSpec` | `id`、`name` |
| `DeviceSpec` | `name`、`role`、`interfaces`、`vlans`、`department`、`layer` |
| `Department` | `key`、`name`、`subnet` |
| `AclRule` | `action`、`source`、`destination`、`protocol`、`destination_port`、`icmp_type`、`tcp_flag` |
| `AclSpec` | `name`、`device`、`rules`、`acl_number`、`interface`、`direction`、`interfaces` |
| `OspfSpec` | `process`、`router_id`、`areas`、`auto_networks` |
| `MstpSpec` | `region`、`devices`（设备名 → 优先级） |
| `VrrpSpec` | `groups` |
| `DhcpSpec` | `pools`（名字 → 地址池）、`devices` |
| `RipSpec` | `process`、`version`、`auto_networks`、`networks`、`devices` |
| `BgpSpec` | `as_number`、`router_id`、`neighbors`、`auto_networks`、`networks`、`devices` |
| `PrefixListSpec` | `name`、`device`、`rules`（`PrefixListRule`：`seq`、`action`、`prefix`、`greater_equal`、`less_equal`） |
| `RoutePolicySpec` | `name`、`device`、`nodes`、`apply_peer`、`apply_direction` |
| `NatRule` | `name`、`device`、`acl_number`、`interface`、`source`、`type`（目前只支持 easy-ip） |

`DeviceSpec.department`、`DeviceSpec.layer` 只用于文档标注，不参与命令生成。
`AclRule` 的 `source`/`destination` 在解析时已归一化：要么是 `any`，要么是部门 key，要么是 CIDR 字符串。
`AclRule.icmp_type`、`AclRule.tcp_flag` 只在对应协议下合法，用来表达「只挡新建连接、放行回程」这一类无状态 ACL 写法。
`AclSpec.interfaces` 非空时一条 ACL 会挂到多个接口上（同方向），`interface` 仍保留单接口写法。

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
| `link_aggregation_commands(device, spec)` | 同上 | Eth-Trunk 与成员口 |
| `mstp_commands(device, spec, req)` | 同上 + 全局 | MSTP 域/实例/优先级 |
| `ip_commands(device, spec, extras=None)` | `extras` 是「接口名小写 → 额外命令行」 | 接口块 |
| `vrrp_lines(device, req)` | 设备 + 全局 | `dict[接口名小写, 命令行]` |
| `dhcp_lines(device, req)` | 同上 | `dict[接口名小写, 命令行]` |
| `dhcp_pool_commands(device, req)` | 同上 | 地址池命令 |
| `acl_commands(device, req)` | 同上 | `(ACL 定义块, dict[接口名小写, traffic-filter 行])` |
| `ospf_commands(device, spec, req)` | 同上 | OSPF 进程与 network |
| `rip_commands(device, spec, req)` | 同上 | RIP 进程、版本与类式 network |
| `bgp_commands(device, spec, req)` | 同上 | BGP 进程、邻居、network、邻居上的 route-policy |
| `prefix_list_commands(device, req)` | 同上 | `ip ip-prefix` 规则 |
| `route_policy_commands(device, req)` | 同上 | `route-policy` 节点与 `if-match` / `apply` |
| `nat_commands(device, req)` | 同上 | `(基本 ACL 块, dict[接口名小写, nat outbound 行])` |

`ip_commands` 的 `extras` 用于把 VRRP、DHCP、ACL、NAT 的下发行合并进同一个接口块，避免重复进入接口视图。

---

## labgen.scaffold

两组文件工作流：`groups.yaml` 骨架 → `requirements.yaml`。

| 函数 | 作用 |
| --- | --- |
| `build_groups_draft(topo, req_text=None) -> str` | 从拓扑与要求原文生成骨架 YAML 文本 |
| `load_groups(path) -> GroupsSpec` | 读取并校验骨架 |
| `expand_groups(spec, topo) -> str` | 分配 VLAN/网段/网关，展开成 requirements 文本 |

展开规则是确定性的：VLAN 从 `vlan_start` 起按 `vlan_step` 递增，网段 `10.<vlan>.0.0/24`，网关 `.254`；VLAN 号必须 ≤254。

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

## labgen.addresses

地址与网关对照的纯函数层，Word 文档和命令行表格共用。

| 函数 | 作用 |
| --- | --- |
| `address_entries(req)` | 所有带 IP 的接口 → `AddressEntry` 列表 |
| `gateway_map(req, entries)` | 网段 → (网关, 来源)。顺序：VRRP → DHCP → `.254` → 唯一地址 |
| `vlan_networks(entries)` | VLAN → 网段，从 `VlanifN` 推 |
| `network_rows(req)` | 网段与网关表行 |
| `device_rows(req)` | 每台设备地址表行，自己是网关的写「本机」 |
| `terminal_rows(topo, req)` | PC 接入位置 + 按顺序分配的建议地址 |
| `render_markdown(topo, req)` | 三张表的 Markdown 文本，给 `--address-table` 用 |

## labgen.excel

地址表 Excel（可选，需要 `openpyxl`）。两页签「设备地址」「终端地址」，用户在 Excel 里改完保存，生成时以它为准。

| 函数 | 作用 |
| --- | --- |
| `available()` | 有没有装 openpyxl |
| `write_address_xlsx(path, topo, req=None)` | 写工作簿；`req=None` 时写 `?` 待填模板 |
| `read_address_xlsx(path)` | 读回 `{"devices": [...], "terminals": [...]}`，跳过空行 |
| `apply_overrides(req, sheet)` | 用表里的值覆盖 `Requirements`：设备行改 IP/掩码/VLAN，终端行改所连端口的 access VLAN；空值或 `?` 表示不改 |

覆盖返回的是新的 `Requirements`（`dataclasses.replace`），原始对象不动。

## labgen.repair

按拓扑校正 YAML 里的接口名，生成命令前调用。

| 函数 | 作用 |
| --- | --- |
| `repair_interfaces(topo, req)` | 返回 `(修正后的 Requirements, 说明列表)`：同号换类型（仅当目标端口在拓扑里接了线）、找不到对应端口的整条移除；`Vlanif`、`Eth-Trunk` 等逻辑接口用 `interface_ok` 判定，不动 |
| `suggest_interface(topo, device, name)` | 单个接口名的建议值，没有就返回 `None` |

## labgen.ui

本地网页界面，纯标准库（`http.server`），只监听 `127.0.0.1`。

| 函数 | 作用 |
| --- | --- |
| `make_server(port=0, root=None, work=None, final=None)` | 起服务，返回 `(server, url)`；port=0 时由系统分配，url 里带一次性 token |
| `serve(port=8765, open_browser=True, window=False)` | 阻塞运行；`window=True` 时尝试用 pywebview 开独立窗口，没装则退回浏览器 |

HTTP 接口：

| 路径 | 方法 | 作用 |
| --- | --- | --- |
| `/` | GET | 单页界面 |
| `/api/summary` | POST | 解析拓扑，返回设备与连线概况 |
| `/api/validate` | POST | 校验 YAML |
| `/api/address-table` | POST | 有 `yaml` 时按 YAML 出表，只有 `topo` 时出 `?` 待填模板；装了 openpyxl 就写 `<拓扑名>-addresses.xlsx`（否则 `.md`），返回 `saved`/`mode`/`stem`/`xlsx` |
| `/api/generate` | POST | 生成 `<拓扑名>-配置文档.docx` 与 `<拓扑名>-<设备>.txt`（超 40 行自动分段）；若 `addr_path` 指向存在的 xlsx，先用它覆盖 YAML，返回 `overrides` 说明用了哪份表 |
| `/api/upload` | POST | `{name, data(base64), work_dir}` 把上传的 `.topo` 原始字节写进中间目录 |
| `/api/save` | POST | `{path, content}` 保存文本文件，只能落在 `output/` 下 |
| `/api/read` | GET | `?path=` 读取项目目录内的文本文件 |
| `/api/list` | GET | `?dir=` 列出目录里的 yaml/md/txt/topo |
| `/api/ai-convert` | POST | `{text, provider, base_url, model, api_key, mode}`，走 `labgen.ai` 出 YAML 或地址表；云端缺 key 直接 400 |
| `/api/file` | GET | `?path=` 下载 `output/` 下的产物 |
| `/api/open` | GET | `?path=` 用系统默认程序打开 `output/` 下的产物（Excel / Word / 记事本） |

POST 必须带 `X-Token` 请求头（页面里的 `__TOKEN__` 会被替换成实际值）；`yaml`、`topo`、`work_dir`、`final_dir` 必须是字符串，类型不对返回 400 而不是断开连接。目录参数都会被解析成绝对路径，越出 `output/` 直接拒绝。

## labgen.docx_writer

### `build_document(topo, req, configs) -> Document`

构建 `python-docx` 文档对象但不写盘，便于测试。

文档结构：标题 → 使用说明 → 拓扑概览（设备表、连线表）→ 地址与网关（网段表、每台设备地址表、终端建议地址）→ 每台设备一节 → 未生成配置的设备清单。

「地址与网关」的网关推断顺序：VRRP 虚拟 IP → DHCP 地址池 `gateway` → 网段内 `.254` → 网段内唯一地址；都没有时写 `—`，不猜。终端建议地址按拓扑连线找到 PC 所连交换机端口，从该端口 access VLAN 的网段里取第一个未占用地址。

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
