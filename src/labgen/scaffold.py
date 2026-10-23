"""两组文件的工作流：先出 groups.yaml 骨架，再展开成 requirements.yaml。

骨架只放「分组」这类必须由人确认的信息；VLAN 号、网段、网关这类机械推导由展开步骤完成。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from labgen.topo import Topology

__all__ = [
    "ScaffoldError",
    "Group",
    "DevicePlan",
    "GroupsSpec",
    "build_groups_draft",
    "load_groups",
    "expand_groups",
]


class ScaffoldError(Exception):
    """骨架文件缺失字段或取值不合法。"""


@dataclass(frozen=True)
class Group:
    name: str
    size: int | None = None
    floor: int | None = None
    vlans: tuple[int, ...] = ()


@dataclass(frozen=True)
class DevicePlan:
    name: str
    group: str | None = None
    layer: str | None = None


@dataclass(frozen=True)
class GroupsSpec:
    experiment: str = ""
    groups: tuple[Group, ...] = ()
    devices: dict[str, DevicePlan] = field(default_factory=dict)
    vlan_start: int = 10
    vlan_step: int = 10


_GROUP_NAME = re.compile(r"([\u4e00-\u9fa5]{2,6}(?:部|组|中心|科|室))")


def _guess_groups(text: str) -> list[tuple[str, int | None]]:
    """从要求原文里猜分组名和人数，猜不到就返回空列表。"""

    found: list[tuple[str, int | None]] = []
    seen: set[str] = set()
    for match in _GROUP_NAME.finditer(text):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        tail = text[match.end(): match.end() + 20]
        size_match = re.search(r"(\d{1,3})\s*人", tail)
        found.append((name, int(size_match.group(1)) if size_match else None))
    return found


def build_groups_draft(topo: Topology, req_text: str | None = None) -> str:
    """根据拓扑（和要求原文）生成 groups.yaml 草稿。"""

    title = "未命名实验"
    guessed: list[tuple[str, int | None]] = []
    if req_text:
        for line in req_text.splitlines():
            line = line.strip().lstrip("\ufeff").lstrip("#").strip()
            if line:
                title = line[:40]
                break
        guessed = _guess_groups(req_text)

    lines: list[str] = [
        "# 骨架文件：只填分组和设备归属，不用写 VLAN / 网段 / 网关。",
        "# 改完执行：run.py --build-req groups.yaml --topo <你的拓扑.topo> -o requirements.yaml",
        "",
        f'experiment: "{title}"',
        "",
        "groups:",
    ]
    if guessed:
        for name, size in guessed:
            lines.append(f"  - name: {name}")
            lines.append(f"    size: {size if size is not None else 0}   # TODO: 人数，用来估算网段大小")
            lines.append("    floor: 0            # TODO: 所在楼层，没有就留 0")
            lines.append("    vlans: []           # TODO: 空=自动分配；要拆分有线/无线就写 [10, 11]")
    else:
        lines.append("  # TODO: 没从原文里认出分组，照下面格式手填")
        lines.append("  # - name: 市场部")
        lines.append("  #   size: 65")
        lines.append("  #   floor: 1")
        lines.append("  #   vlans: []")

    lines += ["", "devices:"]
    for device in topo.devices:
        if device.device_type == "pc":
            continue
        lines.append(f"  {device.name}:")
        lines.append("    group: \"\"            # TODO: 填承载哪个分组")
        lines.append("    layer: \"\"            # TODO: core / aggregation / access")

    lines += [
        "",
        "scaffold:",
        "  vlan_start: 10          # 第一个自动分配的 VLAN 号",
        "  vlan_step: 10           # 每组间隔",
        "",
    ]
    return "\n".join(lines)


def _need_mapping(value, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ScaffoldError(f"{where} 应该是键值对")
    return value


def load_groups(path: str | Path) -> GroupsSpec:
    """读取并校验 groups.yaml。"""

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"骨架文件不存在：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _need_mapping(raw, "文件根节点")

    groups_raw = raw.get("groups") or []
    if not isinstance(groups_raw, list):
        raise ScaffoldError("groups 应该是列表")
    groups: list[Group] = []
    names: set[str] = set()
    for item in groups_raw:
        item = _need_mapping(item, "groups 的条目")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ScaffoldError("每个分组都要有 name")
        name = name.strip()
        if name in names:
            raise ScaffoldError(f"分组 {name} 重复")
        names.add(name)

        size = item.get("size") or None
        if size is not None and (not isinstance(size, int) or size < 0):
            raise ScaffoldError(f"分组 {name} 的 size 应该是非负整数")
        floor = item.get("floor") or None
        if floor is not None and (not isinstance(floor, int) or floor < 0):
            raise ScaffoldError(f"分组 {name} 的 floor 应该是非负整数")

        vlans_raw = item.get("vlans") or []
        if not isinstance(vlans_raw, list):
            raise ScaffoldError(f"分组 {name} 的 vlans 应该是列表")
        vlans: list[int] = []
        for vid in vlans_raw:
            if not isinstance(vid, int) or not 1 <= vid <= 254:
                raise ScaffoldError(f"分组 {name} 的 VLAN 号应该是 1-254 的整数")
            vlans.append(vid)
        groups.append(Group(name=name, size=size, floor=floor, vlans=tuple(vlans)))

    devices_raw = _need_mapping(raw.get("devices"), "devices")
    plans: dict[str, DevicePlan] = {}
    for name, item in devices_raw.items():
        item = _need_mapping(item, f"devices.{name}")
        group = item.get("group") or None
        if group is not None and group not in names:
            raise ScaffoldError(f"设备 {name} 引用了未定义的分组 {group}")
        layer = item.get("layer") or None
        if layer is not None and layer not in ("core", "aggregation", "access"):
            raise ScaffoldError(f"设备 {name} 的 layer 只能是 core/aggregation/access")
        plans[str(name)] = DevicePlan(name=str(name), group=group, layer=layer)

    scaffold = _need_mapping(raw.get("scaffold"), "scaffold")
    start = scaffold.get("vlan_start", 10)
    step = scaffold.get("vlan_step", 10)
    if not isinstance(start, int) or not 1 <= start <= 254:
        raise ScaffoldError("scaffold.vlan_start 应该是 1-254 的整数")
    if not isinstance(step, int) or not 1 <= step <= 100:
        raise ScaffoldError("scaffold.vlan_step 应该是 1-100 的整数")

    if not groups:
        raise ScaffoldError("groups 为空：至少填一个分组")

    return GroupsSpec(
        experiment=str(raw.get("experiment") or ""),
        groups=tuple(groups),
        devices=plans,
        vlan_start=start,
        vlan_step=step,
    )


def _assign_vlans(spec: GroupsSpec) -> dict[str, tuple[int, ...]]:
    used: set[int] = set()
    for group in spec.groups:
        used.update(group.vlans)

    cursor = spec.vlan_start
    assigned: dict[str, tuple[int, ...]] = {}
    for index, group in enumerate(spec.groups):
        if group.vlans:
            assigned[group.name] = group.vlans
            continue
        while cursor in used:
            cursor += spec.vlan_step
        if cursor > 254:
            raise ScaffoldError(f"VLAN 号不够分配了（已用到 {cursor}），请把 vlan_start 调小")
        assigned[group.name] = (cursor,)
        used.add(cursor)
        cursor += spec.vlan_step
    return assigned


def _subnet(vlan: int) -> str:
    return f"10.{vlan}.0.0/24"


def _gateway(vlan: int) -> str:
    return f"10.{vlan}.0.254/24"


def expand_groups(spec: GroupsSpec, topo: Topology) -> str:
    """把骨架展开成 requirements.yaml 文本。"""

    vlans = _assign_vlans(spec)
    known_devices = {d.name for d in topo.devices}

    for name in spec.devices:
        if name not in known_devices:
            raise ScaffoldError(f"devices 里的 {name} 不在拓扑中")

    lines: list[str] = [
        "# 由 groups.yaml 展开生成。可以直接改，但重新展开会覆盖（除非换个文件名）。",
        "# 标 TODO 的地方需要人工确认，其余是确定性推导。",
        "",
        "experiment:",
        f'  name: "{spec.experiment}"',
        "",
        "departments:",
    ]
    for index, group in enumerate(spec.groups, start=1):
        for vlan in vlans[group.name]:
            lines.append(f"  g{index}_{vlan}:")
            lines.append(f"    name: {group.name}")
            lines.append(f"    subnet: {_subnet(vlan)}")
    lines.append("")

    lines.append("devices:")
    for device in topo.devices:
        plan = spec.devices.get(device.name)
        if plan is None:
            continue
        if plan.group:
            dept = plan.group
            group_vlans = vlans[dept]
            lines.append(f"  {device.name}:")
            lines.append(f"    role: {device.device_type}")
            lines.append(f"    department: {dept}")
            if plan.layer:
                lines.append(f"    layer: {plan.layer}")
            lines.append("    vlans:")
            for vlan in group_vlans:
                lines.append(f"      - {{id: {vlan}, name: {dept}}}")
            lines.append("    interfaces:")
            for vlan in group_vlans:
                lines.append(f"      - name: Vlanif{vlan}      # TODO: 不是网关就别留这一行")
                lines.append(f"        ip: {_gateway(vlan)}")
            lines.append("      # TODO: 物理口归属，例如")
            if group_vlans:
                lines.append(
                    f"      # - {{name: {device.ports[0].name if device.ports else 'GigabitEthernet0/0/1'}, mode: access, vlan: {group_vlans[0]}}}"
                )
            lines.append("")
        else:
            lines.append(f"  {device.name}:")
            lines.append(f"    role: {device.device_type}")
            lines.append("    # TODO: 这台设备承载哪个分组，填了才会生成 VLAN 和网关")
            lines.append("")

    lines += [
        "protocols:",
        "  ospf:",
        "    process: 1",
        "    areas:",
        "      - {area: 0}",
        "    auto_networks: true",
        "",
        "# TODO: 需要生成树时取消注释并确认根桥",
        "#  mstp:",
        "#    region: {name: RG-1, revision: 1}",
        "#    instances:",
        "#      - {instance: 1, vlans: [10]}",
        "",
        "# TODO: 需要网关冗余时取消注释，确认 vrid / 虚拟 IP / 优先级",
        "#  vrrp:",
        "#    groups:",
        "#      - {vrid: 10, interface: Vlanif10, virtual_ip: 10.10.0.1,",
        "#         devices: {LSW1: {priority: 120}, LSW2: {priority: 100}}}",
        "",
        "# TODO: 需要部门隔离时取消注释",
        "#  acl:",
        "#    - name: guard",
        "#      device: LSW1",
        "#      apply: {interface: Vlanif10, direction: inbound}",
        "#      rules:",
        "#        - {action: deny, source: any, destination: g1_10}",
        "",
    ]
    return "\n".join(lines)
