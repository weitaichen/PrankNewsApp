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
    assert result == {"out_dir": tmp_path / "app", "url": None, "qr_path": None}
    assert episode.audio_path == result["out_dir"] / "episode.mp3"


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
