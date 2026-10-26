import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import RequirementError, load_requirements
from labgen.topo import parse_topo  # noqa: F401  (conftest 里生成拓扑)

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-mstp.yaml"


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


def test_parses_region(req):
    assert req.mstp.region.name == "RG-1"
    assert req.mstp.region.revision == 1
    assert [(i.instance, i.vlans) for i in req.mstp.region.instances] == [
        (1, (10,)),
        (2, (20,)),
    ]
    assert req.mstp.devices["LSW1"].priorities == {1: 4096, 2: 8192}


def test_switch_gets_mstp_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert "stp mode mstp" in text
    assert "stp region-configuration" in text
    assert " region-name RG-1" in text
    assert " revision-level 1" in text
    assert " instance 1 vlan 10" in text
    assert " instance 2 vlan 20" in text
    assert " active region-configuration" in text
    assert "stp instance 1 priority 4096" in text
    assert "stp instance 2 priority 8192" in text


def test_mstp_before_interface_config(topo, req):
    lines = build_configs(topo, req)["LSW1"]
    assert lines.index("stp mode mstp") < lines.index("interface GigabitEthernet0/0/1")


def test_edged_port_emitted(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert " stp edged-port enable" in text


def test_router_has_no_mstp(topo, req):
    text = "\n".join(build_configs(topo, req)["AR1"])
    assert "stp" not in text


def test_priority_must_be_multiple_of_4096():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  mstp:
    devices:
      LSW1:
        priorities: {1: 4000}
"""
        )


def test_priority_out_of_range():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  mstp:
    devices:
      LSW1:
        priorities: {1: 65536}
"""
        )


def test_vlan_in_two_instances_rejected():
    with pytest.raises(RequirementError) as excinfo:
        load_yaml(
            """
protocols:
  mstp:
    region:
      name: RG
      instances:
        - {instance: 1, vlans: [10]}
        - {instance: 2, vlans: [10]}
"""
        )
    assert "VLAN 10" in str(excinfo.value)


def test_duplicate_instance_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  mstp:
    region:
      name: RG
      instances:
        - {instance: 1, vlans: [10]}
        - {instance: 1, vlans: [20]}
"""
        )


def test_empty_instance_vlans_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  mstp:
    region:
      name: RG
      instances:
        - {instance: 1, vlans: []}
"""
        )


def test_region_name_too_long_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  mstp:
    region:
      name: "0123456789012345678901234567890123"
      instances:
        - {instance: 1, vlans: [10]}
"""
        )


def test_unknown_device_in_mstp_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  mstp:
    devices:
      SW99:
        priorities: {1: 4096}
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "SW99" in str(excinfo.value)


def test_empty_mstp_rejected():
    with pytest.raises(RequirementError):
        load_yaml("protocols:\n  mstp: {}\n")


def test_warning_when_instances_missing():
    from labgen.generators import requirement_warnings

    req = load_yaml(
        """
devices:
  LSW1:
    role: switch
    vlans: [{id: 10, name: a}, {id: 20, name: b}]
    interfaces: [{name: GigabitEthernet0/0/1, mode: access, vlan: 10}]
protocols:
  mstp:
    region: {name: RG-1}
    devices: {LSW1: {priorities: {1: 4096}}}
"""
    )
    notes = requirement_warnings(req)
    assert any("没有配置 instances" in note for note in notes)


def test_no_warning_when_two_instances():
    from labgen.generators import requirement_warnings

    req = load_yaml(
        """
devices:
  LSW1:
    role: switch
    vlans: [{id: 10, name: a}, {id: 20, name: b}]
    interfaces: [{name: GigabitEthernet0/0/1, mode: access, vlan: 10}]
protocols:
  mstp:
    region:
      name: RG-1
      instances:
        - {instance: 1, vlans: [10]}
        - {instance: 2, vlans: [20]}
    devices: {LSW1: {priorities: {1: 4096, 2: 8192}}}
"""
    )
    assert requirement_warnings(req) == []