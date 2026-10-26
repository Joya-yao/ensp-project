"""本地网页 UI：浏览器里操作，不需要 Node，也不需要打包。

设计目标：
- 只用标准库，仓库依赖不增加；
- 只监听 127.0.0.1，并带一次性 token，别的进程偷不到接口；
- 生成的文件只写到用户指定的输出目录，下载接口不能越界读文件。

想变成独立窗口时，装 ``pywebview`` 后运行 ``run.py --ui --window``，
没装就自动退回浏览器，不影响使用。
"""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from labgen.addresses import render_markdown
from labgen.docx_writer import write_docx
from labgen.generators import build_configs
from labgen.pastestyle import chunk_commands, to_safe_paste
from labgen.requirements import RequirementError, load_requirements
from labgen.topo import TopoError, parse_topo

__all__ = ["serve", "make_server"]

MAX_BODY = 2 * 1024 * 1024  # 2 MB，够放几千行 YAML


def _error(status: int, message: str) -> tuple[int, dict]:
    return status, {"ok": False, "error": message}


def _text(payload: dict, key: str, label: str) -> str:
    """取字符串字段，类型不对就抛 ValueError（由 do_POST 转成 400）。"""

    value = payload.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串，收到的是 {type(value).__name__}")
    return value.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "ensp-labgen-ui"

    # 由 make_server 注入
    token: str = ""
    out_dir: Path = Path("output/ui")
    root: Path | None = None

    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    # ---------- 路由 ----------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html(PAGE)
            return
        if parsed.path == "/api/file":
            self._handle_file(parsed)
            return
        self._send_json(*_error(HTTPStatus.NOT_FOUND, "没有这个地址"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if self.headers.get("X-Token") != self.token:
            self._send_json(*_error(HTTPStatus.FORBIDDEN, "token 不对，刷新页面重试"))
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, str(exc)))
            return

        routes = {
            "/api/summary": self._handle_summary,
            "/api/validate": self._handle_validate,
            "/api/address-table": self._handle_address_table,
            "/api/generate": self._handle_generate,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._send_json(*_error(HTTPStatus.NOT_FOUND, "没有这个接口"))
            return
        try:
            self._send_json(*handler(payload))
        except ValueError as exc:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, str(exc)))

    # ---------- 业务 ----------

    def _handle_summary(self, payload: dict) -> tuple[int, dict]:
        topo_path = _text(payload, "topo", "拓扑路径")
        if not topo_path:
            return _error(HTTPStatus.BAD_REQUEST, "先填拓扑文件路径")
        try:
            topo = parse_topo(topo_path)
        except (FileNotFoundError, TopoError) as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))
        return HTTPStatus.OK, {
            "ok": True,
            "devices": [
                {"name": d.name, "model": d.model, "type": d.device_type, "ports": len(d.ports)}
                for d in topo.devices
            ],
            "links": len(topo.links),
            "warnings": topo.warnings,
        }

    def _handle_validate(self, payload: dict) -> tuple[int, dict]:
        yaml_text = _text(payload, "yaml", "要求 YAML")
        if not yaml_text.strip():
            return _error(HTTPStatus.BAD_REQUEST, "先把要求 YAML 贴进来")
        try:
            req = self._load_req_text(yaml_text)
        except RequirementError as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))
        return HTTPStatus.OK, {
            "ok": True,
            "experiment": req.experiment,
            "devices": list(req.devices),
            "acls": len(req.acls),
            "has_bgp": req.bgp is not None,
            "has_rip": req.rip is not None,
            "nats": len(req.nats),
        }

    def _handle_address_table(self, payload: dict) -> tuple[int, dict]:
        yaml_text = _text(payload, "yaml", "要求 YAML")
        if not yaml_text.strip():
            return _error(HTTPStatus.BAD_REQUEST, "先把要求 YAML 贴进来")
        try:
            req = self._load_req_text(yaml_text)
        except RequirementError as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))

        topo = None
        topo_path = _text(payload, "topo", "拓扑路径")
        if topo_path:
            try:
                topo = parse_topo(topo_path)
            except (FileNotFoundError, TopoError) as exc:
                return _error(HTTPStatus.BAD_REQUEST, str(exc))
        return HTTPStatus.OK, {"ok": True, "markdown": render_markdown(topo, req)}

    def _handle_generate(self, payload: dict) -> tuple[int, dict]:
        topo_path = _text(payload, "topo", "拓扑路径")
        yaml_text = _text(payload, "yaml", "要求 YAML")
        if not topo_path:
            return _error(HTTPStatus.BAD_REQUEST, "先填拓扑文件路径")
        if not yaml_text.strip():
            return _error(HTTPStatus.BAD_REQUEST, "先把要求 YAML 贴进来")

        try:
            req = self._load_req_text(yaml_text)
        except RequirementError as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))
        try:
            topo = parse_topo(topo_path)
            configs = build_configs(topo, req)
        except (FileNotFoundError, TopoError, RequirementError) as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))

        out_dir = self._try_out_dir(_text(payload, "out_dir", "输出目录") or None)
        if out_dir is None:
            return _error(
                HTTPStatus.BAD_REQUEST,
                "输出目录必须位于项目的 output/ 目录下，例：output/ui",
            )
        out_dir.mkdir(parents=True, exist_ok=True)

        files: list[dict] = []
        docx_path = out_dir / "配置文档.docx"
        try:
            write_docx(topo, req, configs, docx_path)
            files.append({"name": docx_path.name, "size": docx_path.stat().st_size})
        except ImportError:
            pass  # 没装 python-docx 就只出 txt

        for name in sorted(configs):
            lines = to_safe_paste(configs[name])
            chunks = chunk_commands(lines, 40)
            for index, chunk in enumerate(chunks, start=1):
                suffix = "" if len(chunks) == 1 else f"-{index:02d}"
                target = out_dir / f"{name}{suffix}.txt"
                target.write_text(
                    "\r\n".join(chunk) + "\r\n", encoding="utf-8", newline=""
                )
                files.append({"name": target.name, "size": target.stat().st_size})

        return HTTPStatus.OK, {
            "ok": True,
            "out_dir": str(out_dir),
            "files": files,
            "devices": len(configs),
        }

    # ---------- 工具 ----------

    def _load_req_text(self, yaml_text: str):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(yaml_text)
            path = fh.name
        try:
            return load_requirements(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def _try_out_dir(self, value: str | None) -> Path | None:
        try:
            return self._resolve_out_dir(value)
        except ValueError:
            return None

    def _resolve_out_dir(self, value: str | None) -> Path:
        root = (self.root or Path.cwd()).resolve()
        allowed = (root / "output").resolve()
        if not value or not value.strip():
            return self.out_dir
        candidate = Path(value.strip())
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        if resolved != allowed and allowed not in resolved.parents:
            # 拒绝写到项目 output 之外，避免误覆盖系统文件
            raise ValueError(f"输出目录必须位于 {allowed} 下")
        return resolved

    def _handle_file(self, parsed) -> None:
        query = parse_qs(parsed.query)
        raw = (query.get("path") or [""])[0]
        if not raw:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, "缺少 path"))
            return
        try:
            target = Path(raw).resolve()
            allowed = (self.root or Path.cwd()).resolve() / "output"
            if allowed.resolve() not in target.parents:
                raise ValueError
        except (ValueError, OSError):
            self._send_json(*_error(HTTPStatus.FORBIDDEN, "只能下载 output 目录里的文件"))
            return
        if not target.is_file():
            self._send_json(*_error(HTTPStatus.NOT_FOUND, "文件不存在"))
            return

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        suffix = target.suffix.lower()
        ctype = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
        }.get(suffix, "application/octet-stream")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("请求太大")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是对象")
        return data

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.replace("__TOKEN__", self.token).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    port: int = 0, *, root: Path | None = None, out_dir: Path | None = None
) -> tuple[ThreadingHTTPServer, str]:
    """起一个服务，返回 (server, 访问地址)。port=0 时由系统分配。"""

    root = (root or Path.cwd()).resolve()
    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "token": secrets.token_urlsafe(16),
            "out_dir": (out_dir or root / "output" / "ui").resolve(),
            "root": root,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={handler.token}"
    return server, url


def serve(port: int = 8765, *, open_browser: bool = True, window: bool = False) -> int:
    """启动 UI，阻塞到进程结束。"""

    server, url = make_server(port)
    print(f"eNSP 配置生成器 UI：{url}")
    print("按 Ctrl+C 结束。")

    if window:
        try:
            import webview  # type: ignore

            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            webview.create_window("eNSP 配置生成器", url, width=1100, height=800)
            webview.start()
            server.shutdown()
            return 0
        except ImportError:
            print("没装 pywebview，改用浏览器打开（pip install pywebview 可得到独立窗口）")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        server.shutdown()
    return 0


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>eNSP 配置生成器</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #0f1115; color: #e6e6e6; }
  header { padding: 14px 20px; border-bottom: 1px solid #23262d; display: flex; gap: 12px; align-items: baseline; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header span { color: #8b93a1; font-size: 12px; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px 20px 40px; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  label { display: block; font-size: 12px; color: #9aa3b2; margin: 10px 0 4px; }
  input, textarea { width: 100%; background: #161a21; color: #e6e6e6; border: 1px solid #2a2f3a; border-radius: 6px; padding: 8px 10px; font: inherit; }
  textarea { min-height: 380px; font-family: Consolas, "Cascadia Mono", monospace; font-size: 12.5px; line-height: 1.5; resize: vertical; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
  button { background: #2b6cf6; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; font: inherit; cursor: pointer; }
  button.ghost { background: #1e232c; color: #c8cfdb; border: 1px solid #2a2f3a; }
  button:disabled { opacity: .55; cursor: progress; }
  pre { background: #12151b; border: 1px solid #23262d; border-radius: 8px; padding: 12px; overflow: auto; max-height: 520px; font-size: 12.5px; }
  .ok { color: #4ade80; } .bad { color: #f87171; } .muted { color: #8b93a1; }
  ul.files { list-style: none; padding: 0; margin: 8px 0 0; }
  ul.files li { padding: 4px 0; border-bottom: 1px dashed #23262d; display: flex; justify-content: space-between; gap: 10px; }
  a { color: #7aa7ff; }
</style>
</head>
<body>
<header>
  <h1>eNSP 配置生成器</h1>
  <span>本地运行 · 数据不出机器</span>
</header>
<main>
  <section>
    <label>拓扑文件（.topo 完整路径）</label>
    <input id="topo" placeholder="C:\\path\\lab.topo">
    <label>要求 YAML</label>
    <textarea id="yaml" placeholder="把 requirements.yaml 的内容贴进来"></textarea>
    <div class="row">
      <button id="btn-summary" class="ghost">看拓扑</button>
      <button id="btn-validate" class="ghost">校验</button>
      <button id="btn-addr" class="ghost">地址表</button>
      <button id="btn-gen">生成配置</button>
    </div>
    <label>输出目录（相对项目根，必须在 output/ 下）</label>
    <input id="outdir" value="output/ui">
  </section>
  <section>
    <label>结果</label>
    <pre id="out">就绪。</pre>
    <ul class="files" id="files"></ul>
  </section>
</main>
<script>
const TOKEN = "__TOKEN__";
const $ = (id) => document.getElementById(id);
const out = $("out");

async function call(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Token": TOKEN},
    body: JSON.stringify(payload || {})
  });
  try {
    return await res.json();
  } catch (e) {
    return {ok: false, error: `HTTP ${res.status}`};
  }
}

function setBusy(busy) {
  document.querySelectorAll("button").forEach(b => b.disabled = busy);
}

function body() {
  return { topo: $("topo").value, yaml: $("yaml").value, out_dir: $("outdir").value };
}

function show(text, cls) {
  out.textContent = text;
  out.className = cls || "";
}

$("btn-summary").onclick = async () => {
  setBusy(true);
  try {
    const r = await call("/api/summary", body());
    if (!r.ok) return show(r.error, "bad");
    const lines = r.devices.map(d => `${d.name}  ${d.model}  ${d.type}  ${d.ports} 接口`);
    show(`${r.devices.length} 台设备，${r.links} 条连线\\n\\n` + lines.join("\\n"));
  } finally { setBusy(false); }
};

$("btn-validate").onclick = async () => {
  setBusy(true);
  try {
    const r = await call("/api/validate", body());
    if (!r.ok) return show(r.error, "bad");
    show(`校验通过：${r.experiment || "未命名"}\\n设备 ${r.devices.length} 台\\nACL ${r.acls} 条 · NAT ${r.nats} 条\\nRIP ${r.has_rip ? "有" : "无"} · BGP ${r.has_bgp ? "有" : "无"}`, "ok");
  } finally { setBusy(false); }
};

$("btn-addr").onclick = async () => {
  setBusy(true);
  try {
    const r = await call("/api/address-table", body());
    if (!r.ok) return show(r.error, "bad");
    show(r.markdown);
  } finally { setBusy(false); }
};

$("btn-gen").onclick = async () => {
  setBusy(true);
  $("files").innerHTML = "";
  try {
    const r = await call("/api/generate", body());
    if (!r.ok) return show(r.error, "bad");
    show(`生成完成：${r.devices} 台设备\\n输出目录 ${r.out_dir}`, "ok");
    $("files").innerHTML = r.files.map(f =>
      `<li><a href="/api/file?path=${encodeURIComponent(r.out_dir + "/" + f.name)}">${f.name}</a><span class="muted">${f.size} B</span></li>`
    ).join("");
  } finally { setBusy(false); }
};
</script>
</body>
</html>
"""
