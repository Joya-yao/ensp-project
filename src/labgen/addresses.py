"""地址与网关对照：纯函数，供 Word 文档和命令行表格共用。

先出表、人工确认，再生成命令。表格内容是确定性的：同样的 requirements 每次输出相同。
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

from labgen.requirements import Requirements
from labgen.topo import Topology

__all__ = [
    "AddressEntry",
    "address_entries",
    "gateway_map",
    "vlan_networks",
    "network_rows",
    "device_rows",
    "terminal_rows",
    "render_markdown",
    "render_skeleton",
]


@dataclass(frozen=True)
class AddressEntry:
    device: str
    interface: str
    ip: ipaddress.IPv4Interface
    vlan: str
    description: str

    @property
    def network(self) -> ipaddress.IPv4Network:
        return self.ip.network


def parse_ip(text: str | None) -> ipaddress.IPv4Interface | None:
    if not text:
        return None
    try:
        return ipaddress.ip_interface(text)
    except ValueError:
        return None


def _vlan_label(name: str, vlan: int | None) -> str:
    if vlan:
        return str(vlan)
    match = re.fullmatch(r"vlanif(\d+)", name, re.IGNORECASE)
    return match.group(1) if match else "—"


def address_entries(req: Requirements) -> list[AddressEntry]:
    """所有带 IP 的接口，顺序与 YAML 里的设备/接口顺序一致。"""

    entries: list[AddressEntry] = []
    for name, spec in req.devices.items():
        for iface in spec.interfaces:
            ip = parse_ip(iface.ip)
            if ip is None:
                continue
            entries.append(
                AddressEntry(
                    device=name,
                    interface=iface.name,
                    ip=ip,
                    vlan=_vlan_label(iface.name, iface.vlan),
                    description=iface.description or "—",
                )
            )
    return entries


def _network_of(req: Requirements, device: str, interface: str):
    spec = req.devices.get(device)
    if spec is None:
        return None
    for iface in spec.interfaces:
        if iface.name.lower() == interface.lower():
            ip = parse_ip(iface.ip)
            return ip.network if ip is not None else None
    return None


def gateway_map(req: Requirements, entries: list[AddressEntry]) -> dict:
    """网段 → (网关地址, 网关来源)。

    优先级：VRRP 虚拟 IP → DHCP 地址池 → 网段内 .254 → 网段内唯一地址。
    推不出来就不写，交给人工确认——宁可空着，也不能编一个网关。
    """

    gateways: dict = {}

    if req.vrrp is not None:
        for group in req.vrrp.groups:
            for device in group.devices:
                network = _network_of(req, device, group.interface)
                if network is None:
                    continue
                owner = "/".join(group.devices) or device
                gateways[network] = (
                    group.virtual_ip,
                    f"{owner} VRRP{group.vrid} 虚拟网关",
                )

    if req.dhcp is not None:
        for pool in req.dhcp.pools.values():
            if not pool.gateway:
                continue
            try:
                network = ipaddress.ip_network(pool.network, strict=False)
            except ValueError:
                continue
            gateways.setdefault(network, (pool.gateway, f"DHCP 地址池 {pool.name}"))

    addresses_by_network: dict = {}
    for entry in entries:
        addresses_by_network.setdefault(entry.network, []).append(entry.ip.ip)

    for network, addresses in addresses_by_network.items():
        if network in gateways:
            continue
        # .254 是本项目的网关约定；.1 在多设备互联时通常是对端接口，不能当网关
        match = [ip for ip in addresses if int(ip) & 0xFF == 254]
        if match:
            gateways[network] = (str(match[0]), "网段内 .254 地址")
        elif len(addresses) == 1:
            gateways[network] = (str(addresses[0]), "网段内唯一地址")

    return gateways


def vlan_networks(entries: list[AddressEntry]) -> dict[int, ipaddress.IPv4Network]:
    """VLAN → 网段，从 VlanifN 接口推。"""

    mapping: dict[int, ipaddress.IPv4Network] = {}
    for entry in entries:
        match = re.fullmatch(r"vlanif(\d+)", entry.interface, re.IGNORECASE)
        vlan = int(match.group(1)) if match else None
        if vlan is None and entry.vlan.isdigit():
            vlan = int(entry.vlan)
        if vlan:
            mapping.setdefault(vlan, entry.network)
    return mapping


def _terminal_range(network, gateway: str, members: list[AddressEntry]) -> str:
    used = {gateway} | {str(entry.ip.ip) for entry in members}
    free = [str(host) for host in network.hosts() if str(host) not in used]
    if not free:
        return "—"
    return f"{free[0]} ~ {free[-1]}（{len(free)} 个）"


def network_rows(req: Requirements) -> list[tuple[str, str, str, str, str, str]]:
    entries = address_entries(req)
    if not entries:
        return []
    gateways = gateway_map(req, entries)

    grouped: dict = {}
    for entry in entries:
        grouped.setdefault(entry.network, []).append(entry)

    rows = []
    for network in sorted(grouped, key=lambda net: int(net.network_address)):
        members = grouped[network]
        gateway, source = gateways.get(network, ("—", "需人工确认"))
        rows.append(
            (
                str(network),
                str(network.netmask),
                gateway,
                source,
                "、".join(f"{m.device}:{m.interface}={m.ip.ip}" for m in members),
                _terminal_range(network, gateway, members),
            )
        )
    return rows


def device_rows(req: Requirements) -> list[tuple[str, str, str, str, str, str, str]]:
    entries = address_entries(req)
    if not entries:
        return []
    gateways = gateway_map(req, entries)

    rows = []
    for entry in entries:
        gateway, _source = gateways.get(entry.network, ("—", ""))
        if gateway == str(entry.ip.ip):
            gateway = "本机"
        rows.append(
            (
                entry.device,
                entry.interface,
                str(entry.ip.ip),
                str(entry.network.netmask),
                entry.vlan,
                gateway,
                entry.description,
            )
        )
    return rows


def terminal_rows(topo: Topology, req: Requirements) -> list[tuple[str, ...]]:
    """PC 接在哪台交换机哪个口、属于哪个 VLAN、建议用哪个地址。"""

def terminal_rows(
    topo: Topology, req: Requirements, overrides: dict[str, dict] | None = None
) -> list[tuple[str, ...]]:
    """PC 接在哪台交换机哪个口、属于哪个 VLAN、建议用哪个地址。

    ``overrides`` 是地址表里填好的终端行（键为终端名），填了的以它为准，
    没填的按所接端口的 VLAN 自动建议，并在网关列标出来源。
    """

    overrides = overrides or {}
    entries = address_entries(req)
    gateways = gateway_map(req, entries)
    networks = vlan_networks(entries)
    used = {str(entry.ip.ip) for entry in entries} | {
        gateway for gateway, _source in gateways.values()
    }

    rows: list[tuple[str, ...]] = []
    for device in topo.devices:
        if device.device_type != "pc":
            continue

        peer_name = peer_port = None
        for link in topo.links_of(device.name):
            other = link.dst if link.src.device == device.name else link.src
            if other.device != device.name:
                peer_name, peer_port = other.device, other.port
                break
        if peer_name is None:
            continue

        where = f"{peer_name}:{peer_port or '?'}"
        vlan = None
        spec = req.devices.get(peer_name)
        if spec is not None:
            for iface in spec.interfaces:
                if iface.name.lower() == (peer_port or "").lower():
                    vlan = iface.vlan
                    break

        given = overrides.get(device.name) or {}
        given_ip = (given.get("IP") or "").strip()
        given_gateway = (given.get("网关") or "").strip()
        given_vlan = (given.get("VLAN") or "").strip()
        given_mask = (given.get("掩码") or "").strip()

        if given_ip and given_ip not in ("?", "？", "—", "-"):
            vlan_text = given_vlan or (str(vlan) if vlan is not None else "—")
            mask_text = given_mask or "—"
            gateway_text = (
                f"{given_gateway}（地址表）" if given_gateway else "（地址表未填网关）"
            )
            rows.append((device.name, where, vlan_text, given_ip, mask_text, gateway_text))
            used.add(given_ip)
            continue

        if vlan is None:
            rows.append((device.name, where, "—", "未识别（端口未划 VLAN）", "—", "—"))
            continue

        network = networks.get(vlan)
        if network is None:
            rows.append((device.name, where, str(vlan), "该 VLAN 没有三层网段", "—", "—"))
            continue

        free = next((str(host) for host in network.hosts() if str(host) not in used), None)
        if free is None:
            rows.append((device.name, where, str(vlan), "地址已用完", "—", "—"))
            continue

        used.add(free)
        gateway, source = gateways.get(network, ("—", "需人工确认"))
        gateway_text = f"{gateway}（{source}，地址表未填）"
        rows.append((device.name, where, str(vlan), free, str(network.netmask), gateway_text))

    return rows


def render_skeleton(topo: Topology, req: Requirements | None = None) -> str:
    """只有拓扑、没有 YAML 时给的空白地址表，按连线列出待填的行。"""

    title = Path(topo.source).stem if topo.source else "地址表"
    parts: list[str] = [f"# {title} 地址表（待填写）", ""]

    if topo.links:
        parts.append("## 连线")
        parts.append("")
        rows = [
            (link.src.device, link.src.port or "?", link.dst.device, link.dst.port or "?", link.cable)
            for link in topo.links
        ]
        parts.append(_markdown_table(("设备 A", "接口 A", "设备 B", "接口 B", "线缆"), rows))
        parts.append("")

    parts.append("## 设备地址（把 ? 换成实际值）")
    parts.append("")
    rows = []
    for device in topo.devices:
        if device.device_type == "pc":
            continue
        connected = {
            endpoint.port.lower()
            for link in topo.links
            for endpoint in (link.src, link.dst)
            if endpoint.device == device.name and endpoint.port
        }
        for port in device.ports:
            if port.name.lower() not in connected:
                continue
            rows.append((device.name, port.name, "?", "?", "?", "?", "—"))
    if not rows:
        rows.append(("—", "—", "?", "?", "?", "?", "拓扑里没有连线"))
    parts.append(
        _markdown_table(("设备", "接口", "IP", "掩码", "VLAN", "网关", "说明"), rows)
    )
    parts.append("")

    terminals = [
        (device.name, where)
        for device in topo.devices
        if device.device_type == "pc"
        for where in [
            next(
                (
                    f"{other.device}:{other.port}"
                    for link in topo.links_of(device.name)
                    for other in (link.dst if link.src.device == device.name else link.src,)
                    if other.device != device.name
                ),
                "未连线",
            )
        ]
    ]
    if terminals:
        parts.append("## 终端地址")
        parts.append("")
        parts.append(
            _markdown_table(("终端", "接在", "VLAN", "IP", "掩码", "网关"), [
                (name, where, "?", "?", "?", "?") for name, where in terminals
            ])
        )
        parts.append("")

    parts.append(
        "填完这张表后，可以让 AI 按它生成 requirements.yaml，或照着写进 YAML 再点校验。"
    )
    return "\n".join(parts)


def _markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(
    topo: Topology | None,
    req: Requirements,
    overrides: dict[str, dict] | None = None,
) -> str:
    """给人确认的 Markdown 表格：网段、每台设备地址、终端建议地址。"""

    parts: list[str] = [f"# {req.experiment or '地址与网关'}"]
    parts.append("")

    networks = network_rows(req)
    if networks:
        parts.append("## 网段与网关")
        parts.append("")
        parts.append(
            _markdown_table(
                ("网段", "掩码", "网关", "网关在哪", "该网段设备地址", "终端可用地址"),
                networks,
            )
        )
        parts.append("")

    devices = device_rows(req)
    if devices:
        parts.append("## 每台设备的地址")
        parts.append("")
        parts.append(
            _markdown_table(
                ("设备", "接口", "IP", "掩码", "VLAN", "网关", "说明"),
                devices,
            )
        )
        parts.append("")

    if topo is not None:
        terminals = terminal_rows(topo, req, overrides)
        if terminals:
            parts.append("## 终端建议地址")
            parts.append("")
            parts.append(
                "地址表里填了 IP 的终端以地址表为准（网关列标「地址表」）；"
                "没填的按所接端口的 VLAN 自动取号，并在网关列标「地址表未填」。"
            )
            parts.append("")
            parts.append(
                _markdown_table(
                    ("终端", "接在", "VLAN", "建议 IP", "掩码", "网关"),
                    terminals,
                )
            )
            parts.append("")

    missing = [
        name
        for name, spec in req.devices.items()
        if not any(parse_ip(iface.ip) for iface in spec.interfaces)
    ]
    if missing:
        parts.append("没有三层地址的设备（二层透传）：" + "、".join(missing))
        parts.append("")

    parts.append("确认这份表：网关和 IP 对不对？改完再生成命令。")
    return "\n".join(parts)
