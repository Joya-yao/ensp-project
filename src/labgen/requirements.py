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
    "VlanSpec",
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
class VlanSpec:
    """一个 VLAN 的配置意图。"""

    id: int
    name: str | None = None


@dataclass(frozen=True)
class InterfaceSpec:
    """一个接口的配置意图。"""

    name: str
    ip: str | None = None
    description: str | None = None
    mode: str | None = None            # access / trunk
    vlan: int | None = None            # access 模式下的归属 VLAN
    allow_vlans: tuple[int, ...] = ()  # trunk 模式放行的 VLAN
    edged_port: bool = False           # MSTP 边缘端口

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
    vlans: tuple[VlanSpec, ...] = ()


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
class MstpInstance:
    """一个 MSTP 实例及其承载的 VLAN。"""

    instance: int
    vlans: tuple[int, ...] = ()


@dataclass(frozen=True)
class MstpRegion:
    """MST 域参数，同一域内所有交换机必须一致。"""

    name: str
    revision: int = 0
    instances: tuple[MstpInstance, ...] = ()


@dataclass(frozen=True)
class MstpDevice:
    """一台交换机在 MSTP 里的角色参数。"""

    priorities: dict[int, int] = field(default_factory=dict)  # 实例 → 桥优先级


@dataclass(frozen=True)
class MstpSpec:
    region: MstpRegion | None = None
    devices: dict[str, MstpDevice] = field(default_factory=dict)


@dataclass(frozen=True)
class VrrpDevice:
    """一台设备在 VRRP 备份组里的角色。"""

    priority: int = 100


@dataclass(frozen=True)
class VrrpGroup:
    """一个 VRRP 备份组。"""

    vrid: int
    interface: str
    virtual_ip: str
    devices: dict[str, VrrpDevice] = field(default_factory=dict)
    preempt: bool = True
    preempt_delay: int = 0


@dataclass(frozen=True)
class VrrpSpec:
    groups: tuple[VrrpGroup, ...] = ()


@dataclass(frozen=True)
class Requirements:
    experiment: str = ""
    devices: dict[str, DeviceSpec] = field(default_factory=dict)
    ospf: OspfSpec | None = None
    mstp: MstpSpec | None = None
    vrrp: VrrpSpec | None = None


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

    mode = raw.get("mode")
    if mode is not None and mode not in ("access", "trunk"):
        raise RequirementError(f"{device}/{name} 的 mode 只能是 access 或 trunk")

    vlan = raw.get("vlan")
    if vlan is not None and (not isinstance(vlan, int) or not 1 <= vlan <= 4094):
        raise RequirementError(f"{device}/{name} 的 vlan 应该是 1-4094 的整数")

    allow_raw = raw.get("allow_vlans") or []
    if not isinstance(allow_raw, list):
        raise RequirementError(f"{device}/{name} 的 allow_vlans 应该是列表")
    allow: list[int] = []
    for item in allow_raw:
        if not isinstance(item, int) or not 1 <= item <= 4094:
            raise RequirementError(f"{device}/{name} 的 allow_vlans 含非法 VLAN：{item!r}")
        allow.append(item)

    if mode == "access" and vlan is None:
        raise RequirementError(f"{device}/{name} 是 access 模式，必须给 vlan")
    if mode == "trunk" and not allow:
        raise RequirementError(f"{device}/{name} 是 trunk 模式，必须给 allow_vlans")
    if mode != "trunk" and allow:
        raise RequirementError(f"{device}/{name} 给了 allow_vlans，但 mode 不是 trunk")

    edged = raw.get("edged_port", False)
    if not isinstance(edged, bool):
        raise RequirementError(f"{device}/{name} 的 edged_port 应该是 true/false")

    return InterfaceSpec(
        name=name,
        ip=ip,
        description=description,
        mode=mode,
        vlan=vlan,
        allow_vlans=tuple(allow),
        edged_port=edged,
    )


def _parse_device(name: str, raw) -> DeviceSpec:
    raw = _need_mapping(raw, f"设备 {name}")

    vlans_raw = raw.get("vlans") or []
    if not isinstance(vlans_raw, list):
        raise RequirementError(f"{name}.vlans 应该是列表")
    vlans: list[VlanSpec] = []
    defined: dict[int, str] = {}
    for item in vlans_raw:
        item = _need_mapping(item, f"{name} 的 vlan")
        vid = item.get("id")
        if not isinstance(vid, int) or not 1 <= vid <= 4094:
            raise RequirementError(f"{name} 的 vlan id 应该是 1-4094 的整数：{vid!r}")
        if vid in defined:
            raise RequirementError(f"{name} 的 VLAN {vid} 重复定义")
        vname = item.get("name")
        if vname is not None and not isinstance(vname, str):
            raise RequirementError(f"{name} 的 VLAN {vid} 的 name 应该是字符串")
        defined[vid] = vname or ""
        vlans.append(VlanSpec(id=vid, name=vname))

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

        referenced: list[int] = list(iface.allow_vlans)
        if iface.vlan is not None:
            referenced.append(iface.vlan)
        for vid in referenced:
            if vid not in defined:
                raise RequirementError(
                    f"{name}/{iface.name} 引用了未定义的 VLAN {vid}；"
                    f"已定义：{sorted(defined) or '无'}"
                )

    return DeviceSpec(
        name=name, role=raw.get("role"), interfaces=interfaces, vlans=tuple(vlans)
    )


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


def _parse_mstp(raw) -> MstpSpec | None:
    if raw is None:
        return None
    raw = _need_mapping(raw, "protocols.mstp")

    region_raw = raw.get("region")
    region: MstpRegion | None = None
    if region_raw is not None:
        region_raw = _need_mapping(region_raw, "mstp.region")
        name = region_raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RequirementError("mstp.region.name 必须是非空字符串")
        if len(name) > 32:
            raise RequirementError("mstp.region.name 最长 32 个字符（VRP 限制）")

        revision = region_raw.get("revision", 0)
        if not isinstance(revision, int) or not 0 <= revision <= 65535:
            raise RequirementError("mstp.region.revision 应该是 0-65535 的整数")

        instances_raw = region_raw.get("instances") or []
        if not isinstance(instances_raw, list):
            raise RequirementError("mstp.region.instances 应该是列表")
        instances: list[MstpInstance] = []
        used_instances: set[int] = set()
        vlan_owner: dict[int, int] = {}
        for item in instances_raw:
            item = _need_mapping(item, "mstp.region.instances 的条目")
            inst = item.get("instance")
            if not isinstance(inst, int) or not 1 <= inst <= 4094:
                raise RequirementError(f"MSTP 实例号应该是 1-4094 的整数：{inst!r}")
            if inst in used_instances:
                raise RequirementError(f"MSTP 实例 {inst} 重复定义")
            used_instances.add(inst)

            vlans_raw = item.get("vlans") or []
            if not isinstance(vlans_raw, list) or not vlans_raw:
                raise RequirementError(f"MSTP 实例 {inst} 必须给非空的 vlans 列表")
            vlans: list[int] = []
            for vid in vlans_raw:
                if not isinstance(vid, int) or not 1 <= vid <= 4094:
                    raise RequirementError(f"MSTP 实例 {inst} 含非法 VLAN：{vid!r}")
                if vid in vlan_owner:
                    raise RequirementError(
                        f"VLAN {vid} 同时出现在实例 {vlan_owner[vid]} 和 {inst}，一个 VLAN 只能属于一个实例"
                    )
                vlan_owner[vid] = inst
                vlans.append(vid)
            instances.append(MstpInstance(instance=inst, vlans=tuple(vlans)))

        region = MstpRegion(name=name, revision=revision, instances=tuple(instances))

    devices_raw = raw.get("devices") or {}
    if not isinstance(devices_raw, dict):
        raise RequirementError("mstp.devices 应该是键值对（设备名 → 参数）")
    devices: dict[str, MstpDevice] = {}
    for dev_name, dev_raw in devices_raw.items():
        dev_raw = _need_mapping(dev_raw, f"mstp.devices.{dev_name}")
        prios_raw = dev_raw.get("priorities") or {}
        if not isinstance(prios_raw, dict):
            raise RequirementError(f"mstp.devices.{dev_name}.priorities 应该是键值对")
        priorities: dict[int, int] = {}
        for key, value in prios_raw.items():
            try:
                inst = int(key)
            except (TypeError, ValueError) as exc:
                raise RequirementError(
                    f"mstp.devices.{dev_name}.priorities 的键应该是实例号：{key!r}"
                ) from exc
            if not 1 <= inst <= 4094:
                raise RequirementError(
                    f"mstp.devices.{dev_name} 的实例号超出范围：{inst}"
                )
            if not isinstance(value, int) or value < 0 or value > 61440 or value % 4096:
                raise RequirementError(
                    f"mstp.devices.{dev_name} 实例 {inst} 的优先级必须是 0-61440 之间的 4096 倍数"
                )
            priorities[inst] = value
        devices[str(dev_name)] = MstpDevice(priorities=priorities)

    if region is None and not any(d.priorities for d in devices.values()):
        raise RequirementError("mstp 配置为空：至少要给 region 或设备优先级")
    return MstpSpec(region=region, devices=devices)


def _parse_vrrp(raw) -> VrrpSpec | None:
    if raw is None:
        return None
    raw = _need_mapping(raw, "protocols.vrrp")

    groups_raw = raw.get("groups") or []
    if not isinstance(groups_raw, list):
        raise RequirementError("vrrp.groups 应该是列表")

    groups: list[VrrpGroup] = []
    for item in groups_raw:
        item = _need_mapping(item, "vrrp.groups 的条目")

        vrid = item.get("vrid")
        if not isinstance(vrid, int) or not 1 <= vrid <= 255:
            raise RequirementError(f"VRRP 的 vrid 应该是 1-255 的整数：{vrid!r}")

        interface = item.get("interface")
        if not isinstance(interface, str) or not interface.strip():
            raise RequirementError(f"VRRP vrid {vrid} 必须给 interface，如 GigabitEthernet0/0/0 或 Vlanif10")

        virtual_ip = item.get("virtual_ip")
        if not isinstance(virtual_ip, str):
            raise RequirementError(f"VRRP vrid {vrid} 必须给 virtual_ip")
        try:
            ipaddress.IPv4Address(virtual_ip)
        except ValueError as exc:
            raise RequirementError(f"VRRP vrid {vrid} 的 virtual_ip 不是合法 IPv4：{virtual_ip}") from exc

        devices_raw = item.get("devices")
        if not isinstance(devices_raw, dict) or not devices_raw:
            raise RequirementError(f"VRRP vrid {vrid} 的 devices 必须是非空键值对（设备名 → 参数）")

        members: dict[str, VrrpDevice] = {}
        for dev_name, dev_raw in devices_raw.items():
            dev_raw = _need_mapping(dev_raw, f"vrrp vrid {vrid} 的设备 {dev_name}")
            priority = dev_raw.get("priority", 100)
            if not isinstance(priority, int) or not 1 <= priority <= 254:
                raise RequirementError(
                    f"VRRP vrid {vrid} 设备 {dev_name} 的 priority 应该是 1-254 的整数"
                )
            members[str(dev_name)] = VrrpDevice(priority=priority)
        groups.append(
            VrrpGroup(
                vrid=vrid,
                interface=interface.strip(),
                virtual_ip=virtual_ip,
                devices=members,
                preempt=_parse_bool(item.get("preempt", True), f"vrrp vrid {vrid}.preempt"),
                preempt_delay=_parse_delay(item.get("preempt_delay", 0), vrid),
            )
        )

    # 同一设备上 vrid 不能重复
    seen: dict[str, set[int]] = {}
    for group in groups:
        for dev_name in group.devices:
            bucket = seen.setdefault(dev_name, set())
            if group.vrid in bucket:
                raise RequirementError(f"{dev_name} 上 VRRP vrid {group.vrid} 重复定义")
            bucket.add(group.vrid)

    return VrrpSpec(groups=tuple(groups))


def _parse_bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise RequirementError(f"{where} 应该是 true/false")
    return value


def _parse_delay(value, vrid: int) -> int:
    if not isinstance(value, int) or not 0 <= value <= 3600:
        raise RequirementError(f"VRRP vrid {vrid} 的 preempt_delay 应该是 0-3600 的整数")
    return value


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
        mstp=_parse_mstp(protocols.get("mstp")),
        vrrp=_parse_vrrp(protocols.get("vrrp")),
    )
