import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs, check_specs
from labgen.requirements import RequirementError, load_requirements

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-lag.yaml"


@pytest.fixture(scope="module")
def req():
    return load_requirements(REQ)


def load_yaml(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    try:
        return load_requirements(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_parse_aggregation(req):
    lag = req.devices["LSW1"].link_aggregations[0]
    assert lag.id == 1
    assert lag.mode == "lacp"
    assert lag.port_mode == "trunk"
    assert lag.allow_vlans == (10, 20)
    assert lag.members == ("GigabitEthernet0/0/3", "GigabitEthernet0/0/4")


def test_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert "interface Eth-Trunk1" in text
    assert " mode lacp" in text
    assert " port link-type trunk" in text
    assert " port trunk allow-pass vlan 10 20" in text
    assert "interface GigabitEthernet0/0/3" in text
    assert " eth-trunk 1" in text
    assert text.count(" eth-trunk 1") == 2


def test_aggregation_before_members(topo, req):
    lines = build_configs(topo, req)["LSW1"]
    assert lines.index("interface Eth-Trunk1") < lines.index("interface GigabitEthernet0/0/3")


def test_unknown_member_rejected(topo):
    requirements = load_yaml(
        """
devices:
  LSW1:
    vlans: [{id: 10, name: a}]
    link_aggregation:
      - id: 1
        members: [GigabitEthernet0/0/1, GigabitEthernet0/0/99]
"""
    )
    problems = check_specs(topo, requirements)
    assert any("GigabitEthernet0/0/99" in p for p in problems)


def test_single_member_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    vlans: [{id: 10, name: a}]
    link_aggregation:
      - id: 1
        members: [GigabitEthernet0/0/1]
"""
        )


def test_duplicate_id_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    link_aggregation:
      - {id: 1, members: [GigabitEthernet0/0/1, GigabitEthernet0/0/2]}
      - {id: 1, members: [GigabitEthernet0/0/3, GigabitEthernet0/0/4]}
"""
        )


def test_member_reuse_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    link_aggregation:
      - {id: 1, members: [GigabitEthernet0/0/1, GigabitEthernet0/0/2]}
      - {id: 2, members: [GigabitEthernet0/0/2, GigabitEthernet0/0/3]}
"""
        )


def test_member_in_interfaces_rejected():
    with pytest.raises(RequirementError) as excinfo:
        load_yaml(
            """
devices:
  LSW1:
    vlans: [{id: 10, name: a}]
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: access, vlan: 10}
    link_aggregation:
      - {id: 1, members: [GigabitEthernet0/0/1, GigabitEthernet0/0/2]}
"""
        )
    assert "interfaces" in str(excinfo.value)


def test_access_mode_needs_vlan():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    link_aggregation:
      - {id: 1, port_mode: access, members: [GigabitEthernet0/0/1, GigabitEthernet0/0/2]}
"""
        )


def test_undefined_vlan_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    link_aggregation:
      - {id: 1, port_mode: trunk, allow_vlans: [30], members: [GigabitEthernet0/0/1, GigabitEthernet0/0/2]}
"""
        )


def test_bad_mode_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    link_aggregation:
      - {id: 1, mode: static, members: [GigabitEthernet0/0/1, GigabitEthernet0/0/2]}
"""
        )
