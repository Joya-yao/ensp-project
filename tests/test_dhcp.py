import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import (
    DeviceSpec,
    DhcpDevice,
    DhcpPool,
    DhcpSpec,
    RequirementError,
    Requirements,
    load_requirements,
)
from labgen.topo import parse_topo  # noqa: F401  (conftest 里生成拓扑)

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-dhcp.yaml"


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


def test_parses_pool(req):
    pool = req.dhcp.pools["vlan10"]
    assert pool.network == "10.0.1.0/24"
    assert pool.gateway == "10.0.1.1"
    assert pool.dns == ("114.114.114.114",)
    assert pool.lease_days == 1
    assert req.dhcp.devices["AR1"].pools == ("vlan10",)


def test_server_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["AR1"])
    assert "dhcp enable" in text
    assert "ip pool vlan10" in text
    assert " network 10.0.1.0 mask 255.255.255.0" in text
    assert " gateway-list 10.0.1.1" in text
    assert " dns-list 114.114.114.114" in text
    assert " lease day 1" in text
    assert " dhcp select global" in text


def test_select_global_inside_interface_block(topo, req):
    lines = build_configs(topo, req)["AR1"]
    start = lines.index("interface GigabitEthernet0/0/0")
    end = lines.index(" quit", start)
    assert " dhcp select global" in lines[start:end]
    assert lines.count("interface GigabitEthernet0/0/0") == 1


def test_client_device_has_no_dhcp(topo, req):
    text = "\n".join(build_configs(topo, req)["AR2"])
    assert "dhcp" not in text


def test_network_written_with_mask(topo):
    pool = DhcpPool(name="p", network="192.168.5.0/24")
    requirements = Requirements(
        experiment="t",
        devices={"AR1": DeviceSpec("AR1")},
        dhcp=DhcpSpec(pools={"p": pool}, devices={"AR1": DhcpDevice(pools=("p",))}),
    )
    text = "\n".join(build_configs(topo, requirements)["AR1"])
    assert " network 192.168.5.0 mask 255.255.255.0" in text


def test_gateway_outside_network_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24, gateway: 10.0.9.1}
    devices: {}
"""
        )


def test_bad_dns_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24, dns: [8.8.8.999]}
    devices: {}
"""
        )


def test_lease_range_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24, lease_days: 0}
    devices: {}
"""
        )


def test_undefined_pool_reference_rejected():
    with pytest.raises(RequirementError) as excinfo:
        load_yaml(
            """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24}
    devices:
      AR1:
        pools: [nope]
"""
        )
    assert "nope" in str(excinfo.value)


def test_duplicate_pool_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24}
      - {name: p, network: 10.0.2.0/24}
"""
        )


def test_unknown_device_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24}
    devices:
      R99:
        pools: [p]
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "R99" in str(excinfo.value)


def test_missing_interface_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  dhcp:
    pools:
      - {name: p, network: 10.0.1.0/24}
    devices:
      AR1:
        interfaces: [GigabitEthernet0/0/9]
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "GigabitEthernet0/0/9" in str(excinfo.value)


def test_empty_dhcp_rejected():
    with pytest.raises(RequirementError):
        load_yaml("protocols:\n  dhcp: {}\n")
