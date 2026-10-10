from datetime import datetime
import re
import subprocess
import sys
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest

from prank_news import gui, pipeline, project
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
    monkeypatch.setattr(project.secrets, "choice", lambda alphabet: "a")
    assert gui.default_project_name() == "morning-news-aaaaaa"
    assert re.fullmatch(r"morning-news-[a-z0-9]{6}", gui.default_project_name())
    assert gui.default_project_name is pipeline.default_project_name is project.default_project_name
    assert gui.validate_project_name is project.validate_project_name


@pytest.mark.parametrize("name", ["a", "0", "morning-news-a1b2c3", "a" * 100])
def test_valid_project_names_match_core(monkeypatch, tmp_path, name):
    assert gui.validate_project_name(name) == name
    monkeypatch.setattr("prank_news.deploy.shutil.which", lambda command: "npx")
    assert deploy(tmp_path, name, runner=lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, "https://example.vercel.app\n", ""
    ), public_check=lambda url: None) == f"https://{name}.vercel.app"


@pytest.mark.parametrize("name", ["", "UPPER", "a_b", "-a", "a-", "a" * 101, "a b", "新聞", "a\n", "news---test"])
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


def test_topic_hint_handles_combobox_popdown_focus():
    def focus():
        raise KeyError("popdown")
    calls = []
    window = SimpleNamespace(root=SimpleNamespace(focus_get=focus),
        topic=SimpleNamespace(get=lambda *a: ""),
        topic_hint=SimpleNamespace(place=lambda **k: calls.append(k), place_forget=lambda: None))
    gui.PrankNewsWindow._update_topic_hint(window)
    assert calls == [{"x": 5, "y": 3}]


def test_event_poll_reschedules_after_unexpected_exception():
    events = Queue()
    events.put(("progress", ("build", "working")))
    events.put(("success", (lambda result: None, "done")))
    scheduled = []
    def failed_status(value):
        raise RuntimeError("Tk update failed")
    window = gui.PrankNewsWindow.__new__(gui.PrankNewsWindow)
    window.closed = False
    window.events = events
    window.status = SimpleNamespace(set=failed_status)
    window.root = SimpleNamespace(after=lambda delay, callback: scheduled.append(callback) or "timer")
    window._set_busy = lambda value: scheduled.append(value)
    window._refresh_buttons = lambda: None
    with pytest.raises(RuntimeError):
        window._poll_events()
    assert window.poll_id == "timer" and scheduled[0] == window._poll_events
    window._poll_events()
    assert False in scheduled  # The next success event can still clear busy.


def test_gui_each_build_refreshes_project_and_passes_private_names(monkeypatch, tmp_path):
    window = gui.PrankNewsWindow.__new__(gui.PrankNewsWindow)
    names = iter(["morning-news-aaaaaa", "morning-news-bbbbbb"])
    monkeypatch.setattr(gui, "default_project_name", lambda: next(names))
    class Variable:
        def __init__(self, value): self.value = value
        def get(self): return self.value
        def set(self, value): self.value = value
    window.busy = False
    for key, value in (("project", "old-project"), ("names", "王小明"),
                       ("show", "王小明專屬早報"), ("anchor", "小明"),
                       ("voice", "女聲 曉臻"), ("base_dir", str(tmp_path))):
        setattr(window, key, Variable(value))
    window.script = SimpleNamespace(get=lambda *a: "王小明早安。")
    window._progress = lambda *a: None
    captured = []
    def synthesize(show, anchor, script, voice, directory, progress, *, passenger_names):
        captured.append(passenger_names)
        return SimpleNamespace(audio_path=Path(directory) / "episode.mp3")
    monkeypatch.setattr(gui, "synthesize_episode", synthesize)
    monkeypatch.setattr(gui, "build_and_deploy", lambda *a, **k: {"out_dir": tmp_path})
    window._start = lambda job, completed, message: job()
    window._build()
    first = window.project.get()
    window._build()
    assert first == "morning-news-aaaaaa" and window.project.get() == "morning-news-bbbbbb"
    assert captured == [["王小明"], ["王小明"]]


def test_gui_edited_metadata_is_sanitized_at_build(monkeypatch, tmp_path, template):
    def tts(text, path, voice):
        path.write_bytes(b"audio")
        return 1
    monkeypatch.setattr(pipeline, "synthesize", tts)
    episode = pipeline.synthesize_episode("王小明專屬早報", "小明", "王小明早安。", "voice",
                                          tmp_path / "work", passenger_names=["王小明"])
    result = pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False, template_dir=template)
    public = (result["out_dir"] / "episode.json").read_text(encoding="utf-8")
    assert "王小明" not in public and "小明" not in public
