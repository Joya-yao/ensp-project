"""把实验要求原文转成 requirements.yaml 的 AI 调用层。

只做一件事：调 OpenAI 兼容的 /chat/completions。
本地（Ollama、LM Studio）和云端（任意兼容端点）走同一套代码，靠配置切换。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "AiError",
    "AiConfig",
    "load_ai_config",
    "chat",
    "convert_requirements",
    "convert_address_table",
]

ADDRESS_PROMPT = """你是网络实验配置助手。用户给的是 PDF/Word 实验要求原文，可能有 OCR 错误和错位的表格。

现在只做一件事：提取地址，输出 Markdown 表格。不要输出 YAML，不要输出配置命令。

输出三张表，表头照抄：
表 1 网段与网关：| 网段 | 掩码 | 网关 | 网关在哪台设备 | 原文依据 |
表 2 每台设备的地址：| 设备 | 接口 | IP | 掩码 | VLAN | 网关 | 说明 |
表 3 终端地址：| 终端 | 接在哪 | VLAN | IP | 掩码 | 网关 |

规则：
1. 只写原文能推出来的值。没写也推不出的，写 ?，不要编地址、不要默认 .254。
2. 网关按原文写；原文只说「交换机做网关」没给地址时写 ?。
3. 接口名用 VRP 写法：GigabitEthernet0/0/1、Vlanif10、Eth-Trunk1。
4. 表 3 原文没给 PC 地址就留空表。
5. 表格后面加两节：「待确认」逐条列出拿不准的项和原文出处；「我推断的」列出按惯例补的值和依据。
"""

SYSTEM_PROMPT = """你是网络实验配置助手。把用户的实验要求转成 YAML。

规则：
1. 只输出 YAML，不要解释，不要 Markdown 围栏。
2. 严格用这些顶层键：experiment、departments、devices、protocols。
3. devices.<设备名> 下可用：role、department、layer、vlans、link_aggregation、interfaces。
   - department 是中文部门名（如 财务部），只显示在文档标题里，不进命令。
   - layer 只能是 core / aggregation / access（核心/汇聚/接入）。
   - interfaces 元素可用：name、ip、description、mode（access/trunk）、vlan、allow_vlans、edged_port。
   - name 可以写 Vlanif10 这类逻辑接口，但该设备必须先定义 VLAN 10。
   - link_aggregation 元素可用：id、mode（lacp/manual）、port_mode（access/trunk）、vlan、allow_vlans、members（至少两个物理口）。
4. departments 下每项：name（中文名）、subnet（该部门网段 CIDR）。
5. protocols 下可用：ospf、mstp、vrrp、dhcp、acl、rip、bgp、prefix_list、route_policy、nat，结构见用户消息里的字段说明。
6. IP 一律 CIDR（10.0.1.1/24）。接口名用 GigabitEthernet0/0/0 形式。
7. VLAN 必须先在该设备 vlans 里定义，接口只能引用已定义 VLAN。
8. 原文说「A 不能访问 B，但 B 可以访问 C」这类访问控制，必须写成 acl 规则：
   source/destination 用部门 key 或 any；默认动作用 permit / deny，按顺序匹配。
9. 原文没提到的不要猜；缺信息用 YAML 注释 # TODO: 标出，不要编造。
10. ACL 尽量少，先判断一条 ACL 能不能做完：
    - 「别人不能访问财务部，财务部可以访问别人」= deny icmp icmp-type echo + deny tcp tcp-flag syn
      + permit ip，一条 ACL 就够，用 apply.interfaces 一次挂到多个 VLANIF 入方向。
    - 不要按接口复制成多条 ACL；一条能表达就不写第二条。
    - 交换机（Vlanif）上同一个 ACL 不能挂多个接口，会报 SACL 重复绑定：
      一条规则集 + apply.interfaces + expand: true，工具会自动克隆成 3000/3001/3002。
    - 无状态 ACL 做不到的（双向都要挡、需要会话表）在输出里标 TODO 说明，别硬凑规则。
11. description、vlan name 只用 ASCII；中文只放 department / experiment.name 这类文档字段。
    eNSP 命令行吃中文会乱码，粘贴会中途失败。
12. 路由类要求：
    - RIP 的 network 是类式地址，10.x 一律写 10.0.0.0，别写 10.10.0.0；用 devices 限定跑 RIP 的设备。
    - BGP 必须给 as 和 neighbors（每个邻居要 remote_as）；network 省略时从接口地址自动宣告。
    - 前缀列表用 prefix_list，路由策略用 route_policy，策略里引用的 prefix_list / match_acl 必须先定义。
    - NAT 只支持出方向 easy-ip：基本 ACL 2000-2999 + 出口接口 nat outbound；其他类型标 TODO。
"""

FIELD_GUIDE = """字段示例：
departments:
  finance: {name: 财务部, subnet: 10.0.20.0/24}
  server: {name: 服务器区, subnet: 10.0.30.0/24}
devices:
  AR1:
    role: router
    layer: core
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.1.1/24, description: to-LSW1}
  LSW1:
    role: switch
    department: 财务部
    layer: access
    vlans:
      - {id: 10, name: student}
    link_aggregation:
      - {id: 1, mode: lacp, port_mode: trunk, allow_vlans: [10, 20],
         members: [GigabitEthernet0/0/3, GigabitEthernet0/0/4]}
    interfaces:
      - {name: Vlanif10, ip: 10.10.0.254/24}
      - {name: GigabitEthernet0/0/1, mode: access, vlan: 10}
      - {name: GigabitEthernet0/0/2, mode: trunk, allow_vlans: [10, 20]}
protocols:
  ospf: {process: 1, areas: [{area: 0}], auto_networks: true}
  mstp:
    region: {name: RG-1, revision: 1}
    instances: [{instance: 1, vlans: [10]}]
    devices: {LSW1: {priorities: {1: 4096}}}
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.254,
         devices: {AR1: {priority: 120}, AR2: {priority: 100}}}
  dhcp:
    pools:
      - {name: vlan10, network: 10.0.1.0/24, gateway: 10.0.1.1, dns: [114.114.114.114]}
    devices: {AR1: {pools: [vlan10], interfaces: [GigabitEthernet0/0/0]}}
  acl:
    - name: finance-guard
      device: AR1
      apply: {interface: GigabitEthernet0/0/0, direction: inbound}
      rules:
        - {action: permit, source: finance, destination: server}
        - {action: deny, source: any, destination: finance}
        - {action: permit, source: any, destination: any}
    - name: finance-guard-once
      device: LSW1
      acl_number: 3000
      apply: {interfaces: [Vlanif10, Vlanif20, Vlanif40], direction: inbound}
      rules:
        - {action: deny, protocol: icmp, icmp_type: echo, destination: finance}
        - {action: deny, protocol: tcp, tcp_flag: syn, destination: finance}
        - {action: permit, source: any, destination: any}
  rip: {process: 1, version: 2, devices: [AR2]}
  bgp:
    as: 65001
    router_id: 1.1.1.1
    devices: [AR1]
    neighbors: [{ip: 10.0.1.2, remote_as: 65002}]
  prefix_list:
    - name: PL-24
      device: AR1
      rules: [{seq: 10, action: permit, prefix: 192.168.0.0/16, greater_equal: 24, less_equal: 24}]
  route_policy:
    - name: RP-IN
      device: AR1
      apply_peer: 10.0.1.2
      apply_direction: import
      nodes: [{seq: 10, action: permit, match_prefix_list: PL-24, apply_local_preference: 200}]
  nat:
    - {name: egress, device: AR1, acl_number: 2000, interface: GigabitEthernet0/0/1, source: finance}
"""


class AiError(Exception):
    """AI 配置或调用失败。"""


@dataclass(frozen=True)
class AiConfig:
    provider: str          # local / cloud
    base_url: str
    model: str
    api_key: str = ""
    timeout: int = 120
    temperature: float = 0.0

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


def _section(raw, name: str) -> dict:
    value = raw.get(name) or {}
    if not isinstance(value, dict):
        raise AiError(f"ai.yaml 里的 {name} 应该是键值对")
    return value


def load_ai_config(path: str | Path) -> AiConfig:
    """读取 ai.yaml 并校验。云端缺 key 时回退到环境变量 AI_API_KEY。"""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"AI 配置文件不存在：{path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise AiError("ai.yaml 根节点应该是键值对")

    provider = raw.get("provider")
    if provider not in ("local", "cloud"):
        raise AiError("ai.yaml 的 provider 只能是 local 或 cloud")

    section = _section(raw, provider)
    base_url = section.get("base_url")
    model = section.get("model")
    if not isinstance(base_url, str) or not base_url.strip():
        raise AiError(f"ai.yaml 的 {provider}.base_url 必须填写")
    if not isinstance(model, str) or not model.strip():
        raise AiError(f"ai.yaml 的 {provider}.model 必须填写")

    api_key = section.get("api_key") or ""
    if not isinstance(api_key, str):
        raise AiError(f"ai.yaml 的 {provider}.api_key 应该是字符串")
    if provider == "cloud" and not api_key.strip():
        api_key = os.environ.get("AI_API_KEY", "")
    if provider == "cloud" and not api_key.strip():
        raise AiError(
            "云端模式缺 api_key：填在 ai.yaml 的 cloud.api_key，或设环境变量 AI_API_KEY"
        )

    timeout = raw.get("timeout", 120)
    if not isinstance(timeout, int) or not 10 <= timeout <= 600:
        raise AiError("ai.yaml 的 timeout 应该是 10-600 的整数")

    temperature = raw.get("temperature", 0.0)
    if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
        raise AiError("ai.yaml 的 temperature 应该在 0-2 之间")

    return AiConfig(
        provider=provider,
        base_url=base_url.strip(),
        model=model.strip(),
        api_key=api_key.strip(),
        timeout=timeout,
        temperature=float(temperature),
    )


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise AiError(f"AI 接口返回 {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise AiError(f"连不上 AI 接口 {url}：{exc.reason}") from exc


def chat(config: AiConfig, requirement_text: str, system_prompt: str | None = None) -> str:
    """发一次对话请求，返回模型输出文本。"""

    messages = [
        {"role": "system", "content": system_prompt or (SYSTEM_PROMPT + "\n" + FIELD_GUIDE)},
        {"role": "user", "content": "实验要求原文：\n" + requirement_text},
    ]
    headers = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "stream": False,
    }
    data = _post_json(config.endpoint, payload, headers, config.timeout)

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiError(f"AI 返回结构不符合预期：{str(data)[:300]}") from exc
    return content


_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n|\n```\s*$")


def strip_code_fence(text: str) -> str:
    """去掉模型有时会多加的 Markdown 围栏。"""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip() + "\n"


def convert_requirements(config: AiConfig, requirement_text: str) -> str:
    """要求原文 → YAML 文本（已去围栏，未校验）。"""

    return strip_code_fence(chat(config, requirement_text))


def convert_address_table(config: AiConfig, requirement_text: str) -> str:
    """阶段一：要求原文 → 地址与网关 Markdown 表格（不产出 YAML、不产出命令）。"""

    text = chat(config, requirement_text, system_prompt=ADDRESS_PROMPT).strip()
    return text + "\n"
