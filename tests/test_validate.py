from pathlib import Path

from labgen.topo import _main

ROOT = Path(__file__).resolve().parents[1]
GOOD = ROOT / "samples" / "requirements-dhcp.yaml"


def test_validate_ok(capsys):
    code = _main(["--validate", "--req", str(GOOD)])
    out = capsys.readouterr().out
    assert code == 0
    assert "校验通过" in out
    assert "设备 3 台" in out
    assert "DHCP" in out


def test_validate_reports_counts(capsys):
    _main(["--validate", "--req", str(GOOD)])
    out = capsys.readouterr().out
    assert "接口" in out and "VLAN" in out


def test_validate_rejects_bad_yaml(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("devices:\n  AR1:\n    interfaces:\n      - {name: GE0/0/0, ip: 999.1.1.1/24}\n", encoding="utf-8")
    code = _main(["--validate", "--req", str(bad)])
    err = capsys.readouterr().err
    assert code == 1
    assert "错误" in err


def test_validate_requires_req(capsys):
    code = _main(["--validate"])
    err = capsys.readouterr().err
    assert code == 1
    assert "--req" in err


def test_missing_topo_without_validate(capsys):
    code = _main([])
    err = capsys.readouterr().err
    assert code == 1
    assert ".topo" in err


def test_empty_requirements_rejected(tmp_path, capsys):
    empty = tmp_path / "empty.yaml"
    empty.write_text("protocols: {}\n", encoding="utf-8")
    code = _main(["--validate", "--req", str(empty)])
    err = capsys.readouterr().err
    assert code == 1
    assert "为空" in err
