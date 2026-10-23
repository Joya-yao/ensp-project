import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import RequirementError, load_requirements
from labgen.topo import parse_topo

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-vrrp.yaml"


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


def test_parses_group(req):
    group = req.vrrp.groups[0]
    assert group.vrid == 1
    assert group.interface == "GigabitEthernet0/0/0"
    assert group.virtual_ip == "10.0.1.254"
    assert group.preempt is True
    assert group.preempt_delay == 20
    assert group.devices["AR1"].priority == 120
    assert group.devices["AR2"].priority == 100


def test_master_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["AR1"])
    assert "interface GigabitEthernet0/0/0" in text
    assert " vrrp vrid 1 virtual-ip 10.0.1.254" in text
    assert " vrrp vrid 1 priority 120" in text
    assert " vrrp vrid 1 preempt-mode timer delay 20" in text


def test_interface_not_duplicated(topo, req):
    lines = build_configs(topo, req)["AR1"]
    assert lines.count("interface GigabitEthernet0/0/0") == 1


def test_backup_omits_default_priority(topo, req):
    text = "\n".join(build_configs(topo, req)["AR2"])
    assert " vrrp vrid 1 virtual-ip 10.0.1.254" in text
    assert "priority" not in text


def test_non_member_has_no_vrrp(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert "vrrp" not in text


def test_preempt_disabled(topo):
    requirements = load_yaml(
        """
devices:
  AR1:
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.1.1/24}
protocols:
  vrrp:
    groups:
      - vrid: 2
        interface: GigabitEthernet0/0/0
        virtual_ip: 10.0.1.3
        preempt: false
        devices:
          AR1: {priority: 150}
"""
    )
    text = "\n".join(build_configs(topo, requirements)["AR1"])
    assert " vrrp vrid 2 preempt-mode disable" in text
    assert "timer delay" not in text


def test_vrid_range_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  vrrp:
    groups:
      - {vrid: 300, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.3, devices: {AR1: {}}}
"""
        )


def test_priority_range_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.3, devices: {AR1: {priority: 300}}}
"""
        )


def test_bad_virtual_ip_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.999, devices: {AR1: {}}}
"""
        )


def test_empty_members_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.3, devices: {}}
"""
        )


def test_duplicate_vrid_on_same_device_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.3, devices: {AR1: {}}}
      - {vrid: 1, interface: GigabitEthernet0/0/1, virtual_ip: 10.0.2.3, devices: {AR1: {}}}
"""
        )


def test_unknown_device_in_vrrp_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.3, devices: {R99: {}}}
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "R99" in str(excinfo.value)


def test_missing_interface_on_device_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/9, virtual_ip: 10.0.1.3, devices: {AR1: {}}}
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "GigabitEthernet0/0/9" in str(excinfo.value)


def test_bool_type_enforced():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  vrrp:
    groups:
      - {vrid: 1, interface: GigabitEthernet0/0/0, virtual_ip: 10.0.1.3, preempt: "yes", devices: {AR1: {}}}
"""
        )
