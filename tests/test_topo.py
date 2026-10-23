from pathlib import Path

import pytest

from labgen.topo import TopoError, load_topo, parse_topo

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "lab.topo"


@pytest.fixture(scope="module")
def topo():
    return parse_topo(SAMPLE)


def test_reads_all_devices(topo):
    assert [d.name for d in topo.devices] == ["AR1", "AR2", "LSW1"]
    assert [d.model for d in topo.devices] == ["AR2220", "AR2220", "S5700"]


def test_device_types(topo):
    assert topo.device("AR1").device_type == "router"
    assert topo.device("LSW1").device_type == "switch"


def test_router_ports_start_at_zero(topo):
    names = [p.name for p in topo.device("AR1").ports]
    assert names == [
        "GigabitEthernet0/0/0",
        "GigabitEthernet0/0/1",
        "GigabitEthernet0/0/2",
    ]


def test_switch_ports_start_at_one(topo):
    ports = topo.device("LSW1").ports
    assert len(ports) == 24
    assert ports[0].name == "GigabitEthernet0/0/1"
    assert ports[-1].name == "GigabitEthernet0/0/24"


def test_links_map_to_ports(topo):
    got = {(l.src.device, l.src.port, l.dst.device, l.dst.port) for l in topo.links}
    assert got == {
        ("LSW1", "GigabitEthernet0/0/1", "AR1", "GigabitEthernet0/0/0"),
        ("LSW1", "GigabitEthernet0/0/2", "AR2", "GigabitEthernet0/0/0"),
    }


def test_no_warnings_on_valid_file(topo):
    assert topo.warnings == []


def test_links_of(topo):
    assert len(topo.links_of("LSW1")) == 2
    assert len(topo.links_of("AR1")) == 1


def test_to_dict_is_serializable(topo):
    data = load_topo(SAMPLE)
    assert data["devices"][0]["ports"][0] == "GigabitEthernet0/0/0"
    assert data["links"][0]["src"]["device"] == "LSW1"


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_topo(SAMPLE.with_name("nope.topo"))


def test_bad_root_raises(tmp_path):
    bad = tmp_path / "bad.topo"
    bad.write_text("<not-topo/>", encoding="utf-8")
    with pytest.raises(TopoError):
        parse_topo(bad)


def test_unknown_model_falls_back(tmp_path):
    xml = """<?xml version="1.0" encoding="utf-8"?>
<topo version="1.3">
  <devices>
    <dev id="d1" name="X1" model="UNKNOWN9" system_mac="" com_port="2001">
      <slot number="slot17"><interface sztype="Ethernet" interfacename="GE" count="2"/></slot>
    </dev>
  </devices>
  <lines/>
</topo>"""
    path = tmp_path / "u.topo"
    path.write_text(xml, encoding="utf-8")
    dev = parse_topo(path).device("X1")
    assert [p.name for p in dev.ports] == [
        "GigabitEthernet0/0/0",
        "GigabitEthernet0/0/1",
    ]


def test_link_index_out_of_range_warns(tmp_path):
    xml = """<?xml version="1.0" encoding="utf-8"?>
<topo version="1.3">
  <devices>
    <dev id="d1" name="X1" model="AR2220" com_port="2001">
      <slot number="slot17"><interface sztype="Ethernet" interfacename="GE" count="1"/></slot>
    </dev>
    <dev id="d2" name="X2" model="AR2220" com_port="2002">
      <slot number="slot17"><interface sztype="Ethernet" interfacename="GE" count="1"/></slot>
    </dev>
  </devices>
  <lines>
    <line srcDeviceID="d1" destDeviceID="d2">
      <interfacePair lineName="Copper" srcIndex="0" tarIndex="9"/>
    </line>
  </lines>
</topo>"""
    path = tmp_path / "oob.topo"
    path.write_text(xml, encoding="utf-8")
    topo = parse_topo(path)
    link = topo.links[0]
    assert link.src.port == "GigabitEthernet0/0/0"
    assert link.dst.port is None
    assert any("X2" in w for w in topo.warnings)
