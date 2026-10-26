"""本地网页 UI：浏览器里操作，不需要 Node，也不需要打包。

设计目标：
- 只用标准库，仓库依赖不增加；
- 只监听 127.0.0.1，并带一次性 token，别的进程偷不到接口；
- 读：只允许读项目目录内；写：只允许写项目 ``output/`` 内；
- 上传的拓扑、草稿 YAML、地址表放「中间目录」，最终 docx/txt 放「最终目录」，两者都由用户指定（限 output/ 下）。

想变成独立窗口时，装 ``pywebview`` 后运行 ``run.py --ui --window``，
没装就自动退回浏览器，不影响使用。
"""

from __future__ import annotations

import base64
import binascii
import json
import re
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
from labgen.ai import AiConfig, AiError, convert_address_table, convert_requirements
from labgen.docx_writer import write_docx
from labgen.generators import build_configs
from labgen.pastestyle import chunk_commands, to_safe_paste
from labgen.requirements import RequirementError, load_requirements
from labgen.topo import TopoError, parse_topo

__all__ = ["serve", "make_server"]

MAX_BODY = 8 * 1024 * 1024  # 8 MB：够放一个几 MB 的 .topo 的 base64
TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".txt", ".json", ".topo"}
SAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)


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

    token: str = ""
    root: Path = Path(".").resolve()
    work: Path = Path("output/ui/work")
    final: Path = Path("output/ui/final")

    # ---------- 基础 ----------

    def log_message(self, fmt: str, *args) -> None:
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

    def _output_dir(self) -> Path:
        return (self.root / "output").resolve()

    def _work_dir(self) -> Path:
        return self.work.resolve()

    def _final_dir(self) -> Path:
        return self.final.resolve()

    # ---------- 路由 ----------

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self._send_html(PAGE)
            return
        if parsed.path == "/api/file":
            self._download(query)
            return
        if parsed.path == "/api/read":
            self._read_file(query)
            return
        if parsed.path == "/api/list":
            self._list_dir(query)
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
            "/api/upload": self._handle_upload,
            "/api/save": self._handle_save,
            "/api/ai-convert": self._handle_ai,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._send_json(*_error(HTTPStatus.NOT_FOUND, "没有这个接口"))
            return
        try:
            self._send_json(*handler(payload))
        except ValueError as exc:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, str(exc)))

    # ---------- 路径守卫 ----------

    def _inside(self, path: Path, base: Path) -> bool:
        path = path.resolve()
        base = base.resolve()
        return path == base or base in path.parents

    def _user_dir(self, value: str, default: Path, label: str) -> Path:
        """把用户填的目录解析成绝对路径，必须落在 output/ 下。"""

        raw = value.strip() or str(default.relative_to(self.root))
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if not self._inside(resolved, self._output_dir()):
            raise ValueError(f"{label}必须位于项目的 output/ 目录下，例：output/ui/work")
        return resolved

    # ---------- 业务 ----------

    def _yaml_text(self, payload: dict) -> str:
        text = _text(payload, "yaml", "要求 YAML")
        if not text:
            raise ValueError("先把要求 YAML 贴进来")
        return text

    def _load_req(self, yaml_text: str):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(yaml_text)
            path = fh.name
        try:
            return load_requirements(path)
        finally:
            Path(path).unlink(missing_ok=True)

    def _topo_path(self, payload: dict) -> str:
        topo_path = _text(payload, "topo", "拓扑路径")
        if not topo_path:
            raise ValueError("先选一个 .topo 文件，或填它的路径")
        return topo_path

    def _handle_summary(self, payload: dict) -> tuple[int, dict]:
        try:
            topo = parse_topo(self._topo_path(payload))
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
        try:
            req = self._load_req(self._yaml_text(payload))
        except RequirementError as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))
        return HTTPStatus.OK, {
            "ok": True,
            "experiment": req.experiment,
            "devices": list(req.devices),
            "acls": len(req.acls),
            "nats": len(req.nats),
            "has_rip": req.rip is not None,
            "has_bgp": req.bgp is not None,
        }

    def _handle_address_table(self, payload: dict) -> tuple[int, dict]:
        try:
            req = self._load_req(self._yaml_text(payload))
        except RequirementError as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))

        topo = None
        topo_path = _text(payload, "topo", "拓扑路径")
        if topo_path:
            try:
                topo = parse_topo(topo_path)
            except (FileNotFoundError, TopoError) as exc:
                return _error(HTTPStatus.BAD_REQUEST, str(exc))

        markdown = render_markdown(topo, req)

        saved = None
        try:
            work = self._user_dir(_text(payload, "work_dir", "中间目录"), self._work_dir(), "中间目录")
            work.mkdir(parents=True, exist_ok=True)
            target = work / "addresses.md"
            target.write_text(markdown, encoding="utf-8", newline="")
            saved = str(target)
        except (ValueError, OSError):
            pass  # 保存失败不影响展示

        return HTTPStatus.OK, {"ok": True, "markdown": markdown, "saved": saved}

    def _handle_generate(self, payload: dict) -> tuple[int, dict]:
        try:
            yaml_text = self._yaml_text(payload)
            topo_path = self._topo_path(payload)
            req = self._load_req(yaml_text)
            topo = parse_topo(topo_path)
            configs = build_configs(topo, req)
        except (FileNotFoundError, TopoError, RequirementError) as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))

        final_dir = self._user_dir(_text(payload, "final_dir", "最终目录"), self._final_dir(), "最终目录")
        final_dir.mkdir(parents=True, exist_ok=True)

        files: list[dict] = []
        docx_path = final_dir / "配置文档.docx"
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
                target = final_dir / f"{name}{suffix}.txt"
                target.write_text(
                    "\r\n".join(chunk) + "\r\n", encoding="utf-8", newline=""
                )
                files.append({"name": target.name, "size": target.stat().st_size})

        return HTTPStatus.OK, {
            "ok": True,
            "final_dir": str(final_dir),
            "files": files,
            "devices": len(configs),
        }

    def _handle_upload(self, payload: dict) -> tuple[int, dict]:
        name = _text(payload, "name", "文件名")
        if not name:
            raise ValueError("缺少文件名")
        data_b64 = payload.get("data")
        if not isinstance(data_b64, str) or not data_b64:
            raise ValueError("缺少文件内容")
        try:
            raw = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("文件内容不是合法 base64") from exc

        work = self._user_dir(_text(payload, "work_dir", "中间目录"), self._work_dir(), "中间目录")
        work.mkdir(parents=True, exist_ok=True)
        safe = SAFE_NAME.sub("_", Path(name).name) or "uploaded.topo"
        target = work / safe
        target.write_bytes(raw)
        return HTTPStatus.OK, {"ok": True, "path": str(target), "size": len(raw)}

    def _handle_save(self, payload: dict) -> tuple[int, dict]:
        relative = _text(payload, "path", "保存路径")
        content = payload.get("content")
        if not relative:
            raise ValueError("缺少保存路径")
        if not isinstance(content, str):
            raise ValueError("content 必须是字符串")

        candidate = Path(relative)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if not self._inside(resolved, self._output_dir()):
            raise ValueError("只能保存到项目的 output/ 目录下")
        if resolved.suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError(f"只允许保存这些类型：{'、'.join(sorted(TEXT_SUFFIXES))}")

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8", newline="")
        return HTTPStatus.OK, {"ok": True, "path": str(resolved)}

    def _handle_ai(self, payload: dict) -> tuple[int, dict]:
        text = _text(payload, "text", "要求原文")
        if not text:
            raise ValueError("先把 PDF/Word 里的要求原文贴进来")

        provider = _text(payload, "provider", "provider") or "cloud"
        if provider not in ("local", "cloud"):
            raise ValueError("provider 只能是 local 或 cloud")
        base_url = _text(payload, "base_url", "base_url")
        model = _text(payload, "model", "model")
        api_key = _text(payload, "api_key", "api_key")
        if not base_url or not model:
            raise ValueError("base_url 和 model 都要填")
        if provider == "cloud" and not api_key:
            raise ValueError("云端模式缺 api_key：填在页面里，或改用本地模型")

        mode = _text(payload, "mode", "mode") or "yaml"
        if mode not in ("yaml", "table"):
            raise ValueError("mode 只能是 yaml 或 table")

        config = AiConfig(
            provider=provider, base_url=base_url, model=model, api_key=api_key
        )
        try:
            if mode == "table":
                content = convert_address_table(config, text)
            else:
                content = convert_requirements(config, text)
        except AiError as exc:
            return _error(HTTPStatus.BAD_REQUEST, str(exc))
        return HTTPStatus.OK, {"ok": True, "content": content}

    # ---------- 读写文件 ----------

    def _read_file(self, query) -> None:
        raw = (query.get("path") or [""])[0]
        if not raw:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, "缺少 path"))
            return
        target = Path(raw)
        if not target.is_absolute():
            target = self.root / target
        target = target.resolve()
        if not self._inside(target, self.root):
            self._send_json(*_error(HTTPStatus.FORBIDDEN, "只能读项目目录内的文件"))
            return
        if not target.is_file():
            self._send_json(*_error(HTTPStatus.NOT_FOUND, "文件不存在"))
            return
        if target.suffix.lower() not in TEXT_SUFFIXES:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, "这个类型不支持在线查看"))
            return
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_text(encoding="gb18030", errors="replace")
        self._send_json(HTTPStatus.OK, {"ok": True, "path": str(target), "content": content})

    def _list_dir(self, query) -> None:
        raw = (query.get("dir") or [""])[0]
        base = Path(raw) if raw else self.root / "output" / "ui" / "work"
        if not base.is_absolute():
            base = self.root / base
        base = base.resolve()
        if not self._inside(base, self.root):
            self._send_json(*_error(HTTPStatus.FORBIDDEN, "只能列项目目录内的文件"))
            return
        if not base.is_dir():
            self._send_json(HTTPStatus.OK, {"ok": True, "dir": str(base), "files": []})
            return
        files = []
        for item in sorted(base.iterdir()):
            if not item.is_file() or item.suffix.lower() not in TEXT_SUFFIXES:
                continue
            files.append({"name": item.name, "size": item.stat().st_size, "path": str(item)})
        self._send_json(HTTPStatus.OK, {"ok": True, "dir": str(base), "files": files})

    def _download(self, query) -> None:
        raw = (query.get("path") or [""])[0]
        if not raw:
            self._send_json(*_error(HTTPStatus.BAD_REQUEST, "缺少 path"))
            return
        target = Path(raw)
        if not target.is_absolute():
            target = self.root / target
        target = target.resolve()
        if not self._inside(target, self._output_dir()):
            self._send_json(*_error(HTTPStatus.FORBIDDEN, "只能下载 output 目录里的文件"))
            return
        if not target.is_file():
            self._send_json(*_error(HTTPStatus.NOT_FOUND, "文件不存在"))
            return

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        ctype = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
        }.get(target.suffix.lower(), "application/octet-stream")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.end_headers()
        self.wfile.write(data)

    # ---------- HTTP 工具 ----------

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
    port: int = 0,
    *,
    root: Path | None = None,
    work: Path | None = None,
    final: Path | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """起一个服务，返回 (server, 访问地址)。port=0 时由系统分配。"""

    root = (root or Path.cwd()).resolve()
    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "token": secrets.token_urlsafe(16),
            "root": root,
            "work": (work or root / "output" / "ui" / "work").resolve(),
            "final": (final or root / "output" / "ui" / "final").resolve(),
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
            webview.create_window("eNSP 配置生成器", url, width=1180, height=860)
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


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>eNSP 配置生成器</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #0f1115; color: #e6e6e6; }
  header { padding: 12px 20px; border-bottom: 1px solid #23262d; display: flex; gap: 12px; align-items: baseline; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header span { color: #8b93a1; font-size: 12px; }
  main { display: grid; grid-template-columns: 1.05fr 1fr; gap: 16px; padding: 16px 20px 40px; }
  @media (max-width: 960px) { main { grid-template-columns: 1fr; } }
  section { min-width: 0; }
  label { display: block; font-size: 12px; color: #9aa3b2; margin: 10px 0 4px; }
  input, textarea, select { width: 100%; background: #161a21; color: #e6e6e6; border: 1px solid #2a2f3a; border-radius: 6px; padding: 8px 10px; font: inherit; }
  textarea { min-height: 300px; font-family: Consolas, "Cascadia Mono", monospace; font-size: 12.5px; line-height: 1.5; resize: vertical; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; }
  .row input { flex: 1 1 160px; width: auto; }
  button { background: #2b6cf6; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; font: inherit; cursor: pointer; }
  button.ghost { background: #1e232c; color: #c8cfdb; border: 1px solid #2a2f3a; }
  button:disabled { opacity: .55; cursor: progress; }
  pre { background: #12151b; border: 1px solid #23262d; border-radius: 8px; padding: 12px; overflow: auto; max-height: 420px; font-size: 12.5px; white-space: pre-wrap; }
  .ok { color: #4ade80; } .bad { color: #f87171; } .muted { color: #8b93a1; }
  details { border: 1px solid #23262d; border-radius: 8px; padding: 8px 12px; margin-top: 12px; }
  summary { cursor: pointer; color: #c8cfdb; }
  ul.files { list-style: none; padding: 0; margin: 8px 0 0; max-height: 220px; overflow: auto; }
  ul.files li { padding: 4px 0; border-bottom: 1px dashed #23262d; display: flex; justify-content: space-between; gap: 10px; }
  a { color: #7aa7ff; cursor: pointer; }
  .hint { font-size: 12px; color: #8b93a1; margin-top: 4px; }
</style>
</head>
<body>
<header>
  <h1>eNSP 配置生成器</h1>
  <span>本地运行 · 数据不出机器</span>
</header>
<main>
  <section>
    <label>拓扑文件</label>
    <div class="row">
      <input type="file" id="file" accept=".topo">
      <button id="btn-upload" class="ghost">上传到中间目录</button>
    </div>
    <input id="topo" placeholder="或直接填 .topo 完整路径" style="margin-top:8px">
    <div class="hint" id="topo-hint"></div>

    <label>要求 YAML（可直接编辑）</label>
    <textarea id="yaml" placeholder="把 requirements.yaml 的内容贴进来，或从下面文件列表打开"></textarea>
    <div class="row">
      <button id="btn-save" class="ghost">保存到中间目录</button>
      <input id="save-name" value="requirements.yaml" style="flex:0 0 200px">
    </div>

    <label>目录设置（都必须在项目 output/ 下）</label>
    <input id="work-dir" value="output/ui/work" placeholder="中间目录">
    <input id="final-dir" value="output/ui/final" placeholder="最终目录" style="margin-top:8px">
    <div class="row">
      <button id="btn-list">刷新中间目录</button>
      <span class="muted" id="work-label"></span>
    </div>
    <ul class="files" id="work-files"></ul>

    <details>
      <summary>AI 转换（可选，不填也能用）</summary>
      <label>模型位置</label>
      <select id="ai-provider">
        <option value="cloud">云端（OpenAI 兼容）</option>
        <option value="local">本地（Ollama / LM Studio）</option>
      </select>
      <label>base_url</label>
      <input id="ai-base" value="https://api.deepseek.com/v1">
      <label>model</label>
      <input id="ai-model" value="deepseek-chat">
      <label>api_key（云端必填，本地留空）</label>
      <input id="ai-key" type="password" placeholder="sk-...">
      <label>转换输出</label>
      <select id="ai-mode">
        <option value="yaml">直接出 YAML</option>
        <option value="table">只出地址表（先核对）</option>
      </select>
      <label>要求原文（PDF/Word 里复制出来）</label>
      <textarea id="ai-text" style="min-height:140px" placeholder="把老师的 PDF/Word 要求贴进来"></textarea>
      <div class="row"><button id="btn-ai">转换</button></div>
    </details>
  </section>

  <section>
    <div class="row">
      <button id="btn-summary" class="ghost">看拓扑</button>
      <button id="btn-validate" class="ghost">校验</button>
      <button id="btn-addr" class="ghost">地址表</button>
      <button id="btn-gen">生成配置</button>
    </div>
    <label>结果</label>
    <pre id="out">就绪。</pre>
    <label>生成的文件</label>
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
  try { return await res.json(); } catch (e) { return {ok: false, error: `HTTP ${res.status}`}; }
}

async function getJSON(path) {
  const res = await fetch(path);
  try { return await res.json(); } catch (e) { return {ok: false, error: `HTTP ${res.status}`}; }
}

function setBusy(busy) { document.querySelectorAll("button").forEach(b => b.disabled = busy); }
function show(text, cls) { out.textContent = text; out.className = cls || ""; }
function body(extra) {
  return Object.assign({
    topo: $("topo").value,
    yaml: $("yaml").value,
    work_dir: $("work-dir").value,
    final_dir: $("final-dir").value
  }, extra || {});
}

$("btn-upload").onclick = async () => {
  const file = $("file").files[0];
  if (!file) return show("先选一个 .topo 文件", "bad");
  setBusy(true);
  try {
    const buf = await file.arrayBuffer();
    let bin = ""; const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    const r = await call("/api/upload", {name: file.name, data: btoa(bin), work_dir: $("work-dir").value});
    if (!r.ok) return show(r.error, "bad");
    $("topo").value = r.path;
    $("topo-hint").textContent = "已上传：" + r.path + "（" + r.size + " 字节）";
    show("上传完成。下一步：填/贴 YAML，然后校验。", "ok");
    loadWork();
  } finally { setBusy(false); }
};

$("btn-save").onclick = async () => {
  const name = ($("save-name").value || "requirements.yaml").trim();
  const dir = ($("work-dir").value || "output/ui/work").replace(/[\\\\/]+$/, "");
  setBusy(true);
  try {
    const r = await call("/api/save", {path: dir + "/" + name, content: $("yaml").value});
    if (!r.ok) return show(r.error, "bad");
    show("已保存：" + r.path, "ok");
    loadWork();
  } finally { setBusy(false); }
};

async function loadWork() {
  const dir = encodeURIComponent($("work-dir").value || "output/ui/work");
  const r = await getJSON("/api/list?dir=" + dir);
  if (!r.ok) { $("work-files").innerHTML = ""; return; }
  $("work-label").textContent = r.dir;
  $("work-files").innerHTML = r.files.map(f =>
    `<li><a data-path="${f.path}">${f.name}</a><span class="muted">${f.size} B</span></li>`
  ).join("") || `<li class="muted">目录是空的</li>`;
  $("work-files").querySelectorAll("a[data-path]").forEach(a => {
    a.onclick = async () => {
      const r2 = await getJSON("/api/read?path=" + encodeURIComponent(a.dataset.path));
      if (!r2.ok) return show(r2.error, "bad");
      if (r2.path.endsWith(".topo")) { $("topo").value = r2.path; show("已选拓扑：" + r2.path, "ok"); }
      else { $("yaml").value = r2.content; show("已载入：" + r2.path + "（改完点保存）", "ok"); }
    };
  });
}

$("btn-list").onclick = loadWork;

$("btn-summary").onclick = async () => {
  setBusy(true);
  try {
    const r = await call("/api/summary", body());
    if (!r.ok) return show(r.error, "bad");
    show(`${r.devices.length} 台设备，${r.links} 条连线\\n\\n` +
      r.devices.map(d => `${d.name}  ${d.model}  ${d.type}  ${d.ports} 接口`).join("\\n"));
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
    show(r.markdown + (r.saved ? `\\n\\n已保存：${r.saved}` : ""));
    loadWork();
  } finally { setBusy(false); }
};

$("btn-gen").onclick = async () => {
  setBusy(true); $("files").innerHTML = "";
  try {
    const r = await call("/api/generate", body());
    if (!r.ok) return show(r.error, "bad");
    show(`生成完成：${r.devices} 台设备\\n最终目录 ${r.final_dir}`, "ok");
    $("files").innerHTML = r.files.map(f =>
      `<li><a href="/api/file?path=${encodeURIComponent(r.final_dir + "/" + f.name)}">${f.name}</a><span class="muted">${f.size} B</span></li>`
    ).join("");
  } finally { setBusy(false); }
};

$("btn-ai").onclick = async () => {
  setBusy(true);
  try {
    const r = await call("/api/ai-convert", {
      text: $("ai-text").value,
      provider: $("ai-provider").value,
      base_url: $("ai-base").value,
      model: $("ai-model").value,
      api_key: $("ai-key").value,
      mode: $("ai-mode").value
    });
    if (!r.ok) return show(r.error, "bad");
    if ($("ai-mode").value === "yaml") { $("yaml").value = r.content; show("已填入 YAML，先点校验确认。", "ok"); }
    else show(r.content);
  } finally { setBusy(false); }
};

$("ai-provider").onchange = () => {
  const cloud = $("ai-provider").value === "cloud";
  $("ai-base").value = cloud ? "https://api.deepseek.com/v1" : "http://127.0.0.1:11434/v1";
  $("ai-model").value = cloud ? "deepseek-chat" : "qwen2.5:7b";
};

loadWork();
</script>
</body>
</html>
"""
