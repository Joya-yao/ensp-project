# 更新记录

## 未发布

### 新增

- **地址与网关章节**：Word 里多一节「地址与网关」，含三张表——网段与网关（网段/掩码/网关/网关在哪/该网段设备地址/终端可用地址）、每台设备的地址（设备/接口/IP/掩码/VLAN/网关/说明）、终端建议地址（PC 接在哪台交换机哪个口、VLAN、建议 IP、掩码、网关）。网关推断顺序：VRRP 虚拟 IP → DHCP 地址池 → 网段内 `.254` → 网段内唯一地址，推不出写 `—` 不瞎猜。
- **终端地址推导**：按拓扑连线找 PC 所连交换机端口，读该端口的 access VLAN，从对应网段按顺序取第一个未占用地址。
- **两阶段 AI 工作流**：`--ai-input --ai-table` 只让 AI 出「地址与网关表」，人工确认后再生成 YAML；提示词模板 `docs/prompts/requirements-to-yaml.md` 按「表格 → 确认 → YAML」重写，禁止模型一步做到命令。
- **`--address-table`**：不生成命令，只打印三张 Markdown 表（网段与网关 / 每台设备地址 / 终端建议地址），用来回读 YAML 有没有把网关改错。
- **`labgen.addresses`**：地址与网关的纯函数层，Word 与命令行共用同一份取值逻辑。
- **`scripts/export_configs.py`**：把命令按设备拆成 `<设备名>.txt` + `README.txt`，方便逐台整段粘贴。
- **实验指导书**：`docs/labs/` 增加实验一（VLAN/Trunk/VLANIF）指导书、参考拓扑与要求文件。
- **ACL 一条搞定 + 一次挂多接口**：`AclRule` 支持 `icmp_type`、`tcp_flag`，`AclSpec.apply` 支持 `interfaces: [...]`。这样「别人进不来、财务出得去」只写一条 ACL：`deny icmp icmp-type echo` + `deny tcp tcp-flag syn` + `permit ip`，一次挂到多个 VLANIF 入方向，不再按接口复制。
- **txt 导出修编码**：`export_configs.py` 默认写无 BOM 的 utf-8，新增 `--encoding gbk|utf-8|ascii`，并修掉 Windows 下 `\r\n` 被二次转义成空行的问题。
- **脚手架认部门更准**：先按「是/为/包括」截断再匹配，「机分别是销售部」「不能访问财务部」不再被当成部门名。
- **粘贴安全样式**：顶层 `quit` 改写为 `return` + `system-view`（`labgen.pastestyle`）。`return` 必然回用户视图、`system-view` 必然回系统视图，即使控制台重复执行一行也不会越退越深；嵌套 `quit`（`ospf` 里的 `area`）保留。
- **按行数分段导出**：`export_configs.py --chunk 40`（默认）把长设备拆成 `LSW1-01.txt`…，每段自带 `system-view`…`return`，单独粘也能跑——eNSP 一次粘贴行数有上限，整份 128 行会中途断掉。
- **ACL 展开开关**：`apply.expand: true` 把一条规则集按接口克隆成编号连续的 ACL（3000/3001/3002）。S5700 上同一 ACL 不能重复挂多个 Vlanif，会报 `Sacl doesn't support config the same acl or rule repeatedly`。
- **icmp-type 统一输出数字**：`icmp_type: echo` 生成 `icmp-type 8 0`。部分 VRP 版本不认 `echo` 名字，整条 rule 被拒后 ACL 只剩 permit，表现为「配了 ACL 但不生效」。
- **RIP**：`protocols.rip` 支持进程号、版本、`devices` 限定范围；network 自动按类式地址推导（10.x → 10.0.0.0），v2 附带 `undo summary`。
- **BGP**：`protocols.bgp` 支持 `as`、`router_id`、`neighbors`（remote_as / description）、network 自动或手工宣告，邻居上可挂 route-policy。
- **前缀列表与路由策略**：`prefix_list`（前缀 + greater-equal / less-equal）与 `route_policy`（节点、if-match ip-prefix / acl、apply cost / local-preference / tag、apply_peer + import/export）。引用不存在的列表或 ACL 会在解析时报错。
- **Easy IP 出方向 NAT**：`protocols.nat` 生成基本 ACL（2000-2999）+ 接口 `nat outbound`，`source` 支持部门 key / 网段 / any。
- **本地网页界面**：`run.py --ui` 用标准库起服务，浏览器里看拓扑、校验 YAML、出地址表、生成配置并直接下载；`--window` 配 pywebview 可得到独立窗口，没装则退回浏览器。只监听 `127.0.0.1`，带一次性 token，读限项目目录、写限 `output/`。
- **界面支持上传与在线编辑**：可直接选 `.topo` 上传（按原始字节落盘，自动识别编码），YAML 在页面里改完一键保存；中间文件（拓扑、草稿 YAML、地址表）与最终产物（docx、分段 txt）分别指定目录。
- **界面内置 AI 转换**：页面里选本地/云端、填 base_url / model / key，贴要求原文即可出 YAML 或只出地址表；不填也能用全部离线功能。
- **界面回显落盘位置**：地址表生成时就写盘并显示绝对路径，页面上可以直接改再保存；生成配置后每个文件都带完整路径与下载链接；选文件即自动上传并填入路径，不用先点上传。
- **地址表支持待填模板**：只给拓扑、不给 YAML 时，按连线生成一张 `?` 待填表（连线 / 设备地址 / 终端地址三节），填完可直接保存。
- **产物按拓扑名命名**：中间文件 `<拓扑名>-requirements.yaml`、`<拓扑名>-addresses.md`，最终产物 `<拓扑名>-配置文档.docx`、`<拓扑名>-<设备>.txt`，同名直接覆盖，多项目不混。
- **地址表改成 Excel**：装了 `openpyxl` 时生成 `<拓扑名>-addresses.xlsx`（两页签：设备地址 / 终端地址），点「地址表」自动用 Excel 打开；在 Excel 里改 IP、掩码、VLAN 并保存后，点「生成配置」时**以 Excel 为准**覆盖 YAML（设备行改接口 IP，终端行改所连端口的 access VLAN，空值或 `?` 表示不改）。没装 openpyxl 时退回 Markdown。
- **双击启动**：仓库根目录 `启动界面.bat`，双击即启动本地界面并自动打开默认浏览器。
- **产物直接打开**：产物列表里的「打开」用系统默认程序打开文件（Excel / Word / 记事本），不再只能下载。
- **接口名自动修正**：生成前按拓扑校正 YAML 里的接口名——同号但类型写错（S3700 的 3 号口写成 `GigabitEthernet0/0/3`）会自动换成 `Ethernet0/0/3`，但只换到「真的接了线」的端口；完全不存在且无同号可换的端口会被移除，并在结果里逐条说明。`Vlanif`、`Eth-Trunk` 这类逻辑接口不受影响。
- **终端地址来源标注**：文档「终端建议地址」表里，地址表填过的终端标「地址表」，没填的标「地址表未填」并按所接端口的 VLAN 自动取号；表头前加一段说明统计了几台来自地址表、几台是自动建议。
- **修复下载中文文件名报错**：`Content-Disposition` 里不再塞原始中文（浏览器会报磁盘/内存不足之类），改成 ASCII 兜底名 + `filename*=UTF-8''…`。
- **修复「打开」链接**：产物里的「打开」改为后台请求后由本机程序打开，不再让浏览器跳到一个 JSON 页面；服务端也改成先读完请求体再回 403，避免连接被重置。
- **文档写明浏览器打不开 Word/Excel**：README「已知限制」新增一节，说明「打开」是调用本机 Office/WPS、失败时的报错对照表、产物路径（`output/ui/work` 中间文件、`output/ui/final` 最终产物），以及后续计划（内置预览 + 打开所在文件夹）。界面产物区也加了同样提示。

### 变更

- `PC/STA 的 IP 不生成` 的限制收窄：PC 地址不写进命令（eNSP 里手工配），但文档会给出建议地址与网关。

## v0.1.0 — 2026-10-23

首个可用版本：从 eNSP 工程和结构化要求生成 VRP 配置文档。

### 新增

- **拓扑解析**：读 `.topo`（UTF-8 / UTF-16 / GB18030 自动识别），输出设备、接口、连线。接口序号按型号换算成 `GigabitEthernet0/0/x`，覆盖 AR2220/AR1220/S3700/S5700/AC6005/AD9430/R250D，未知型号有兜底规则。序号越界只告警不崩。
- **结构化要求**：YAML 定义配置意图，字段贴近人的表达（`vlan: {id: 10, name: student}`），不写命令。读取时做类型、范围、引用关系校验，错误消息带设备名与字段名。
- **命令生成**：接口 IP/描述、VLAN、Access/Trunk、MSTP（域/实例/优先级/边缘端口）、VRRP（虚拟 IP/优先级/抢占）、DHCP（全局地址池）、OSPF（自动推导网段 + 反掩码）。同一输入输出逐字节一致。
- **ACL 与部门隔离**：`departments` 定义部门网段，`protocols.acl` 用部门 key 写规则（如「财务可访问服务器、其他禁止访问财务」），生成 `acl number` / `rule` / `traffic-filter`。
- **Vlanif 三层网关**：接口名可写 `Vlanif10`，只要该设备定义了 VLAN 10；VRRP、OSPF、ACL 都可以挂在 Vlanif 上。
- **链路聚合**：`link_aggregation` 定义 Eth-Trunk（LACP / 手工），生成 `interface Eth-Trunk`、`mode lacp`、成员口 `eth-trunk N`。
- **骨架工作流**：`--scaffold-out` 从拓扑和要求原文生成 `groups.yaml`，人工确认分组与设备归属后，`--build-req` 自动分配 VLAN、网段、网关，展开成 `requirements.yaml`。
- **部门与层级标注**：设备可写 `department`、`layer`，只出现在文档里（标题「LSW1（财务部）」、设备表多出部门/层级两列），不进设备命令。
- **Word 输出**：按设备分节，命令用 Consolas 等宽块、零行距，支持整段复制；附拓扑概览表与未配置设备清单。
- **AI 入口（可选）**：`ai.yaml` 切换本地 / 云端 OpenAI 兼容端点，把要求原文转成 YAML，转完自动跑校验。提示词已覆盖部门标注与 ACL 意图判断。
- **命令行**：`--validate` 只校验要求文件；`--json` 导出拓扑；`--out` 生成 Word。
- **测试与 CI**：135 个 pytest 用例；GitHub Actions 在 Python 3.10 / 3.12 上跑测试。

### 已知限制

- 只支持华为 VRP，不支持配置下发到真实设备。
- 只认 `.topo`，不解析 eNSP 的 `.zip` 工程包。
- PC/STA 的 IP 不生成。
- 尚未做 IP 冲突与网段重叠检测。
