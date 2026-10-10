from datetime import datetime
import re
import subprocess
import sys

import pytest

from prank_news import gui, pipeline
from prank_news.deploy import deploy


@pytest.mark.parametrize(("text", "expected"), [
    ("王小明、陳美麗", ["王小明", "陳美麗"]),
    (" 王小明, 陳美麗， 林大華 、 ", ["王小明", "陳美麗", "林大華"]),
    (" ,、， \n", []),
    ("Mary Jane", ["Mary Jane"]),
    ("王小明、王小明", ["王小明", "王小明"]),
])
def test_parse_names(text, expected):
    assert gui.parse_names(text) == expected


def test_estimate_minutes_counts_visible_characters():
    assert gui.script_character_count("早安。 \n\t台灣！") == 6
    assert gui.estimate_minutes("早安。 \n\t台灣！") == 6 / 250
    assert gui.estimate_minutes("字" * 750) == 3
    assert gui.estimate_minutes(" \n\t") == 0


def test_default_project_name(monkeypatch):
    monkeypatch.setattr(gui.secrets, "choice", lambda alphabet: "a")
    assert gui.default_project_name() == "morning-news-aaaaaa"
    assert re.fullmatch(r"morning-news-[a-z0-9]{6}", gui.default_project_name())


@pytest.mark.parametrize("name", ["a", "0", "morning-news-a1b2c3", "a" * 100])
def test_valid_project_names_match_core(monkeypatch, tmp_path, name):
    assert gui.validate_project_name(name) == name
    monkeypatch.setattr("prank_news.deploy.shutil.which", lambda command: "npx")
    assert deploy(tmp_path, name, runner=lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, "https://example.vercel.app\n", ""
    )) == "https://example.vercel.app"


@pytest.mark.parametrize("name", ["", "UPPER", "a_b", "-a", "a-", "a" * 101, "a b", "新聞", "a\n"])
def test_invalid_project_names_match_core(tmp_path, name):
    with pytest.raises(ValueError):
        gui.validate_project_name(name)
    with pytest.raises(ValueError):
        deploy(tmp_path, name, runner=lambda *args, **kwargs: pytest.fail("must not invoke Vercel"))


def test_output_directory_is_timestamped_child_without_io(tmp_path):
    base = tmp_path / "Documents" / "PrankNews"
    when = datetime(2026, 10, 10, 17, 30, 45, 123456)
    output = gui.output_directory(base, when)
    assert output == base / "20261010-173045-123456"
    assert not base.exists()
    assert gui.output_directory(base, when.replace(microsecond=123457)) != output


def test_import_does_not_create_window():
    result = subprocess.run(
        [sys.executable, "-c", "import tkinter; "
         "tkinter.Tk = lambda *a, **k: (_ for _ in ()).throw(AssertionError('window created')); "
         "import prank_news.gui"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_edited_script_synthesis_preserves_exact_text_and_builds_app(monkeypatch, tmp_path, template):
    edited = "節目：這行是口白\n主播：也是口白\n\n  #使用者編修 *稿子*\n"
    calls = []

    def synthesize(text, path, voice):
        calls.append((text, voice))
        path.write_bytes(b"fake-audio")
        return 12.5

    monkeypatch.setattr(pipeline, "synthesize", synthesize)
    monkeypatch.setattr(pipeline, "generate_script", lambda *args: pytest.fail("must not invoke Claude"))
    monkeypatch.setattr(pipeline, "deploy_app", lambda *args: pytest.fail("must not deploy"))
    stages = []
    progress = lambda stage, message: stages.append(stage)
    episode = pipeline.synthesize_episode(" 自訂節目 ", " 自訂主播 ", edited,
                                          gui.VOICES["男聲 雲哲"], tmp_path / "work", progress)
    result = pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False,
                                      template_dir=template, progress=progress)
    assert calls == [(edited, "zh-TW-YunJheNeural")]
    assert episode.script == edited
    assert (episode.show, episode.anchor) == ("自訂節目", "自訂主播")
    assert episode.duration_sec == 12.5
    assert episode.audio_path == result["out_dir"] / "episode.mp3"
    assert episode.audio_path.read_bytes() == b"fake-audio"
    assert stages == ["tts", "done", "build", "done"]


@pytest.mark.parametrize(("show", "anchor", "script", "voice"), [
    ("節目", "主播", " \n", "voice"),
    (" ", "主播", "稿子", "voice"),
    ("節目", " ", "稿子", "voice"),
    ("節目", "主播", "稿子", " "),
])
def test_synthesis_rejects_empty_fields_before_work(monkeypatch, tmp_path, show, anchor, script, voice):
    monkeypatch.setattr(pipeline, "synthesize", lambda *args: pytest.fail("must not call TTS"))
    work = tmp_path / "work"
    with pytest.raises(ValueError):
        pipeline.synthesize_episode(show, anchor, script, voice, work)
    assert not work.exists()
