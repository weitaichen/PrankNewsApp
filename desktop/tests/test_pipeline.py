import json
import re

import pytest

from prank_news import pipeline


def test_generation_stage_order_and_actual_duration(monkeypatch, tmp_path, request_data):
    monkeypatch.setattr(pipeline, "generate_script", lambda request: ("早安台灣", "雅婷", "王小明早安。"))
    calls = []

    def synthesize(text, out_path, voice):
        calls.append((text, voice))
        out_path.write_bytes(b"audio")
        return 42.5

    monkeypatch.setattr(pipeline, "synthesize", synthesize)
    stages = []
    episode = pipeline.generate_episode(request_data, tmp_path / "work", lambda stage, msg: stages.append(stage))
    assert stages == ["script", "tts", "done"]
    assert calls == [("王小明早安。", request_data.voice)]
    assert episode.duration_sec == 42.5
    assert episode.audio_path.is_file()
    assert episode.title.endswith("日 晨間新聞")


def test_script_override_skips_claude(monkeypatch, tmp_path, request_data):
    def forbidden(request):
        raise AssertionError("must not invoke Claude")

    monkeypatch.setattr(pipeline, "generate_script", forbidden)
    monkeypatch.setattr(pipeline, "synthesize", lambda *args: 5)
    episode = pipeline.generate_episode(request_data, tmp_path, script_text="早安。")
    assert episode.script == "早安。"
    assert episode.show == "晨間新聞快報"


def test_build_without_deploy(monkeypatch, tmp_path, template, episode):
    def forbidden(*args):
        raise AssertionError("deployment disabled")

    monkeypatch.setattr(pipeline, "deploy_app", forbidden)
    stages = []
    result = pipeline.build_and_deploy(
        episode, tmp_path / "app", deploy=False, template_dir=template,
        progress=lambda stage, msg: stages.append(stage),
    )
    assert stages == ["build", "done"]
    assert result["out_dir"] == tmp_path / "app"
    assert result["url"] is result["qr_path"] is None
    assert re.fullmatch(r"https://morning-news-[a-z0-9]{6}\.vercel\.app/feed.xml", result["feed_url"])
    assert episode.audio_path.parent == result["out_dir"] / "episodes"
    assert episode.audio_path.is_file()


def test_build_deploy_and_qr(monkeypatch, tmp_path, template, episode):
    calls = []

    def deploy(directory, name):
        calls.append((directory, name))
        return "https://prank-news.vercel.app"

    monkeypatch.setattr(pipeline, "deploy_app", deploy)
    stages = []
    result = pipeline.build_and_deploy(
        episode, tmp_path / "app", template_dir=template, project_name="prank-news",
        progress=lambda stage, msg: stages.append(stage),
    )
    assert stages == ["build", "deploy", "done"]
    assert calls == [(result["out_dir"], "prank-news")]
    assert result["url"] == "https://prank-news.vercel.app"
    assert result["qr_path"].is_file()


def test_core_default_project_is_neutral(monkeypatch, tmp_path, template, episode):
    names = []
    monkeypatch.setattr(pipeline, "deploy_app", lambda directory, name: names.append(name) or f"https://{name}.vercel.app")
    result = pipeline.build_and_deploy(episode, tmp_path / "app", template_dir=template)
    assert re.fullmatch(r"morning-news-[a-z0-9]{6}", names[0])
    assert "prank" not in result["url"]


@pytest.mark.parametrize("show, anchor, title", [
    ("王小明專屬早報", "小明主播", "小明新聞"),
    ("小明專屬早報", "王小明", "王小明新聞"),
])
def test_build_sanitizes_all_public_metadata(tmp_path, template, episode, show, anchor, title):
    episode.passenger_names = ["王小明"]
    episode.show, episode.anchor, episode.title = show, anchor, title
    result = pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False, template_dir=template)
    public = (result["out_dir"] / "episode.json").read_text(encoding="utf-8")
    assert "王小明" not in public and "小明" not in public
    data = json.loads(public)
    assert "passenger_names" not in data and "script" not in data
    metadata = json.loads(public)
    assert metadata["show"] == "晨間新聞快報"
    assert metadata["title"].endswith("日 晨間新聞")
    assert metadata["anchor"] == "主播 林雅婷"


def test_script_file_names_reach_build_guard(monkeypatch, tmp_path, template, request_data):
    def tts(text, path, voice):
        path.write_bytes(b"audio")
        return 5

    monkeypatch.setattr(pipeline, "synthesize", tts)
    episode = pipeline.generate_episode(request_data, tmp_path / "work",
        script_text="節目：王小明專屬早報\n主播：小明\n\n王小明早安。")
    result = pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False, template_dir=template)
    public = (result["out_dir"] / "episode.json").read_text(encoding="utf-8")
    assert "王小明" not in public and "小明" not in public


def test_default_anchor_cannot_leak_matching_passenger(episode):
    episode.passenger_names = ["林雅婷"]
    pipeline.sanitize_metadata(episode)
    assert "林雅婷" not in episode.anchor and "雅婷" not in episode.anchor


def test_generate_to_fixed_show_and_qr_encodes_player_url(monkeypatch, tmp_path, template, request_data):
    from prank_news.show import create_show
    show = create_show("固定晨報", "主播", "morning-news-fixed")
    seen = []
    def generate(request):
        assert request.show_title == show.title and request.anchor_name == show.anchor
        return "乘客名字", "乘客名字", "王小明早安。"
    def tts(script, path, voice):
        path.write_bytes(b"audio")
        return 3
    monkeypatch.setattr(pipeline, "generate_script", generate)
    monkeypatch.setattr(pipeline, "synthesize", tts)
    monkeypatch.setattr(pipeline, "deploy_app", lambda directory, project: seen.append(project) or f"https://{project}.vercel.app")
    monkeypatch.setattr(pipeline, "make_qr", lambda url, path: seen.append(url) or path)
    result = pipeline.generate_and_deploy(request_data, show, tmp_path / "work", tmp_path / "app", template_dir=template)
    assert seen == [show.project, "https://morning-news-fixed.vercel.app"]
    assert result["feed_url"] == "https://morning-news-fixed.vercel.app/feed.xml"
    assert result["qr_path"] == result["out_dir"] / "qr.png"
