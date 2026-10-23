"""eNSP ``.topo`` 解析：设备、接口、连接关系。

只做确定性解析：文件里没有的信息不做推断。
接口编号规则来自实测，见 :data:`MODEL_PORTS`。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "TopoError",
    "Port",
    "Device",
    "Endpoint",
    "Link",
    "Topology",
    "parse_topo",
    "load_topo",
]


class TopoError(Exception):
    """拓扑文件无法读取或结构不符合预期。"""


# 接口前缀 → VRP 接口名
VRP_PREFIX = {
    "GE": "GigabitEthernet",
    "Ethernet": "Ethernet",
    "XGE": "XGigabitEthernet",
    "10GE": "10GE",
}

# 实测的每型号端口编号规则：[(接口前缀, 起始编号, 端口数), ...]
# 不同系列的起始编号不一致，AR/AC 从 1 起，AD9430/R250D 从 0 起。
MODEL_PORTS: dict[str, list[tuple[str, int, int]]] = {
    "AR2220": [("GE", 0, 1), ("GE", 1, 2)],
    "AR1220": [("GE", 0, 1), ("GE", 1, 1)],
    "AC6005": [("GE", 1, 8)],
    "AD9430": [("GE", 0, 28)],
    "R250D": [("GE", 0, 1)],
    "S3700": [("Ethernet", 1, 22), ("GE", 1, 2)],
    "S5700": [("GE", 1, 24)],
}

_ENCODINGS = ("utf-8-sig", "utf-16", "gb18030")


@dataclass(frozen=True)
class Port:
    """一个可连线的物理接口。"""

    index: int          # 全局序号，等于 .topo 里的 srcIndex / tarIndex
    name: str           # VRP 接口名，如 GigabitEthernet0/0/1
    prefix: str         # 接口前缀，如 GigabitEthernet
    slot: str           # 所属槽位，如 slot17
    number_in_block: int  # 在当前 interface 块内的偏移


@dataclass
class Device:
    """一台设备及其接口清单。"""

    id: str
    name: str
    model: str
    mac: str = ""
    com_port: int | None = None
    device_type: str = "router"
    ports: list[Port] = field(default_factory=list)
    slot_count: int = 0

    def port(self, index: int) -> Port | None:
        """按全局序号取接口，越界返回 None。"""
        if 0 <= index < len(self.ports):
            return self.ports[index]
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "type": self.device_type,
            "com_port": self.com_port,
            "mac": self.mac,
            "ports": [p.name for p in self.ports],
        }


@dataclass(frozen=True)
class Endpoint:
    """链路的一端。port 为 None 表示序号超出该设备接口清单。"""

    device: str
    port: str | None
    index: int


@dataclass(frozen=True)
class Link:
    """一条物理连接。"""

    src: Endpoint
    dst: Endpoint
    cable: str = ""


@dataclass
class Topology:
    """解析结果。"""

    version: str
    source: str
    devices: list[Device] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def device(self, name: str) -> Device | None:
        for d in self.devices:
            if d.name == name:
                return d
        return None

    def links_of(self, name: str) -> list[Link]:
        return [l for l in self.links if name in (l.src.device, l.dst.device)]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "source": self.source,
            "devices": [d.to_dict() for d in self.devices],
            "links": [
                {
                    "src": {"device": l.src.device, "port": l.src.port},
                    "dst": {"device": l.dst.device, "port": l.dst.port},
                    "cable": l.cable,
                }
                for l in self.links
            ],
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------
# 读取与解码
# --------------------------------------------------------------------------


def _read_root(path: Path) -> ET.Element:
    raw = path.read_bytes()
    errors: list[str] = []
    for encoding in _ENCODINGS:
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        # 文件里写的是 encoding="UNICODE"，解码后统一改成 utf-8 再交给解析器
        text = re.sub(
            r'(encoding\s*=\s*)["\'][^"\']*["\']', r'\1"utf-8"', text, count=1
        )
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            errors.append(f"{encoding}: {exc}")
    raise TopoError("拓扑文件解析失败：" + "; ".join(errors))


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


# --------------------------------------------------------------------------
# 接口编号
# --------------------------------------------------------------------------


def _interface_blocks(dev_elem: ET.Element) -> list[tuple[str, str, int, str]]:
    """取出 (槽位, 前缀, 端口数) 列表，保持文件内顺序。"""

    blocks: list[tuple[str, str, int, str]] = []
    for slot_elem in dev_elem.findall("slot"):
        slot = slot_elem.get("number", "")
        for iface_elem in slot_elem.findall("interface"):
            prefix = (iface_elem.get("interfacename") or "").strip()
            sztype = (iface_elem.get("sztype") or "").strip()
            count = _int(iface_elem.get("count")) or 0
            if count <= 0:
                continue
            blocks.append((slot, prefix or sztype, count, sztype))
    return blocks


def _block_starts(
    blocks: list[tuple[str, str, int, str]], model: str, is_switch: bool
) -> list[int]:
    """每个 interface 块的起始编号。优先用实测型号表，否则按设备类型兜底。"""

    table = MODEL_PORTS.get(model.upper())
    if table and len(table) == len(blocks):
        return [start for _, start, _ in table]

    base = 1 if is_switch else 0
    starts: list[int] = []
    next_start = base
    for _, _, count, _ in blocks:
        starts.append(next_start)
        next_start += count
    return starts


def _device_type(model: str) -> str:
    upper = model.upper()
    if upper in ("PC", "STA") or upper.startswith("STA"):
        return "pc"
    if upper.startswith("S") and not upper.startswith("STA"):
        return "switch"
    return "router"


def _build_ports(dev_elem: ET.Element, model: str, device_type: str) -> list[Port]:
    blocks = _interface_blocks(dev_elem)
    starts = _block_starts(blocks, model, device_type == "switch")

    ports: list[Port] = []
    for i, (slot, prefix, count, _sztype) in enumerate(blocks):
        name_prefix = VRP_PREFIX.get(prefix, prefix)
        for k in range(count):
            ports.append(
                Port(
                    index=len(ports),
                    name=f"{name_prefix}0/0/{starts[i] + k}",
                    prefix=name_prefix,
                    slot=slot,
                    number_in_block=k,
                )
            )
    return ports


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------


def parse_topo(path: str | Path) -> Topology:
    """解析 ``.topo`` 文件，返回 :class:`Topology`。"""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"拓扑文件不存在：{path}")

    root = _read_root(path)
    if root.tag != "topo":
        raise TopoError(f"根节点不是 <topo>，实际是 <{root.tag}>")

    devices: list[Device] = []
    for dev_elem in root.findall("./devices/dev"):
        dev_id = dev_elem.get("id")
        name = dev_elem.get("name")
        model = dev_elem.get("model")
        if not (dev_id and name and model):
            continue
        dtype = _device_type(model)
        devices.append(
            Device(
                id=dev_id,
                name=name,
                model=model,
                mac=dev_elem.get("system_mac", ""),
                com_port=_int(dev_elem.get("com_port")),
                device_type=dtype,
                ports=_build_ports(dev_elem, model, dtype),
                slot_count=len(dev_elem.findall("slot")),
            )
        )

    by_id = {d.id: d for d in devices}
    # eNSP 保存时会重排设备顺序，按名字排序保证输出稳定
    devices.sort(key=lambda d: d.name)
    links: list[Link] = []
    warnings: list[str] = []

    for line_elem in root.findall("./lines/line"):
        src_id = line_elem.get("srcDeviceID")
        dst_id = line_elem.get("destDeviceID")
        pair = line_elem.find("interfacePair")
        if not (src_id and dst_id and pair is not None):
            warnings.append("跳过一条缺少端点或 interfacePair 的连线")
            continue

        src_dev, dst_dev = by_id.get(src_id), by_id.get(dst_id)
        if src_dev is None or dst_dev is None:
            warnings.append(f"连线引用了未知设备：{src_id} → {dst_id}")
            continue

        src_index = _int(pair.get("srcIndex")) or 0
        dst_index = _int(pair.get("tarIndex")) or 0
        src_port = src_dev.port(src_index)
        dst_port = dst_dev.port(dst_index)
        if src_port is None:
            warnings.append(f"{src_dev.name} 没有序号 {src_index} 的接口")
        if dst_port is None:
            warnings.append(f"{dst_dev.name} 没有序号 {dst_index} 的接口")

        links.append(
            Link(
                src=Endpoint(src_dev.name, src_port.name if src_port else None, src_index),
                dst=Endpoint(dst_dev.name, dst_port.name if dst_port else None, dst_index),
                cable=pair.get("lineName", ""),
            )
        )

    # 连线顺序同样按端点排序，避免 eNSP 重排导致输出漂移
    links.sort(key=lambda l: (l.src.device, l.src.port or "", l.dst.device, l.dst.port or ""))

    return Topology(
        version=root.get("version", "unknown"),
        source=str(path),
        devices=devices,
        links=links,
        warnings=warnings,
    )


def load_topo(path: str | Path) -> dict:
    """解析并返回可直接序列化的 dict。"""

    return parse_topo(path).to_dict()


def _print_summary(requirements, path: str | Path) -> None:
    """校验通过后打印要求文件概况。"""

    devices = requirements.devices
    iface_count = sum(len(spec.interfaces) for spec in devices.values())
    vlan_count = sum(len(spec.vlans) for spec in devices.values())

    protocols: list[str] = []
    if any(iface.ip for spec in devices.values() for iface in spec.interfaces):
        protocols.append("接口 IP")
    if vlan_count:
        protocols.append("VLAN")
    if requirements.ospf is not None:
        protocols.append("OSPF")
    if requirements.mstp is not None:
        protocols.append("MSTP")
    if requirements.vrrp is not None:
        protocols.append("VRRP")
    if requirements.dhcp is not None:
        protocols.append("DHCP")

    print(f"要求文件：{Path(path).name}")
    print(f"实验：{requirements.experiment or '（未命名）'}")
    print(f"设备 {len(devices)} 台：" + "、".join(devices))
    print(f"接口 {iface_count} 个，VLAN {vlan_count} 个")
    print("协议：" + ("、".join(protocols) if protocols else "（无）"))
    print("校验通过。")


def _main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文输出会乱码
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="解析 eNSP .topo，输出设备/接口/连线")
    parser.add_argument("topo", nargs="?", help=".topo 文件路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是表格")
    parser.add_argument("--req", help="requirements.yaml，给出后输出每台设备的命令")
    parser.add_argument("--out", help="输出 .docx 路径（需要同时给 --req）")
    parser.add_argument("--validate", action="store_true", help="只校验 requirements.yaml，不解析拓扑")
    parser.add_argument("--ai-config", help="ai.yaml，配合 --ai-input 把要求原文转成 YAML")
    parser.add_argument("--ai-input", help="要求原文文件（.md/.txt），用 AI 转成 YAML")
    parser.add_argument("--ai-out", help="AI 生成的 YAML 路径（默认 requirements.generated.yaml）")
    args = parser.parse_args(argv)

    if args.ai_input:
        if not args.ai_config:
            print("错误：--ai-input 需要配合 --ai-config 使用", file=sys.stderr)
            return 1
        from labgen.ai import AiError, convert_requirements, load_ai_config
        from labgen.requirements import RequirementError, load_requirements

        try:
            ai_config = load_ai_config(args.ai_config)
            source = Path(args.ai_input).read_text(encoding="utf-8")
            yaml_text = convert_requirements(ai_config, source)
        except (FileNotFoundError, AiError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

        target = Path(args.ai_out or "requirements.generated.yaml")
        target.write_text(yaml_text, encoding="utf-8")
        print(f"已用 {ai_config.provider}（{ai_config.model}）生成：{target}")

        try:
            requirements = load_requirements(target)
        except RequirementError as exc:
            print(f"生成结果校验未通过：{exc}", file=sys.stderr)
            print("请修正后再用 --validate 复查。", file=sys.stderr)
            return 1
        _print_summary(requirements, target)
        return 0

    if args.validate:
        if not args.req:
            print("错误：--validate 需要配合 --req 使用", file=sys.stderr)
            return 1
        from labgen.requirements import RequirementError, load_requirements

        try:
            requirements = load_requirements(args.req)
        except (FileNotFoundError, RequirementError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        _print_summary(requirements, args.req)
        return 0

    if not args.topo:
        print("错误：缺少 .topo 文件路径（或用 --validate 只校验要求文件）", file=sys.stderr)
        return 1

    try:
        topo = parse_topo(args.topo)
    except (FileNotFoundError, TopoError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if args.req:
        from labgen.docx_writer import write_docx
        from labgen.generators import build_configs
        from labgen.requirements import RequirementError, load_requirements

        try:
            requirements = load_requirements(args.req)
            configs = build_configs(topo, requirements)
        except (FileNotFoundError, RequirementError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

        if args.out:
            try:
                path = write_docx(topo, requirements, configs, args.out)
            except ImportError as exc:
                print(f"错误：写出 Word 需要 python-docx（{exc}）", file=sys.stderr)
                return 1
            print(f"已生成：{path}（{len(configs)} 台设备）")
            return 0

        for name, commands in configs.items():
            print(f"===== {name} =====")
            print("\n".join(commands))
            print()
        return 0

    if args.json:
        print(json.dumps(topo.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"拓扑 {Path(args.topo).name}（版本 {topo.version}）")
    print(f"设备 {len(topo.devices)} 台，连线 {len(topo.links)} 条\n")
    for dev in topo.devices:
        print(f"[{dev.name}] {dev.model} ({dev.device_type}) 接口 {len(dev.ports)} 个")
        for port in dev.ports:
            print(f"    {port.index:>2}  {port.name}")
    print()
    for link in topo.links:
        print(
            f"{link.src.device}({link.src.port}) --{link.cable}-- "
            f"{link.dst.device}({link.dst.port})"
        )
    for warning in topo.warnings:
        print(f"警告：{warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
