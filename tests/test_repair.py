"""接口名自动修正：同号换类型、不存在的端口移除并提示。"""

from pathlib import Path

import pytest

from labgen.repair import repair_interfaces, suggest_interface
from labgen.requirements import load_requirements
from labgen.topo import parse_topo

S3700_TOPO = """<?xml version="1.0" encoding="UNICODE" ?>
<topo version="1.3.00.100">
    <devices>
        <dev id="T-LSW3" name="LSW3" poe="0" model="S3700" settings="" system_mac="00-E0-FC-00-00-03" com_port="2002" bootmode="1" cx="0.0" cy="0.0" edit_left="0" edit_top="0">
            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="Ethernet" count="22" />
                <interface sztype="Ethernet" interfacename="GE" count="2" />
            </slot>
        </dev>
        <dev id="T-PC1" name="PC1" poe="0" model="PC" settings="" system_mac="00-E0-FC-00-00-11" com_port="2003" bootmode="1" cx="0.0" cy="0.0" edit_left="0" edit_top="0">
            <slot number="slot1" isMainBoard="0">
                <interface sztype="Ethernet" interfacename="Ethernet" count="1" />
            </slot>
        </dev>
    </devices>
    <lines>
        <line srcDeviceID="T-LSW3" destDeviceID="T-PC1">
            <interfacePair lineName="Copper" srcIndex="2" srcBoundRectIsMoved="0" srcBoundRect_X="0" srcBoundRect_Y="0" srcOffset_X="0" srcOffset_Y="0" tarIndex="0" tarBoundRectIsMoved="0" tarBoundRect_X="0" tarBoundRect_Y="0" tarOffset_X="0" tarOffset_Y="0" />
        </line>
    </lines>
    <shapes />
    <txttips />
</topo>
"""

WRONG = """
experiment: {name: 接口名修正}
devices:
  LSW3:
    role: switch
    vlans:
      - {id: 10, name: student}
    interfaces:
      - {name: GigabitEthernet0/0/3, mode: access, vlan: 10}
"""


@pytest.fixture(scope="module")
def topo(tmp_path_factory):
    path = tmp_path_factory.mktemp("topo") / "s3700.topo"
    path.write_text(S3700_TOPO, encoding="utf-8")
    return parse_topo(path)


def load_yaml(text, tmp_path):
    path = tmp_path / "r.yaml"
    path.write_text(text, encoding="utf-8")
    return load_requirements(path)


def test_s3700_port_layout(topo):
    names = [port.name for port in topo.devices[0].ports]
    assert names[0] == "Ethernet0/0/1"
    assert names[21] == "Ethernet0/0/22"
    assert names[22] == "GigabitEthernet0/0/1"


def test_suggest_only_offers_connected_ports(topo):
    # Ethernet0/0/3 在拓扑里接了 PC1，可以换
    assert suggest_interface(topo, "LSW3", "GigabitEthernet0/0/3") == "Ethernet0/0/3"
    # Ethernet0/0/5 没接线，不换
    assert suggest_interface(topo, "LSW3", "GigabitEthernet0/0/5") is None
    # 本来就有这个口
    assert suggest_interface(topo, "LSW3", "GigabitEthernet0/0/1") is None


def test_repair_renames_existing_port(topo, tmp_path):
    req = load_yaml(WRONG, tmp_path)
    fixed, notes = repair_interfaces(topo, req)
    assert [i.name for i in fixed.devices["LSW3"].interfaces] == ["Ethernet0/0/3"]
    assert any("改成 Ethernet0/0/3" in note for note in notes)


def test_repair_drops_missing_port(topo, tmp_path):
    # 30 号口在 S3700 上不存在，也没有同号的其它类型可换
    req = load_yaml(WRONG.replace("GigabitEthernet0/0/3", "GigabitEthernet0/0/30"), tmp_path)
    fixed, notes = repair_interfaces(topo, req)
    assert fixed.devices["LSW3"].interfaces == ()
    assert any("移除" in note for note in notes)


def test_repair_keeps_valid_ports_untouched(topo, tmp_path):
    req = load_yaml(WRONG.replace("GigabitEthernet0/0/3", "Ethernet0/0/1"), tmp_path)
    fixed, notes = repair_interfaces(topo, req)
    assert [i.name for i in fixed.devices["LSW3"].interfaces] == ["Ethernet0/0/1"]
    assert notes == []


def test_repaired_config_generates(topo, tmp_path):
    from labgen.generators import build_configs

    req = load_yaml(WRONG, tmp_path)
    fixed, _ = repair_interfaces(topo, req)
    configs = build_configs(topo, fixed)
    assert "interface Ethernet0/0/3" in "\n".join(configs["LSW3"])