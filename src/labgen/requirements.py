"""结构化要求（requirements.yaml）的读取与校验。

设计原则：写「人的意图」，不写命令。
字段说明见 REQUIREMENTS.md 第 6 节。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path

import yaml

__all__ = [
    "RequirementError",
    "InterfaceSpec",
    "DeviceSpec",
    "OspfArea",
    "OspfSpec",
    "Requirements",
    "load_requirements",
]


class RequirementError(Exception):
    """要求文件缺失字段、类型不对或自相矛盾。"""


@dataclass(frozen=True)
class InterfaceSpec:
    """一个接口的配置意图。"""

    name: str
    ip: str | None = None
    description: str | None = None

    @property
    def network(self) -> ipaddress.IPv4Network | None:
        if not self.ip:
            return None
        try:
            return ipaddress.ip_interface(self.ip).network
        except ValueError as exc:
            raise RequirementError(f"接口 {self.name} 的 IP 写法错误：{self.ip}") from exc


@dataclass(frozen=True)
class DeviceSpec:
    """一台设备的配置意图。"""

    name: str
    role: str | None = None
    interfaces: tuple[InterfaceSpec, ...] = ()


@dataclass(frozen=True)
class OspfArea:
    area: int
    networks: tuple[str, ...] = ()


@dataclass(frozen=True)
class OspfSpec:
    process: int = 1
    router_id: str | None = None
    areas: tuple[OspfArea, ...] = ()
    auto_networks: bool = True


@dataclass(frozen=True)
class Requirements:
    experiment: str = ""
    devices: dict[str, DeviceSpec] = field(default_factory=dict)
    ospf: OspfSpec | None = None


def _need_mapping(value, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RequirementError(f"{where} 应该是键值对，实际是 {type(value).__name__}")
    return value


def _parse_interface(raw, device: str) -> InterfaceSpec:
    raw = _need_mapping(raw, f"{device} 的 interface")
    name = raw.get("name")
    if not name:
        raise RequirementError(f"{device} 有一个接口缺少 name")
    ip = raw.get("ip")
    if ip is not None:
        if not isinstance(ip, str):
            raise RequirementError(f"{device}/{name} 的 ip 应该是字符串，如 10.0.1.1/24")
        try:
            ipaddress.ip_interface(ip)
        except ValueError as exc:
            raise RequirementError(f"{device}/{name} 的 IP 写法错误：{ip}") from exc
    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise RequirementError(f"{device}/{name} 的 description 应该是字符串")
    return InterfaceSpec(name=name, ip=ip, description=description)


def _parse_device(name: str, raw) -> DeviceSpec:
    raw = _need_mapping(raw, f"设备 {name}")
    interfaces_raw = raw.get("interfaces") or []
    if not isinstance(interfaces_raw, list):
        raise RequirementError(f"{name}.interfaces 应该是列表")
    interfaces = tuple(_parse_interface(item, name) for item in interfaces_raw)

    seen: set[str] = set()
    for iface in interfaces:
        key = iface.name.lower()
        if key in seen:
            raise RequirementError(f"{name} 的接口 {iface.name} 重复出现")
        seen.add(key)

    return DeviceSpec(name=name, role=raw.get("role"), interfaces=interfaces)


def _parse_ospf(raw) -> OspfSpec | None:
    if raw is None:
        return None
    raw = _need_mapping(raw, "protocols.ospf")

    process = raw.get("process", 1)
    if not isinstance(process, int) or process <= 0:
        raise RequirementError("ospf.process 应该是正整数")

    router_id = raw.get("router_id")
    if router_id is not None:
        try:
            ipaddress.IPv4Address(router_id)
        except ValueError as exc:
            raise RequirementError(f"ospf.router_id 不是合法 IPv4：{router_id}") from exc

    areas_raw = raw.get("areas") or []
    if not isinstance(areas_raw, list):
        raise RequirementError("ospf.areas 应该是列表")
    areas: list[OspfArea] = []
    for item in areas_raw:
        item = _need_mapping(item, "ospf.areas 的条目")
        area_id = item.get("area", 0)
        if not isinstance(area_id, int) or area_id < 0:
            raise RequirementError("ospf.areas[].area 应该是非负整数")
        networks = item.get("networks") or []
        if not isinstance(networks, list):
            raise RequirementError("ospf.areas[].networks 应该是列表")
        for network in networks:
            try:
                ipaddress.ip_network(network, strict=False)
            except ValueError as exc:
                raise RequirementError(f"OSPF 网段写法错误：{network}") from exc
        areas.append(OspfArea(area=area_id, networks=tuple(networks)))

    auto = raw.get("auto_networks", True)
    if not isinstance(auto, bool):
        raise RequirementError("ospf.auto_networks 应该是 true/false")

    return OspfSpec(
        process=process,
        router_id=router_id,
        areas=tuple(areas),
        auto_networks=auto,
    )


def load_requirements(path: str | Path) -> Requirements:
    """读取 ``requirements.yaml``。"""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"要求文件不存在：{path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _need_mapping(raw, "文件根节点")

    experiment = _need_mapping(raw.get("experiment"), "experiment")

    devices_raw = _need_mapping(raw.get("devices"), "devices")
    devices = {
        str(name): _parse_device(str(name), spec) for name, spec in devices_raw.items()
    }

    protocols = _need_mapping(raw.get("protocols"), "protocols")

    return Requirements(
        experiment=str(experiment.get("name", "")),
        devices=devices,
        ospf=_parse_ospf(protocols.get("ospf")),
    )
