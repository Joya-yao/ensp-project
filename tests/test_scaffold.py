import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import load_requirements
from labgen.scaffold import (
    DevicePlan,
    Group,
    GroupsSpec,
    ScaffoldError,
    build_groups_draft,
    expand_groups,
    load_groups,
)
from labgen.topo import _main

REQ_TEXT = """
课程设计：某中小企业网络规划
市场部（约65人，位于1楼）、财务部（约30人，位于2楼）
网络需实现部门间隔离。
"""


def write_tmp(text, suffix=".yaml"):
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fh:
        fh.write(text)
        return Path(fh.name)


def test_draft_guesses_groups(topo):
    draft = build_groups_draft(topo, REQ_TEXT)
    assert "市场部" in draft
    assert "财务部" in draft
    assert "size: 65" in draft
    assert "LSW1" in draft
    assert "vlan_start: 10" in draft


def test_draft_without_text_has_todo(topo):
    draft = build_groups_draft(topo)
    assert "# TODO" in draft
    assert "groups:" in draft


def test_draft_ignores_clauses_around_department_names(topo):
    text = """
    接入交换机分别是销售部、后勤部、财务部、研发部。
    其他人不能访问财务部，但是财务部可以访问其他部门。
    """
    draft = build_groups_draft(topo, text)
    names = [
        line.split(":", 1)[1].strip()
        for line in draft.splitlines()
        if line.strip().startswith("- name:")
    ]
    assert names == ["销售部", "后勤部", "财务部", "研发部"]
 

def test_load_groups_ok():
    path = write_tmp(
        """
experiment: 测试
groups:
  - {name: 市场部, size: 65, floor: 1}
  - {name: 财务部, size: 30, vlans: [30]}
devices:
  LSW1: {group: 市场部, layer: access}
scaffold: {vlan_start: 10, vlan_step: 10}
"""
    )
    try:
        spec = load_groups(path)
    finally:
        path.unlink(missing_ok=True)
    assert [g.name for g in spec.groups] == ["市场部", "财务部"]
    assert spec.devices["LSW1"].group == "市场部"


def test_load_groups_rejects_unknown_group_ref():
    path = write_tmp(
        """
groups: [{name: 市场部}]
devices:
  LSW1: {group: 不存在的组}
"""
    )
    try:
        with pytest.raises(ScaffoldError):
            load_groups(path)
    finally:
        path.unlink(missing_ok=True)


def test_expand_assigns_vlans_and_gateways(topo):
    spec = GroupsSpec(
        experiment="中小企业网络",
        groups=(Group("市场部", size=65), Group("财务部", size=30)),
        devices={"LSW1": DevicePlan("LSW1", group="市场部", layer="access")},
    )
    text = expand_groups(spec, topo)
    assert "g1_10:" in text
    assert "subnet: 10.10.0.0/24" in text
    assert "g2_20:" in text
    assert "Vlanif10" in text
    assert "ip: 10.10.0.254/24" in text
    assert "department: 市场部" in text


def test_expanded_yaml_is_valid(topo, tmp_path):
    spec = GroupsSpec(
        experiment="中小企业网络",
        groups=(Group("市场部"), Group("财务部")),
        devices={"LSW1": DevicePlan("LSW1", group="市场部", layer="access")},
    )
    path = tmp_path / "requirements.yaml"
    path.write_text(expand_groups(spec, topo), encoding="utf-8")

    req = load_requirements(path)
    assert "g1_10" in req.departments
    assert req.devices["LSW1"].vlans[0].id == 10
    commands = build_configs(topo, req)["LSW1"]
    assert "interface Vlanif10" in "\n".join(commands)


def test_expand_rejects_unknown_device(topo):
    spec = GroupsSpec(
        experiment="x",
        groups=(Group("市场部"),),
        devices={"R99": DevicePlan("R99", group="市场部")},
    )
    with pytest.raises(ScaffoldError):
        expand_groups(spec, topo)


def test_cli_scaffold_writes_draft(topo_path, tmp_path):
    groups = tmp_path / "groups.yaml"
    code = _main([str(topo_path), "--scaffold-out", str(groups)])
    assert code == 0
    text = groups.read_text(encoding="utf-8")
    assert "groups:" in text
    assert "devices:" in text


def test_cli_build_and_overwrite_guard(topo_path, tmp_path):
    groups = tmp_path / "groups.yaml"
    groups.write_text(
        "groups: [{name: 市场部, size: 10}]\n"
        "devices: {LSW1: {group: 市场部, layer: access}}\n",
        encoding="utf-8",
    )
    built = tmp_path / "requirements.yaml"

    code = _main(
        [str(topo_path), "--build-req", str(groups), "--build-out", str(built)]
    )
    assert code == 0
    assert built.is_file()
    assert "interface Vlanif10" not in built.read_text(encoding="utf-8")  # 展开文件里是 YAML

    code = _main(
        [str(topo_path), "--build-req", str(groups), "--build-out", str(built)]
    )
    assert code == 1  # 不加 --force 拒绝覆盖

    code = _main(
        [str(topo_path), "--build-req", str(groups), "--build-out", str(built), "--force"]
    )
    assert code == 0
