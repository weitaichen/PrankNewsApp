import json
import subprocess
from types import SimpleNamespace

import pytest

from prank_news import script_gen


def test_prompt_names_length_and_constraints(request_data):
    prompt = script_gen.build_prompt(request_data)
    for expected in (
        "王小明", "陳小美", "750", "675–825", "±10%", "250", "第一則",
        "2–4", "各位聽眾早安", "結尾", "輕鬆無害", "犯罪指控", "疾病死亡",
        "政治人物", "真實品牌負面消息", "節目：xxx", "主播：xxx", "markdown",
        request_data.topic, request_data.style,
    ):
        assert expected in prompt


def test_parse_headers():
    assert script_gen.parse_response("節目：早安台灣\n主播：林雅婷\n\n各位聽眾早安。\n謝謝收聽。") == (
        "早安台灣", "林雅婷", "各位聽眾早安。\n謝謝收聽。",
    )


@pytest.mark.parametrize("text", ["各位聽眾早安。", "節目：不完整\n各位聽眾早安。"])
def test_parse_missing_headers_keeps_entire_script(text):
    assert script_gen.parse_response(text) == (
        "晨間新聞快報", "主播 林雅婷", text,
    )


def test_markdown_cleanup():
    response = "```text\n# 節目：**早安台灣**\n主播：**林雅婷**\n\n\n- **各位聽眾早安。**\n\n\n* 王小明的吐司正在唱歌。\n```"
    assert script_gen.parse_response(response) == (
        "早安台灣", "林雅婷", "各位聽眾早安。\n\n王小明的吐司正在唱歌。",
    )
    assert script_gen.clean_script("\n## 新聞\n- 消息\n\n\n**結尾**\n") == "新聞\n消息\n\n結尾"


def test_runner_receives_prompt_utf8_and_timeout(monkeypatch, request_data):
    request_data.topic += '\n100% ^ " & special report'
    monkeypatch.setattr(script_gen.shutil, "which", lambda name: "C:/tools/claude.cmd")
    captured = {}

    def runner(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "節目：早安\n主播：雅婷\n\n早安。"}))

    assert script_gen.generate_script(request_data, runner=runner, timeout=12) == ("早安", "雅婷", "早安。")
    assert captured["command"] == ["C:/tools/claude.cmd", "-p", "--output-format", "json"]
    prompt = script_gen.build_prompt(request_data)
    assert all(prompt not in arg and request_data.topic not in arg for arg in captured["command"])
    assert captured["input"] == prompt
    assert "stdin" not in captured
    assert captured["timeout"] == 12
    assert captured["encoding"] == "utf-8"


def test_missing_claude_does_not_call_runner(monkeypatch, request_data):
    monkeypatch.setattr(script_gen.shutil, "which", lambda name: None)

    def forbidden(*args, **kwargs):
        pytest.fail("missing CLI must not execute anything")

    with pytest.raises(script_gen.ClaudeNotFoundError, match="安裝並登入 Claude Code"):
        script_gen.generate_script(request_data, runner=forbidden)


@pytest.mark.parametrize("stdout", ["not json", "[]", "{}", '{"result": 1}', '{"result":" "}', '{"is_error":true,"result":"error"}'])
def test_bad_cli_response(monkeypatch, request_data, stdout):
    monkeypatch.setattr(script_gen.shutil, "which", lambda name: "claude")
    with pytest.raises(script_gen.ScriptGenerationError):
        script_gen.generate_script(request_data, runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=stdout))


def test_cli_timeout(monkeypatch, request_data):
    monkeypatch.setattr(script_gen.shutil, "which", lambda name: "claude")

    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(script_gen.ScriptGenerationError, match="逾時"):
        script_gen.generate_script(request_data, runner=runner)
