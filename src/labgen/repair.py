"""按拓扑修正要求里的接口名。

AI 生成或手写的 YAML 常见两类错：
1. 端口类型写错：S3700 上 3 号口是 ``Ethernet0/0/3``，写成了 ``GigabitEthernet0/0/3``；
2. 端口根本不存在：S3700 只有 1-22 号 Ethernet 和两个 GE，写了 ``GigabitEthernet0/0/9``。

这里只做「同号换类型」和「整条丢弃并提示」两种修正，不改地址、不改 VLAN，也不猜端口。
修正结果和说明一起返回，由调用方决定是否采用。
"""

from __future__ import annotations

import re
from dataclasses import replace

from labgen.requirements import Requirements
from labgen.topo import Topology

__all__ = ["repair_interfaces", "suggest_interface"]

_PORT = re.compile(r"^(?P<prefix>[A-Za-z\-]+?)\s*(?P<slot>\d+)/(?P<sub>\d+)/(?P<index>\d+)$")


def _parse(name: str):
    match = _PORT.match(name.strip())
    if match is None:
        return None
    return (
        match.group("prefix").lower(),
        match.group("slot"),
        match.group("sub"),
        int(match.group("index")),
    )


def _connected_ports(topo: Topology, device: str) -> set[str]:
    ports: set[str] = set()
    for link in topo.links:
        for endpoint in (link.src, link.dst):
            if endpoint.device == device and endpoint.port:
                ports.add(endpoint.port.lower())
    return ports


def suggest_interface(topo: Topology, device: str, name: str) -> str | None:
    """找一个「槽位和序号相同、类型不同、且拓扑里确实接了线」的接口名。"""

    dev = topo.device(device)
    parsed = _parse(name)
    if dev is None or parsed is None:
        return None
    if any(port.name.lower() == name.strip().lower() for port in dev.ports):
        return None

    connected = _connected_ports(topo, device)
    if not connected:
        return None
    _prefix, slot, sub, index = parsed
    for port in dev.ports:
        other = _parse(port.name)
        if other is None:
            continue
        if other[1] == slot and other[2] == sub and other[3] == index:
            # 只换成真正接了线的端口，避免把配置落到空口上
            if port.name.lower() in connected:
                return port.name
            return None
    return None


def repair_interfaces(topo: Topology, req: Requirements) -> tuple[Requirements, list[str]]:
    """返回（修正后的要求, 说明列表）。没问题的原样返回。"""

    notes: list[str] = []
    devices = dict(req.devices)

    from labgen.generators import interface_ok  # 避免循环导入

    for name, spec in req.devices.items():
        dev = topo.device(name)
        if dev is None:
            continue
        available = {port.name.lower(): port.name for port in dev.ports}

        changed = False
        kept = []
        for iface in spec.interfaces:
            if iface.name.lower() in available or interface_ok(dev, spec, iface.name):
                kept.append(iface)
                continue

            candidate = suggest_interface(topo, name, iface.name)
            if candidate is not None:
                kept.append(replace(iface, name=candidate))
                notes.append(
                    f"{name}：{iface.name} 不存在，按同号端口改成 {candidate}"
                )
                changed = True
                continue

            notes.append(
                f"{name}：{iface.name} 在拓扑里没有对应端口，已从要求里移除"
            )
            changed = True

        if changed:
            devices[name] = replace(spec, interfaces=tuple(kept))

    return replace(req, devices=devices), notes
