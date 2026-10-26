"""export_configs.py 的输出必须是能整段粘贴的纯命令文本。

踩过的坑：UTF-8 BOM 让第一行变成 \\ufeffsystem-view；Windows 下换行被转义两次
（\\r\\r\\n）会让控制台把上一条命令再执行一次，正好是 quit，于是掉进用户视图。
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_configs  # noqa: E402

LAB = ROOT / "docs" / "labs"


@pytest.fixture()
def exported(tmp_path):
    out = tmp_path / "out"
    code = export_configs.main(
        [
            "export_configs.py",
            str(LAB / "lab01.topo"),
            str(LAB / "lab01-vlan.yaml"),
            str(out),
        ]
    )
    assert code == 0
    return out


def test_files_have_no_bom_and_no_double_cr(exported):
    for path in exported.glob("*.txt"):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} 带 BOM"
        assert b"\r\r" not in raw, f"{path.name} 有重复 CR"


def test_commands_start_with_system_view_and_end_with_return(exported):
    text = (exported / "LSW1.txt").read_bytes().decode("utf-8")
    lines = text.split("\r\n")
    assert lines[0] == "system-view"
    assert lines[-2] == "return"


def test_every_block_is_balanced(exported):
    """进视图要么用 quit 退出，要么用 return + system-view 回到系统视图。"""

    text = (exported / "LSW1.txt").read_bytes().decode("utf-8")
    depth = 0
    for line in text.split("\r\n"):
        stripped = line.strip()
        if stripped == "return":
            depth = 0
        elif stripped.startswith(
            ("interface ", "vlan ", "acl number", "ospf ", "area ", "stp region-configuration")
        ):
            depth += 1
        elif stripped == "quit":
            depth -= 1
            assert depth >= 0
    assert depth == 0


def test_safe_paste_replaces_top_level_quit():
    from labgen.pastestyle import to_safe_paste

    commands = [
        "system-view",
        "sysname LSW1",
        "vlan 10",
        " name sales",
        " quit",
        "interface Vlanif10",
        " ip address 10.10.0.252 255.255.255.0",
        " traffic-filter inbound acl 3000",
        " quit",
        "return",
    ]
    out = to_safe_paste(commands)
    assert " quit" not in out
    assert out.count("return") == 3
    assert out.count("system-view") == 3
    # 块结构仍然完整：interface 之后紧跟自己的配置行
    index = out.index("interface Vlanif10")
    assert out[index + 1] == " ip address 10.10.0.252 255.255.255.0"


def test_safe_paste_keeps_nested_quit():
    from labgen.pastestyle import to_safe_paste

    commands = [
        "system-view",
        "ospf 1",
        " area 0",
        "  network 10.0.0.0 0.0.0.255",
        " quit",
        " quit",
        "return",
    ]
    out = to_safe_paste(commands)
    assert out.count(" quit") == 1  # area 的 quit 保留
    assert "return" in out


def test_explicit_gbk_encoding(exported, tmp_path):
    out = tmp_path / "gbk"
    code = export_configs.main(
        [
            "export_configs.py",
            str(LAB / "lab01.topo"),
            str(LAB / "lab01-vlan.yaml"),
            str(out),
            "--encoding",
            "gbk",
        ]
    )
    assert code == 0
    raw = (out / "LSW1.txt").read_bytes()
    assert b"\r\r" not in raw
    (out / "LSW1.txt").read_text(encoding="gbk")


def test_chunking_splits_into_pasteable_parts(tmp_path):
    out = tmp_path / "chunked"
    code = export_configs.main(
        [
            "export_configs.py",
            str(LAB / "lab01.topo"),
            str(LAB / "lab01-vlan.yaml"),
            str(out),
            "--chunk",
            "8",
        ]
    )
    assert code == 0
    parts = sorted(p.name for p in out.glob("LSW1-[0-9][0-9].txt"))
    assert len(parts) > 1
    for part in parts:
        text = (out / part).read_bytes().decode("utf-8")
        lines = [line for line in text.split("\r\n") if line]
        assert lines[0] == "system-view", part
        assert lines[-1] == "return", part
        assert len(lines) <= 8, part


def test_chunk_zero_keeps_single_file(tmp_path):
    out = tmp_path / "whole"
    code = export_configs.main(
        [
            "export_configs.py",
            str(LAB / "lab01.topo"),
            str(LAB / "lab01-vlan.yaml"),
            str(out),
            "--chunk",
            "0",
        ]
    )
    assert code == 0
    assert (out / "LSW1.txt").is_file()
    assert not list(out.glob("LSW1-*.txt"))