from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import (
    DeviceSpec,
    InterfaceSpec,
    RequirementError,
    Requirements,
    VlanSpec,
    load_requirements,
)
from labgen.topo import parse_topo  # noqa: F401  (conftest 里生成拓扑)

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-vlan.yaml"


@pytest.fixture(scope="module")
def req():
    return load_requirements(REQ)


def test_parses_vlans(req):
    sw = req.devices["LSW1"]
    assert [(v.id, v.name) for v in sw.vlans] == [(10, "student"), (20, "teacher")]
    access = sw.interfaces[0]
    assert access.mode == "access" and access.vlan == 10
    trunk = sw.interfaces[2]
    assert trunk.mode == "trunk" and trunk.allow_vlans == (10, 20)


def test_switch_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert "vlan 10" in text and " name student" in text
    assert "vlan 20" in text and " name teacher" in text
    assert " port link-type access" in text
    assert " port default vlan 10" in text
    assert " port link-type trunk" in text
    assert " port trunk allow-pass vlan 10 20" in text


def test_routers_unaffected(topo, req):
    configs = build_configs(topo, req)
    assert " ip address 10.0.1.1 255.255.255.0" in "\n".join(configs["AR1"])
    assert "vlan" not in "\n".join(configs["AR1"])


def _req_with(interfaces, vlans=()):
    return Requirements(
        experiment="t",
        devices={"LSW1": DeviceSpec("LSW1", "switch", tuple(interfaces), tuple(vlans))},
        ospf=None,
    )


def _build(topo, requirements):
    return build_configs(topo, requirements)["LSW1"]


def test_access_without_vlan_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: access}
"""
        )


def load_yaml(text, tmp_path_factory=None):
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    try:
        return load_requirements(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_trunk_without_allow_vlans_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: trunk}
"""
        )


def test_undefined_vlan_rejected():
    with pytest.raises(RequirementError) as excinfo:
        load_yaml(
            """
devices:
  LSW1:
    vlans:
      - {id: 10, name: student}
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: access, vlan: 99}
"""
        )
    assert "99" in str(excinfo.value)


def test_duplicate_vlan_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    vlans:
      - {id: 10, name: a}
      - {id: 10, name: b}
"""
        )


def test_allow_vlans_on_access_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    vlans:
      - {id: 10, name: a}
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: access, vlan: 10, allow_vlans: [10]}
"""
        )


def test_vlan_id_out_of_range_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    vlans:
      - {id: 5000, name: bad}
"""
        )


def test_mode_typo_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  LSW1:
    interfaces:
      - {name: GigabitEthernet0/0/1, mode: acess, vlan: 10}
"""
        )
