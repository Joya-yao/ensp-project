"""本地 UI 的接口测试：起真服务，用 HTTP 打一遍。"""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest

from labgen.ui import make_server

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "labs"


@pytest.fixture()
def server(tmp_path):
    srv, url = make_server(0, root=tmp_path, out_dir=tmp_path / "output" / "ui")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, url
    finally:
        srv.shutdown()
        thread.join(timeout=2)


def _token(url: str) -> str:
    return url.split("t=")[1]


def _post(url: str, path: str, payload: dict, token: str | None = None):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url.split("/?")[0] + path, data=body, method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Token", token if token is not None else _token(url))
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_index_serves_page_with_token(server):
    srv, url = server
    with urllib.request.urlopen(url, timeout=5) as response:
        html = response.read().decode("utf-8")
    assert response.status == 200
    assert "eNSP 配置生成器" in html
    assert "__TOKEN__" not in html
    assert _token(url) in html


def test_api_rejects_missing_token(server):
    srv, url = server
    body = json.dumps({"topo": "x"}).encode()
    request = urllib.request.Request(url.split("/?")[0] + "/api/summary", data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=5)
    assert exc.value.code == 403


def test_summary_needs_topo(server):
    srv, url = server
    status, data = _post(url, "/api/summary", {})
    assert status == 400
    assert data["ok"] is False
    assert "拓扑" in data["error"]


def test_validate_reports_error(server):
    srv, url = server
    status, data = _post(url, "/api/validate", {"yaml": "devices: {}"})
    assert status == 400
    assert data["ok"] is False


def test_address_table_returns_markdown(server):
    srv, url = server
    yaml_text = (LAB / "lab01-vlan.yaml").read_text(encoding="utf-8")
    status, data = _post(
        url,
        "/api/address-table",
        {"yaml": yaml_text, "topo": str(LAB / "lab01.topo")},
    )
    assert data["ok"] is True
    assert "## 网段与网关" in data["markdown"]
    assert "10.10.0.254" in data["markdown"]


def test_generate_writes_files_inside_output(server, tmp_path):
    srv, url = server
    yaml_text = (LAB / "lab01-vlan.yaml").read_text(encoding="utf-8")
    status, data = _post(
        url,
        "/api/generate",
        {
            "yaml": yaml_text,
            "topo": str(LAB / "lab01.topo"),
            "out_dir": "output/ui",
        },
    )
    assert data["ok"] is True, data
    names = {item["name"] for item in data["files"]}
    assert "LSW1.txt" in names
    assert (tmp_path / "output" / "ui" / "LSW1.txt").is_file()


def test_generate_rejects_output_outside_project(server):
    srv, url = server
    yaml_text = (LAB / "lab01-vlan.yaml").read_text(encoding="utf-8")
    status, data = _post(
        url,
        "/api/generate",
        {"yaml": yaml_text, "topo": str(LAB / "lab01.topo"), "out_dir": "C:/Windows/Temp/x"},
    )
    assert status == 400
    assert data["ok"] is False
    assert "output" in data["error"]


def test_non_string_field_is_rejected(server):
    """字段类型不对要返回 400 而不是崩掉连接。"""

    srv, url = server
    status, data = _post(url, "/api/generate", {"yaml": {"a": 1}, "topo": "x.topo"})
    assert status == 400
    assert data["ok"] is False
    assert "字符串" in data["error"]


def test_file_download_rejects_path_outside_output(server):
    srv, url = server
    target = quote(str(LAB / "lab01.topo"), safe="")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(
            url.split("/?")[0] + "/api/file?path=" + target, timeout=5
        )
    assert exc.value.code == 403