from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import RequirementError, load_requirements
from labgen.topo import parse_topo

ROOT = Path(__file__).resolve().parents[1]
TOPO = ROOT / "samples" / "lab.topo"
REQ = ROOT / "samples" / "requirements.yaml"


@pytest.fixture(scope="module")
def topo():
    return parse_topo(TOPO)


@pytest.fixture(scope="module")
def req():
    return load_requirements(REQ)


def test_loads_requirements(req):
    assert req.experiment == "实验三 单区域 OSPF"
    assert set(req.devices) == {"AR1", "AR2"}
    assert req.ospf.process == 1
    assert req.ospf.auto_networks is True


def test_ip_and_ospf_commands(topo, req):
    configs = build_configs(topo, req)
    ar1 = "\n".join(configs["AR1"])
    assert ar1.startswith("system-view\nsysname AR1")
    assert "interface GigabitEthernet0/0/0" in ar1
    assert " ip address 10.0.1.1 255.255.255.0" in ar1
    assert " description to-LSW1" in ar1
    assert "ospf 1" in ar1
    assert " area 0" in ar1
    assert "  network 10.0.1.0 0.0.0.255" in ar1
    assert ar1.rstrip().endswith("return")


def test_devices_without_spec_are_skipped(topo, req):
    assert "LSW1" not in build_configs(topo, req)


def test_output_is_deterministic(topo, req):
    assert build_configs(topo, req) == build_configs(topo, req)


def test_unknown_interface_raises(topo, req):
    bad = load_requirements(REQ)
    broken = type(req)(
        experiment=bad.experiment,
        devices={
            "AR1": type(bad.devices["AR1"])(
                name="AR1",
                role="router",
                interfaces=(type(bad.devices["AR1"].interfaces[0])(
                    name="GigabitEthernet0/0/9", ip="10.9.9.1/24"
                ),),
            )
        },
        ospf=None,
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, broken)
    assert "GigabitEthernet0/0/9" in str(excinfo.value)


def test_unknown_device_raises(topo, req):
    from labgen.requirements import DeviceSpec, Requirements

    broken = Requirements(
        experiment="x",
        devices={"R99": DeviceSpec(name="R99", interfaces=())},
        ospf=None,
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, broken)
    assert "R99" in str(excinfo.value)


def test_explicit_networks_only_on_matching_device(topo, req):
    from labgen.requirements import DeviceSpec, InterfaceSpec, OspfArea, OspfSpec, Requirements

    ospf = OspfSpec(
        process=2,
        areas=(OspfArea(area=10, networks=("10.0.2.0/24",)),),
        auto_networks=False,
    )
    requirements = Requirements(
        experiment="x",
        devices={
            "AR1": DeviceSpec("AR1", "router", (InterfaceSpec("GigabitEthernet0/0/0", "10.0.1.1/24"),)),
            "AR2": DeviceSpec("AR2", "router", (InterfaceSpec("GigabitEthernet0/0/0", "10.0.2.1/24"),)),
        },
        ospf=ospf,
    )
    configs = build_configs(topo, requirements)
    assert "network 10.0.2.0 0.0.0.255" in "\n".join(configs["AR2"])
    assert "ospf" not in "\n".join(configs["AR1"])


def test_invalid_ip_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "devices:\n  AR1:\n    interfaces:\n      - {name: GE0/0/0, ip: 300.1.1.1/24}\n",
        encoding="utf-8",
    )
    with pytest.raises(RequirementError):
        load_requirements(bad)


def test_missing_name_rejected(tmp_path):
    bad = tmp_path / "bad2.yaml"
    bad.write_text("devices:\n  AR1:\n    interfaces:\n      - {ip: 10.0.1.1/24}\n", encoding="utf-8")
    with pytest.raises(RequirementError):
        load_requirements(bad)


def test_small_prefix_wildcard(topo):
    from labgen.requirements import DeviceSpec, InterfaceSpec, OspfArea, OspfSpec, Requirements

    requirements = Requirements(
        experiment="p2p",
        devices={"AR1": DeviceSpec("AR1", "router", (InterfaceSpec("GigabitEthernet0/0/0", "10.0.0.1/30"),))},
        ospf=OspfSpec(areas=(OspfArea(area=0),)),
    )
    text = "\n".join(build_configs(topo, requirements)["AR1"])
    assert "network 10.0.0.0 0.0.0.3" in text
