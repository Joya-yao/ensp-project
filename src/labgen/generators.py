"""把「拓扑 + 结构化要求」翻译成 VRP 命令。

每个配置类别一个生成函数，互不依赖；按设备聚合后交给文档输出。
"""

from __future__ import annotations

import ipaddress
import re

from labgen.requirements import (
    DeviceSpec,
    Requirements,
    RequirementError,
)
from labgen.topo import Device, Topology

__all__ = [
    "acl_commands",
    "build_configs",
    "dhcp_lines",
    "dhcp_pool_commands",
    "ip_commands",
    "mstp_commands",
    "ospf_commands",
    "vlan_commands",
    "vrrp_lines",
    "check_specs",
]


def _mask(address: ipaddress.IPv4Interface) -> str:
    return str(address.netmask)


_VLANIF = re.compile(r"^vlanif(\d+)$", re.IGNORECASE)


def vlanif_id(name: str) -> int | None:
    """``Vlanif10`` → 10；不是 Vlanif 就返回 None。"""

    match = _VLANIF.match(name.strip())
    return int(match.group(1)) if match else None


def interface_ok(device: Device, spec: DeviceSpec | None, name: str) -> bool:
    """接口名是否可用：物理口在拓扑里，或 Vlanif 对应的 VLAN 已定义。"""

    if any(port.name.lower() == name.strip().lower() for port in device.ports):
        return True
    vid = vlanif_id(name)
    if vid is None or spec is None:
        return False
    return any(vlan.id == vid for vlan in spec.vlans)


def check_specs(topo: Topology, req: Requirements) -> list[str]:
    """校验要求与拓扑是否对得上，返回所有问题（空列表表示没问题）。"""

    problems: list[str] = []
    for name, spec in req.devices.items():
        device = topo.device(name)
        if device is None:
            known = "、".join(d.name for d in topo.devices)
            problems.append(f"要求里的设备 {name} 不在拓扑中（拓扑有：{known}）")
            continue
        for iface in spec.interfaces:
            if interface_ok(device, spec, iface.name):
                continue
            vid = vlanif_id(iface.name)
            if vid is not None:
                problems.append(
                    f"{name} 的 {iface.name} 需要先定义 VLAN {vid}"
                )
            else:
                problems.append(
                    f"{name} 没有接口 {iface.name}（可用："
                    + "、".join(p.name for p in device.ports)
                    + "）"
                )

    if req.mstp is not None:
        for name in req.mstp.devices:
            if topo.device(name) is None:
                problems.append(f"mstp 配置里引用了拓扑中不存在的设备 {name}")

    if req.vrrp is not None:
        for group in req.vrrp.groups:
            for name in group.devices:
                device = topo.device(name)
                if device is None:
                    problems.append(
                        f"vrrp vrid {group.vrid} 引用了拓扑中不存在的设备 {name}"
                    )
                    continue
                if not interface_ok(device, req.devices.get(name), group.interface):
                    problems.append(
                        f"vrrp vrid {group.vrid}：{name} 没有可用接口 {group.interface}"
                    )

    if req.dhcp is not None:
        for name, dev_cfg in req.dhcp.devices.items():
            device = topo.device(name)
            if device is None:
                problems.append(f"dhcp 配置里引用了拓扑中不存在的设备 {name}")
                continue
            for iface in dev_cfg.interfaces:
                if not interface_ok(device, req.devices.get(name), iface):
                    problems.append(f"dhcp：{name} 没有可用接口 {iface}")

    for acl in req.acls:
        device = topo.device(acl.device)
        if device is None:
            problems.append(f"acl {acl.name} 引用了拓扑中不存在的设备 {acl.device}")
            continue
        if acl.interface and not interface_ok(
            device, req.devices.get(acl.device), acl.interface
        ):
            problems.append(
                f"acl {acl.name}：{acl.device} 没有可用接口 {acl.interface}"
            )

    return problems


def _spec_for(name: str, req: Requirements) -> DeviceSpec | None:
    return req.devices.get(name)


def vlan_commands(device: Device, spec: DeviceSpec) -> list[str]:
    """VLAN 创建与命名。"""

    lines: list[str] = []
    for vlan in spec.vlans:
        lines.append(f"vlan {vlan.id}")
        if vlan.name:
            lines.append(f" name {vlan.name}")
        lines.append(" quit")
    return lines


def ip_commands(
    device: Device,
    spec: DeviceSpec,
    extras: dict[str, list[str]] | None = None,
) -> list[str]:
    """接口 IP、描述、二层端口模式，以及挂在该接口下的协议行（如 VRRP）。"""

    extras = extras or {}
    lines: list[str] = []
    for iface in spec.interfaces:
        key = iface.name.lower()
        extra_lines = extras.get(key, [])
        if not (iface.ip or iface.description or iface.mode or iface.edged_port or extra_lines):
            continue
        lines.append(f"interface {iface.name}")
        if iface.description:
            lines.append(f" description {iface.description}")
        if iface.ip:
            address = ipaddress.ip_interface(iface.ip)
            lines.append(f" ip address {address.ip} {_mask(address)}")
        if iface.mode == "access":
            lines.append(" port link-type access")
            lines.append(f" port default vlan {iface.vlan}")
        elif iface.mode == "trunk":
            allowed = " ".join(str(v) for v in iface.allow_vlans)
            lines.append(" port link-type trunk")
            lines.append(f" port trunk allow-pass vlan {allowed}")
        if iface.edged_port:
            lines.append(" stp edged-port enable")
        lines.extend(extra_lines)
        lines.append(" quit")
    return lines


def _device_networks(device: Device, spec: DeviceSpec) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    for iface in spec.interfaces:
        net = iface.network
        if net is not None and net not in nets:
            nets.append(net)
    return nets


def ospf_commands(device: Device, spec: DeviceSpec, req: Requirements) -> list[str]:
    """OSPF 进程、区域与 network 宣告。"""

    cfg = req.ospf
    if cfg is None:
        return []

    device_nets = _device_networks(device, spec)
    if not device_nets:
        return []

    # 自动模式：设备上每个有 IP 的网段都宣告进第一个区域
    if cfg.auto_networks:
        area_id = cfg.areas[0].area if cfg.areas else 0
        declarations = [(area_id, net) for net in device_nets]
    else:
        declarations = []
        for area in cfg.areas:
            for network in area.networks:
                net = ipaddress.ip_network(network, strict=False)
                if net in device_nets:
                    declarations.append((area.area, net))
        if not declarations:
            return []

    header = f"ospf {cfg.process}"
    if cfg.router_id:
        header += f" router-id {cfg.router_id}"

    lines = [header]
    last_area: int | None = None
    for area_id, net in declarations:
        if area_id != last_area:
            if last_area is not None:
                lines.append(" quit")
            lines.append(f" area {area_id}")
            last_area = area_id
        lines.append(f"  network {net.network_address} {net.hostmask}")
    if last_area is not None:
        lines.append(" quit")
    lines.append(" quit")
    return lines


def mstp_commands(device: Device, spec: DeviceSpec, req: Requirements) -> list[str]:
    """MSTP：模式、域参数、实例与桥优先级。只对交换机生效。"""

    cfg = req.mstp
    if cfg is None or device.device_type != "switch":
        return []

    dev_cfg = cfg.devices.get(device.name)
    has_priority = bool(dev_cfg and dev_cfg.priorities)
    if cfg.region is None and not has_priority:
        return []

    lines = ["stp mode mstp"]
    if cfg.region is not None:
        lines.append("stp region-configuration")
        lines.append(f" region-name {cfg.region.name}")
        if cfg.region.revision:
            lines.append(f" revision-level {cfg.region.revision}")
        for instance in cfg.region.instances:
            vlans = " ".join(str(v) for v in instance.vlans)
            lines.append(f" instance {instance.instance} vlan {vlans}")
        lines.append(" active region-configuration")
        lines.append(" quit")

    if has_priority:
        for instance_id, priority in sorted(dev_cfg.priorities.items()):
            lines.append(f"stp instance {instance_id} priority {priority}")
    return lines


def vrrp_lines(device: Device, req: Requirements) -> dict[str, list[str]]:
    """VRRP 命令行，按接口分组（键为接口名小写）。"""

    cfg = req.vrrp
    if cfg is None:
        return {}

    per_interface: dict[str, list[str]] = {}
    for group in cfg.groups:
        member = group.devices.get(device.name)
        if member is None:
            continue
        lines = per_interface.setdefault(group.interface.lower(), [])
        lines.append(f" vrrp vrid {group.vrid} virtual-ip {group.virtual_ip}")
        if member.priority != 100:
            lines.append(f" vrrp vrid {group.vrid} priority {member.priority}")
        if not group.preempt:
            lines.append(f" vrrp vrid {group.vrid} preempt-mode disable")
        elif group.preempt_delay:
            lines.append(
                f" vrrp vrid {group.vrid} preempt-mode timer delay {group.preempt_delay}"
            )
    return per_interface


def dhcp_lines(device: Device, req: Requirements) -> dict[str, list[str]]:
    """接口下的 DHCP 命令行，键为接口名小写。"""

    cfg = req.dhcp
    if cfg is None:
        return {}
    dev_cfg = cfg.devices.get(device.name)
    if dev_cfg is None:
        return {}
    return {iface.lower(): [" dhcp select global"] for iface in dev_cfg.interfaces}


def dhcp_pool_commands(device: Device, req: Requirements) -> list[str]:
    """DHCP 使能与全局地址池。"""

    cfg = req.dhcp
    if cfg is None:
        return []
    dev_cfg = cfg.devices.get(device.name)
    if dev_cfg is None or not (dev_cfg.pools or dev_cfg.interfaces):
        return []

    lines = ["dhcp enable"]
    for pool_name in dev_cfg.pools:
        pool = cfg.pools[pool_name]
        net = ipaddress.ip_network(pool.network, strict=False)
        lines.append(f"ip pool {pool.name}")
        lines.append(f" network {net.network_address} mask {net.netmask}")
        if pool.gateway:
            lines.append(f" gateway-list {pool.gateway}")
        if pool.dns:
            lines.append(" dns-list " + " ".join(pool.dns))
        if pool.lease_days:
            lines.append(f" lease day {pool.lease_days}")
        lines.append(" quit")
    return lines


def _leftover_blocks(mapping: dict[str, list[str]], covered: set[str]) -> list[str]:
    """把没写进设备接口清单的接口块补出来。"""

    out: list[str] = []
    for interface, lines in mapping.items():
        if interface in covered:
            continue
        out.append(f"interface {interface}")
        out.extend(lines)
        out.append(" quit")
    return out


def _acl_address(value: str, req: Requirements) -> tuple[str, str]:
    """把部门 key 或 CIDR 变成 (网络地址, 反掩码)。"""

    if value in req.departments:
        value = req.departments[value].subnet or ""
    network = ipaddress.ip_network(value, strict=False)
    return str(network.network_address), str(network.hostmask)


def acl_commands(
    device: Device, req: Requirements
) -> tuple[list[str], dict[str, list[str]]]:
    """生成该设备上的 ACL 定义，以及「接口 → traffic-filter」映射。"""

    blocks: list[str] = []
    apply_map: dict[str, list[str]] = {}

    for acl in req.acls:
        if acl.device != device.name:
            continue

        blocks.append(f"acl number {acl.acl_number}")
        step = 5
        for rule in acl.rules:
            parts = [f" rule {step}", rule.action, rule.protocol]
            if rule.source != "any":
                address, wildcard = _acl_address(rule.source, req)
                parts.extend(["source", address, wildcard])
            if rule.destination != "any":
                address, wildcard = _acl_address(rule.destination, req)
                parts.extend(["destination", address, wildcard])
            if rule.destination_port is not None:
                parts.extend(["destination-port", "eq", str(rule.destination_port)])
            blocks.append(" ".join(parts))
            step += 5
        blocks.append(" quit")

        if acl.interface and acl.direction:
            apply_map.setdefault(acl.interface.lower(), []).append(
                f" traffic-filter {acl.direction} acl {acl.acl_number}"
            )

    return blocks, apply_map


def build_configs(topo: Topology, req: Requirements) -> dict[str, list[str]]:
    """按拓扑顺序为每台设备生成完整命令块。"""

    problems = check_specs(topo, req)
    if problems:
        raise RequirementError("要求与拓扑不一致：\n- " + "\n- ".join(problems))

    configs: dict[str, list[str]] = {}
    for device in topo.devices:
        spec = _spec_for(device.name, req)
        if spec is None:
            continue

        body: list[str] = [f"sysname {device.name}"]
        body.extend(vlan_commands(device, spec))
        body.extend(mstp_commands(device, spec, req))
        vrrp = vrrp_lines(device, req)
        dhcp = dhcp_lines(device, req)
        acl_blocks, acl_apply = acl_commands(device, req)
        extras: dict[str, list[str]] = {}
        for source in (vrrp, dhcp, acl_apply):
            for key, lines in source.items():
                extras.setdefault(key, []).extend(lines)
        covered = {iface.name.lower() for iface in spec.interfaces}

        body.extend(dhcp_pool_commands(device, req))
        body.extend(acl_blocks)
        body.extend(ip_commands(device, spec, extras))
        body.extend(_leftover_blocks(vrrp, covered))
        body.extend(_leftover_blocks(dhcp, covered))
        body.extend(_leftover_blocks(acl_apply, covered))
        body.extend(ospf_commands(device, spec, req))
        if len(body) == 1:
            continue  # 只有 sysname，没有实际配置

        header = ["system-view"]
        footer = ["return"]
        configs[device.name] = header + body + footer

    return configs
