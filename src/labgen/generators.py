"""把「拓扑 + 结构化要求」翻译成 VRP 命令。

每个配置类别一个生成函数，互不依赖；按设备聚合后交给文档输出。
"""

from __future__ import annotations

import ipaddress

from labgen.requirements import (
    DeviceSpec,
    Requirements,
    RequirementError,
)
from labgen.topo import Device, Topology

__all__ = ["build_configs", "ip_commands", "ospf_commands", "vlan_commands", "check_specs"]


def _mask(address: ipaddress.IPv4Interface) -> str:
    return str(address.netmask)


def check_specs(topo: Topology, req: Requirements) -> list[str]:
    """校验要求与拓扑是否对得上，返回所有问题（空列表表示没问题）。"""

    problems: list[str] = []
    for name, spec in req.devices.items():
        device = topo.device(name)
        if device is None:
            known = "、".join(d.name for d in topo.devices)
            problems.append(f"要求里的设备 {name} 不在拓扑中（拓扑有：{known}）")
            continue
        available = {p.name.lower(): p.name for p in device.ports}
        for iface in spec.interfaces:
            if iface.name.lower() not in available:
                problems.append(
                    f"{name} 没有接口 {iface.name}（可用："
                    + "、".join(p.name for p in device.ports)
                    + "）"
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


def ip_commands(device: Device, spec: DeviceSpec) -> list[str]:
    """接口 IP、描述与二层端口模式。"""

    lines: list[str] = []
    for iface in spec.interfaces:
        if not (iface.ip or iface.description or iface.mode):
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
        body.extend(ip_commands(device, spec))
        body.extend(ospf_commands(device, spec, req))
        if len(body) == 1:
            continue  # 只有 sysname，没有实际配置

        header = ["system-view"]
        footer = ["return"]
        configs[device.name] = header + body + footer

    return configs
