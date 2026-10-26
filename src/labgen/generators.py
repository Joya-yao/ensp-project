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
    "bgp_commands",
    "build_configs",
    "dhcp_lines",
    "dhcp_pool_commands",
    "ip_commands",
    "link_aggregation_commands",
    "mstp_commands",
    "nat_commands",
    "ospf_commands",
    "prefix_list_commands",
    "rip_commands",
    "route_policy_commands",
    "vlan_commands",
    "vrrp_lines",
    "check_specs",
]

# VRP 各版本对 icmp-type 名字的支持不一致（有的只认数字），统一转成 type/code，
# 写错名字会让整条 rule 被拒绝，ACL 只剩 permit，表现为「规则配了但不生效」。
ICMP_TYPE_CODES = {
    "echo": "8 0",
    "echo-reply": "0 0",
    "unreachable": "3 0",
    "redirect": "5 0",
    "time-exceeded": "11 0",
    "parameter-problem": "12 0",
    "source-quench": "4 0",
}


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

    if req.rip is not None:
        for name in req.rip.devices:
            if topo.device(name) is None:
                problems.append(f"rip 配置里引用了拓扑中不存在的设备 {name}")

    if req.bgp is not None:
        for name in req.bgp.devices:
            if topo.device(name) is None:
                problems.append(f"bgp 配置里引用了拓扑中不存在的设备 {name}")

    for prefix_list in req.prefix_lists:
        if topo.device(prefix_list.device) is None:
            problems.append(
                f"prefix_list {prefix_list.name} 引用了拓扑中不存在的设备 {prefix_list.device}"
            )

    for policy in req.route_policies:
        if topo.device(policy.device) is None:
            problems.append(
                f"route_policy {policy.name} 引用了拓扑中不存在的设备 {policy.device}"
            )

    for nat in req.nats:
        device = topo.device(nat.device)
        if device is None:
            problems.append(f"nat {nat.name} 引用了拓扑中不存在的设备 {nat.device}")
            continue
        if not interface_ok(device, req.devices.get(nat.device), nat.interface):
            problems.append(f"nat {nat.name}：{nat.device} 没有可用接口 {nat.interface}")

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
        targets = acl.interfaces or ((acl.interface,) if acl.interface else ())
        for target in targets:
            if not interface_ok(device, req.devices.get(acl.device), target):
                problems.append(f"acl {acl.name}：{acl.device} 没有可用接口 {target}")

    for name, spec in req.devices.items():
        device = topo.device(name)
        if device is None:
            continue
        ports = {p.name.lower() for p in device.ports}
        for lag in spec.link_aggregations:
            for member in lag.members:
                if member.lower() not in ports:
                    problems.append(
                        f"{name} 的聚合组 {lag.id} 成员口 {member} 不在拓扑里"
                    )

    return problems


def _spec_for(name: str, req: Requirements) -> DeviceSpec | None:
    return req.devices.get(name)


def link_aggregation_commands(device: Device, spec: DeviceSpec) -> list[str]:
    """Eth-Trunk 聚合组：创建接口、模式、二层属性、成员口加入。"""

    lines: list[str] = []
    for lag in spec.link_aggregations:
        lines.append(f"interface Eth-Trunk{lag.id}")
        if lag.mode == "lacp":
            lines.append(" mode lacp")
        if lag.port_mode == "access":
            lines.append(" port link-type access")
            lines.append(f" port default vlan {lag.vlan}")
        elif lag.port_mode == "trunk":
            allowed = " ".join(str(v) for v in lag.allow_vlans)
            lines.append(" port link-type trunk")
            lines.append(f" port trunk allow-pass vlan {allowed}")
        lines.append(" quit")

        for member in lag.members:
            lines.append(f"interface {member}")
            lines.append(f" eth-trunk {lag.id}")
            lines.append(" quit")
    return lines


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
            if rule.icmp_type:
                parts.extend(
                    ["icmp-type", ICMP_TYPE_CODES.get(rule.icmp_type.lower(), rule.icmp_type)]
                )
            if rule.tcp_flag:
                parts.extend(["tcp-flag", rule.tcp_flag])
            blocks.append(" ".join(parts))
            step += 5
        blocks.append(" quit")

        targets = acl.interfaces or ((acl.interface,) if acl.interface else ())
        if acl.direction:
            for target in targets:
                apply_map.setdefault(target.lower(), []).append(
                    f" traffic-filter {acl.direction} acl {acl.acl_number}"
                )

    return blocks, apply_map


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _classful(ip: str) -> str:
    """RIP 的 network 要类式地址：10.x.x.x → 10.0.0.0。"""

    first = int(ipaddress.IPv4Address(ip)) >> 24
    if first < 128:
        bits = 8
    elif first < 192:
        bits = 16
    else:
        bits = 24
    return str(ipaddress.ip_network(f"{ip}/{bits}", strict=False).network_address)


def rip_commands(device: Device, spec: DeviceSpec, req: Requirements) -> list[str]:
    cfg = req.rip
    if cfg is None:
        return []
    if cfg.devices and device.name not in cfg.devices:
        return []

    networks: list[str] = []
    if cfg.auto_networks:
        for iface in spec.interfaces:
            address = iface.network
            if address is None:
                continue
            networks.append(_classful(str(iface.ip).split("/")[0]))
    networks.extend(_dedupe([str(ipaddress.ip_network(n, strict=False).network_address) for n in cfg.networks]))
    networks = _dedupe(networks)
    if not networks:
        return []

    lines = [f"rip {cfg.process}"]
    if cfg.version == 2:
        lines.append(" version 2")
        lines.append(" undo summary")
    for network in networks:
        lines.append(f" network {network}")
    lines.append(" quit")
    return lines


def bgp_commands(device: Device, spec: DeviceSpec, req: Requirements) -> list[str]:
    cfg = req.bgp
    if cfg is None:
        return []
    if cfg.devices and device.name not in cfg.devices:
        return []

    lines = [f"bgp {cfg.as_number}"]
    if cfg.router_id:
        lines.append(f" router-id {cfg.router_id}")

    for neighbor in cfg.neighbors:
        lines.append(f" peer {neighbor.ip} as-number {neighbor.remote_as}")
        if neighbor.description:
            lines.append(f" peer {neighbor.ip} description {neighbor.description}")

    for policy in req.route_policies:
        if policy.device == device.name and policy.apply_peer:
            lines.append(
                f" peer {policy.apply_peer} route-policy {policy.name} {policy.apply_direction}"
            )

    networks = []
    if cfg.auto_networks:
        for iface in spec.interfaces:
            if iface.network is not None:
                networks.append(iface.network)
    for network in cfg.networks:
        networks.append(ipaddress.ip_network(network, strict=False))

    for network in _dedupe(networks):
        lines.append(f" network {network.network_address} {network.netmask}")
    lines.append(" quit")
    return lines


def prefix_list_commands(device: Device, req: Requirements) -> list[str]:
    lines: list[str] = []
    for prefix_list in req.prefix_lists:
        if prefix_list.device != device.name:
            continue
        for rule in prefix_list.rules:
            network = ipaddress.ip_network(rule.prefix, strict=False)
            parts = [
                f"ip ip-prefix {prefix_list.name} index {rule.seq}",
                rule.action,
                str(network.network_address),
                str(network.prefixlen),
            ]
            if rule.greater_equal is not None:
                parts.extend(["greater-equal", str(rule.greater_equal)])
            if rule.less_equal is not None:
                parts.extend(["less-equal", str(rule.less_equal)])
            lines.append(" ".join(parts))
    return lines


def route_policy_commands(device: Device, req: Requirements) -> list[str]:
    lines: list[str] = []
    for policy in req.route_policies:
        if policy.device != device.name:
            continue
        for node in policy.nodes:
            lines.append(f"route-policy {policy.name} {node.action} node {node.seq}")
            if node.match_prefix_list:
                lines.append(f" if-match ip-prefix {node.match_prefix_list}")
            if node.match_acl is not None:
                lines.append(f" if-match acl {node.match_acl}")
            if node.apply_cost is not None:
                lines.append(f" apply cost {node.apply_cost}")
            if node.apply_local_preference is not None:
                lines.append(f" apply local-preference {node.apply_local_preference}")
            if node.apply_tag is not None:
                lines.append(f" apply tag {node.apply_tag}")
            lines.append(" quit")
    return lines


def nat_commands(device: Device, req: Requirements) -> tuple[list[str], dict[str, list[str]]]:
    """出方向 Easy IP：基本 ACL + 接口 nat outbound。"""

    blocks: list[str] = []
    apply_map: dict[str, list[str]] = {}

    for rule in req.nats:
        if rule.device != device.name:
            continue

        blocks.append(f"acl number {rule.acl_number}")
        if rule.source == "any":
            blocks.append(" rule 5 permit")
        else:
            address, wildcard = _acl_address(rule.source, req)
            blocks.append(f" rule 5 permit source {address} {wildcard}")
        blocks.append(" quit")

        apply_map.setdefault(rule.interface.lower(), []).append(
            f" nat outbound {rule.acl_number}"
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
        body.extend(link_aggregation_commands(device, spec))
        body.extend(mstp_commands(device, spec, req))
        vrrp = vrrp_lines(device, req)
        dhcp = dhcp_lines(device, req)
        acl_blocks, acl_apply = acl_commands(device, req)
        nat_blocks, nat_apply = nat_commands(device, req)
        extras: dict[str, list[str]] = {}
        for source in (vrrp, dhcp, acl_apply, nat_apply):
            for key, lines in source.items():
                extras.setdefault(key, []).extend(lines)
        covered = {iface.name.lower() for iface in spec.interfaces}

        body.extend(dhcp_pool_commands(device, req))
        body.extend(acl_blocks)
        body.extend(nat_blocks)
        body.extend(prefix_list_commands(device, req))
        body.extend(route_policy_commands(device, req))
        body.extend(ip_commands(device, spec, extras))
        body.extend(_leftover_blocks(vrrp, covered))
        body.extend(_leftover_blocks(dhcp, covered))
        body.extend(_leftover_blocks(acl_apply, covered))
        body.extend(_leftover_blocks(nat_apply, covered))
        body.extend(ospf_commands(device, spec, req))
        body.extend(rip_commands(device, spec, req))
        body.extend(bgp_commands(device, spec, req))
        if len(body) == 1:
            continue  # 只有 sysname，没有实际配置

        header = ["system-view"]
        footer = ["return"]
        configs[device.name] = header + body + footer

    return configs
