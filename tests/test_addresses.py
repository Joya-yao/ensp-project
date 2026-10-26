import ipaddress
from pathlib import Path

import pytest

from labgen.addresses import (
    address_entries,
    device_rows,
    gateway_map,
    network_rows,
    render_markdown,
    terminal_rows,
)
from labgen.requirements import load_requirements
from labgen.topo import _main, parse_topo

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
LABS = ROOT / "docs" / "labs"


def _req(name):
    return load_requirements(SAMPLES / name)


def test_entries_only_include_interfaces_with_ip():
    req = _req("requirements-vlan.yaml")
    entries = address_entries(req)
    assert {entry.interface for entry in entries} == {"GigabitEthernet0/0/0"}
    assert {entry.device for entry in entries} == {"AR1", "AR2"}


def test_gateway_prefers_vrrp_over_host_convention():
    req = _req("requirements-vrrp.yaml")
    gateways = gateway_map(req, address_entries(req))
    network = ipaddress.ip_network("10.0.1.0/24")
    assert gateways[network][0] == "10.0.1.254"
    assert "VRRP1" in gateways[network][1]


def test_gateway_from_dhcp_pool():
    req = _req("requirements-dhcp.yaml")
    gateways = gateway_map(req, address_entries(req))
    network = ipaddress.ip_network("10.0.1.0/24")
    assert gateways[network] == ("10.0.1.1", "DHCP 地址池 vlan10")


def test_gateway_from_254_convention():
    req = load_requirements(LABS / "lab01-vlan.yaml")
    gateways = gateway_map(req, address_entries(req))
    assert gateways[ipaddress.ip_network("10.10.0.0/24")] == (
        "10.10.0.254",
        "网段内 .254 地址",
    )


def test_transit_link_has_no_gateway():
    # AR1/AR2 互联：两端都是 .1/.2，不该把 .1 当网关
    req = _req("requirements.yaml")
    gateways = gateway_map(req, address_entries(req))
    assert ipaddress.ip_network("10.0.1.0/24") not in gateways
    rows = device_rows(req)
    assert all(row[5] == "—" for row in rows)


def test_device_rows_mark_own_gateway():
    req = load_requirements(LABS / "lab01-vlan.yaml")
    rows = device_rows(req)
    assert (
        "LSW1",
        "Vlanif10",
        "10.10.0.254",
        "255.255.255.0",
        "10",
        "本机",
        "gateway-student",
    ) in rows


def test_network_rows_count_free_terminal_addresses():
    req = load_requirements(LABS / "lab01-vlan.yaml")
    rows = network_rows(req)
    row = next(row for row in rows if row[0] == "10.10.0.0/24")
    assert row[2] == "10.10.0.254"
    assert row[5].startswith("10.10.0.1 ~ 10.10.0.253")


def test_terminal_rows_follow_access_vlan():
    topo = parse_topo(LABS / "lab01.topo")
    req = load_requirements(LABS / "lab01-vlan.yaml")
    rows = {row[0]: row for row in terminal_rows(topo, req)}
    assert rows["PC1"][1:5] == (
        "LSW1:GigabitEthernet0/0/1",
        "10",
        "10.10.0.1",
        "255.255.255.0",
    )
    assert rows["PC3"][3] == "10.10.0.2"
    assert rows["PC4"][3] == "10.20.0.2"
    assert rows["PC1"][5].startswith("10.10.0.254")


def test_terminal_rows_without_vlan_are_flagged():
    topo = parse_topo(LABS / "lab01.topo")
    req = load_requirements(SAMPLES / "requirements.yaml")  # 没有 LSW1/LSW2 的 VLAN 定义
    rows = terminal_rows(topo, req)
    assert len(rows) == 4
    assert all("未识别" in row[3] for row in rows)


def test_render_markdown_has_three_sections():
    topo = parse_topo(LABS / "lab01.topo")
    req = load_requirements(LABS / "lab01-vlan.yaml")
    text = render_markdown(topo, req)
    assert "## 网段与网关" in text
    assert "## 每台设备的地址" in text
    assert "## 终端建议地址" in text
    assert "确认这份表" in text


def test_render_markdown_without_topo_skips_terminals():
    req = load_requirements(LABS / "lab01-vlan.yaml")
    text = render_markdown(None, req)
    assert "## 网段与网关" in text
    assert "## 终端建议地址" not in text


def test_cli_address_table_prints_markdown(capsys):
    code = _main(["--address-table", "--req", str(LABS / "lab01-vlan.yaml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "## 每台设备的地址" in out
    assert "10.10.0.254" in out


def test_cli_address_table_requires_req(capsys):
    code = _main(["--address-table"])
    assert code == 1
    assert "--address-table" in capsys.readouterr().err


def test_ai_stage_one_uses_address_prompt(monkeypatch):
    from labgen import ai

    captured = {}

    def fake_chat(config, text, system_prompt=None):
        captured["prompt"] = system_prompt
        captured["text"] = text
        return "| 网段 |\n| --- |"

    monkeypatch.setattr(ai, "chat", fake_chat)
    out = ai.convert_address_table(object(), "原文：网关 .254")

    assert "不要输出 YAML" in captured["prompt"]
    assert "不要输出配置命令" in captured["prompt"]
    assert captured["text"] == "原文：网关 .254"
    assert out.endswith("\n")


def test_stage_two_keeps_yaml_prompt(monkeypatch):
    from labgen import ai

    captured = {}

    def fake_chat(config, text, system_prompt=None):
        captured["prompt"] = system_prompt
        return "```yaml\nexperiment: {}\n```"

    monkeypatch.setattr(ai, "chat", fake_chat)
    out = ai.convert_requirements(object(), "已确认的表")
    assert captured["prompt"] is None
    assert out == "experiment: {}\n"