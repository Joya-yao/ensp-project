import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs, check_specs
from labgen.requirements import RequirementError, load_requirements

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-vlanif.yaml"


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


def test_vlanif_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert "interface Vlanif10" in text
    assert " ip address 10.10.0.254 255.255.255.0" in text
    assert "interface Vlanif20" in text


def test_ospf_runs_on_vlanif(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert "ospf 1" in text
    assert " network 10.10.0.0 0.0.0.255" in text


def test_vrrp_on_vlanif(topo, req):
    text = "\n".join(build_configs(topo, req)["LSW1"])
    assert " vrrp vrid 10 virtual-ip 10.10.0.1" in text
    assert " traffic" not in text


def test_vlanif_without_vlan_rejected():
    with pytest.raises(RequirementError) as excinfo:
        load_yaml(
            """
devices:
  LSW1:
    interfaces:
      - {name: Vlanif99, ip: 10.99.0.1/24}
"""
        )
    assert "VLAN 99" in str(excinfo.value)


def test_vlanif_does_not_need_physical_port(topo, req):
    assert check_specs(topo, req) == []


def test_physical_port_still_checked(topo, req):
    broken = load_yaml(
        """
devices:
  LSW1:
    vlans: [{id: 10, name: a}]
    interfaces:
      - {name: GigabitEthernet0/0/30, ip: 10.0.9.1/24}
"""
    )
    problems = check_specs(topo, broken)
    assert any("GigabitEthernet0/0/30" in p for p in problems)
