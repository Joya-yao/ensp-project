from pathlib import Path

import pytest

from labgen.docx_writer import build_document, write_docx
from labgen.generators import build_configs
from labgen.requirements import load_requirements

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements.yaml"


@pytest.fixture(scope="module")
def built(topo):
    req = load_requirements(REQ)
    return topo, req, build_configs(topo, req)


def _texts(doc):
    return [p.text for p in doc.paragraphs]


def test_document_has_topology_section(built):
    topo, req, configs = built
    texts = _texts(build_document(topo, req, configs))
    assert req.experiment in texts
    assert "拓扑概览" in texts
    assert "设备" in texts
    assert "连线" in texts


def test_each_device_gets_section(built):
    topo, req, configs = built
    texts = _texts(build_document(topo, req, configs))
    assert "AR1　AR2220" in texts
    assert "AR2　AR2220" in texts
    # LSW1 没有配置意图，不能有命令节
    assert "LSW1　S5700" not in texts


def test_commands_are_verbatim_lines(built):
    topo, req, configs = built
    texts = _texts(build_document(topo, req, configs))
    for expected in (
        "system-view",
        " ip address 10.0.1.1 255.255.255.0",
        "  network 10.0.1.0 0.0.0.255",
        "return",
    ):
        assert expected in texts


def test_idle_devices_listed(built):
    topo, req, configs = built
    texts = _texts(build_document(topo, req, configs))
    assert "未生成配置的设备" in texts
    assert any("LSW1" in t and "没有命令" in t for t in texts)


def test_command_runs_use_monospace(built):
    topo, req, configs = built
    doc = build_document(topo, req, configs)
    code_runs = [
        run
        for p in doc.paragraphs
        for run in p.runs
        if run.text.startswith("system-view") or run.text.startswith(" ip address")
    ]
    assert code_runs
    assert all(run.font.name == "Consolas" for run in code_runs)


def test_output_is_deterministic(built):
    topo, req, configs = built
    first = _texts(build_document(topo, req, configs))
    second = _texts(build_document(topo, req, configs))
    assert first == second


def test_write_docx_creates_file(built, tmp_path):
    topo, req, configs = built
    out = write_docx(topo, req, configs, tmp_path / "out.docx")
    assert out.is_file()
    assert out.stat().st_size > 4000


def _table_rows(doc, header):
    header = tuple(header) if isinstance(header, (list, tuple)) else (header,)
    for table in doc.tables:
        texts = [[cell.text for cell in row.cells] for row in table.rows]
        if texts and tuple(texts[0][: len(header)]) == header:
            return texts
    return []


ADDRESS_HEADER = ("设备", "接口", "IP", "掩码", "VLAN", "网关", "说明")


def test_address_section_lists_interface_ip(topo):
    req = load_requirements(ROOT / "samples" / "requirements.yaml")
    doc = build_document(topo, req, build_configs(topo, req))
    assert "地址与网关" in _texts(doc)
    rows = _table_rows(doc, ADDRESS_HEADER)
    assert ["AR1", "GigabitEthernet0/0/0", "10.0.1.1", "255.255.255.0", "—", "—", "to-LSW1"] in rows


def test_gateway_comes_from_vrrp(topo):
    req = load_requirements(ROOT / "samples" / "requirements-vrrp.yaml")
    doc = build_document(topo, req, build_configs(topo, req))
    rows = _table_rows(doc, ADDRESS_HEADER)
    ar1 = next(row for row in rows[1:] if row[0] == "AR1")
    assert ar1[5] == "10.0.1.254"
    networks = _table_rows(doc, ("网段", "掩码", "网关"))
    assert any("VRRP1" in row[3] and row[2] == "10.0.1.254" for row in networks)


def test_gateway_inferred_from_254(topo):
    req = load_requirements(ROOT / "samples" / "requirements-vlanif.yaml")
    doc = build_document(topo, req, build_configs(topo, req))
    rows = _table_rows(doc, ADDRESS_HEADER)
    gateway_rows = [row for row in rows[1:] if row[5] == "本机"]
    assert gateway_rows
    assert any(row[1] == "Vlanif10" and row[4] == "10" for row in rows[1:])


def test_layer2_devices_are_called_out(topo):
    req = load_requirements(ROOT / "samples" / "requirements-vlan.yaml")
    doc = build_document(topo, req, build_configs(topo, req))
    assert any("没有三层地址的设备" in t and "LSW1" in t for t in _texts(doc))


def test_terminal_addresses_follow_access_vlan():
    from labgen.topo import parse_topo

    lab_topo = parse_topo(ROOT / "docs" / "labs" / "lab01.topo")
    req = load_requirements(ROOT / "docs" / "labs" / "lab01-vlan.yaml")
    doc = build_document(lab_topo, req, build_configs(lab_topo, req))

    rows = _table_rows(doc, ("终端", "接在", "VLAN"))
    by_name = {row[0]: row for row in rows[1:]}
    assert by_name["PC1"][1:5] == ["LSW1:GigabitEthernet0/0/1", "10", "10.10.0.1", "255.255.255.0"]
    assert by_name["PC2"][1:5] == ["LSW1:GigabitEthernet0/0/2", "20", "10.20.0.1", "255.255.255.0"]
    assert by_name["PC3"][3] == "10.10.0.2"
    assert by_name["PC4"][3] == "10.20.0.2"
    assert by_name["PC1"][5].startswith("10.10.0.254")
