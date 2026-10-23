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
