import os
import tempfile
from pathlib import Path

import pytest

import labgen.ai as ai
from labgen.topo import _main

LOCAL_YAML = """
provider: local
local:
  base_url: http://127.0.0.1:11434/v1
  model: qwen2.5:7b
"""


def write_tmp(text, suffix=".yaml"):
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fh:
        fh.write(text)
        return Path(fh.name)


def test_load_local_config():
    path = write_tmp(LOCAL_YAML)
    try:
        cfg = ai.load_ai_config(path)
    finally:
        path.unlink(missing_ok=True)
    assert cfg.provider == "local"
    assert cfg.model == "qwen2.5:7b"
    assert cfg.endpoint == "http://127.0.0.1:11434/v1/chat/completions"


def test_invalid_provider_rejected():
    path = write_tmp("provider: gpu\n")
    try:
        with pytest.raises(ai.AiError):
            ai.load_ai_config(path)
    finally:
        path.unlink(missing_ok=True)


def test_cloud_without_key_rejected(monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    path = write_tmp(
        """
provider: cloud
cloud:
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
"""
    )
    try:
        with pytest.raises(ai.AiError) as excinfo:
            ai.load_ai_config(path)
    finally:
        path.unlink(missing_ok=True)
    assert "api_key" in str(excinfo.value)


def test_cloud_key_from_env(monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "sk-test")
    path = write_tmp(
        """
provider: cloud
cloud:
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
"""
    )
    try:
        cfg = ai.load_ai_config(path)
    finally:
        path.unlink(missing_ok=True)
    assert cfg.api_key == "sk-test"


def test_strip_code_fence():
    assert ai.strip_code_fence("```yaml\nprotoc: {}\n```").strip() == "protoc: {}"
    assert ai.strip_code_fence("plain\n").strip() == "plain"


def test_convert_uses_chat(monkeypatch):
    monkeypatch.setattr(ai, "chat", lambda cfg, text: "```yaml\ndevices: {}\n```")
    cfg = ai.AiConfig(provider="local", base_url="http://x/v1", model="m")
    assert ai.convert_requirements(cfg, "任意原文").strip() == "devices: {}"


GOOD_OUTPUT = """
devices:
  AR1:
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.1.1/24}
"""


def test_cli_ai_generates_and_checks(monkeypatch, tmp_path, capsys):
    source = tmp_path / "req.md"
    source.write_text("AR1 的 GE0/0/0 配 10.0.1.1/24", encoding="utf-8")
    ai_cfg = tmp_path / "ai.yaml"
    ai_cfg.write_text(LOCAL_YAML, encoding="utf-8")
    target = tmp_path / "out.yaml"

    monkeypatch.setattr(ai, "chat", lambda cfg, text: GOOD_OUTPUT)
    code = _main(
        [
            "--ai-input", str(source),
            "--ai-config", str(ai_cfg),
            "--ai-out", str(target),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert target.is_file()
    assert "校验通过" in out


def test_cli_ai_bad_output_fails(monkeypatch, tmp_path, capsys):
    source = tmp_path / "req.md"
    source.write_text("随便写", encoding="utf-8")
    ai_cfg = tmp_path / "ai.yaml"
    ai_cfg.write_text(LOCAL_YAML, encoding="utf-8")
    target = tmp_path / "bad.yaml"

    monkeypatch.setattr(ai, "chat", lambda cfg, text: "devices: 这不是映射\n")
    code = _main(
        ["--ai-input", str(source), "--ai-config", str(ai_cfg), "--ai-out", str(target)]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "校验未通过" in err or "错误" in err
