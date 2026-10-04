import json
import sys
from pathlib import Path

import pytest

from prank_news.builder import build_app, default_template_dir


def test_build_structure_metadata_and_headers(tmp_path, template, episode):
    output = tmp_path / "app"
    output.mkdir()
    (output / "stale.txt").write_text("old")
    assert build_app(template, output, episode) == output
    assert {path.name for path in output.iterdir()} == {
        "index.html", "sw.js", "manifest.webmanifest", "cover.png", "assets",
        "episode.json", "episode.mp3", "vercel.json",
    }
    assert (output / "assets" / "app.js").is_file()
    assert (output / "episode.mp3").read_bytes() == episode.audio_path.read_bytes()
    assert (output / "cover.png").read_bytes() == b"template-cover"
    assert json.loads((output / "episode.json").read_text(encoding="utf-8")) == {
        "show": episode.show, "title": episode.title, "anchor": episode.anchor,
        "published": "2026-10-04", "durationSec": 180.25,
        "audio": "episode.mp3", "cover": "cover.png",
        "description": "今日頭條新聞",
    }
    assert "王小明" in episode.script
    metadata = json.loads((output / "episode.json").read_text(encoding="utf-8"))
    assert "王小明" not in json.dumps(metadata, ensure_ascii=False)
    headers = json.loads((output / "vercel.json").read_text())["headers"]
    assert headers == [
        {"source": "/sw.js", "headers": [{"key": "Cache-Control", "value": "no-cache"}]},
        {"source": "/episode.json", "headers": [{"key": "Cache-Control", "value": "no-cache"}]},
        {"source": "/episode.mp3", "headers": [{"key": "Accept-Ranges", "value": "bytes"}]},
    ]
    assert (template / "episode.json").read_text() == "old metadata"


def test_audio_and_custom_cover_inside_output_are_preserved(tmp_path, template, episode):
    output = tmp_path / "app"
    output.mkdir()
    episode.audio_path = output / "source.mp3"
    episode.audio_path.write_bytes(b"source-in-output")
    cover = output / "custom.png"
    cover.write_bytes(b"custom-cover")
    build_app(template, output, episode, cover)
    assert (output / "episode.mp3").read_bytes() == b"source-in-output"
    assert (output / "cover.png").read_bytes() == b"custom-cover"


def test_missing_input_does_not_clear_output(tmp_path, template, episode):
    output = tmp_path / "app"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep")
    episode.audio_path = tmp_path / "missing.mp3"
    with pytest.raises(FileNotFoundError):
        build_app(template, output, episode)
    assert marker.read_text() == "keep"


@pytest.mark.parametrize("target", ["same", "ancestor", "descendant"])
def test_template_overlap_rejected(tmp_path, template, episode, target):
    output = {"same": template, "ancestor": tmp_path, "descendant": template / "app"}[target]
    with pytest.raises(ValueError):
        build_app(template, output, episode)
    assert (template / "index.html").is_file()


def test_default_template_source_and_frozen(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert default_template_dir() == Path(__file__).resolve().parents[2] / "pwa_template"
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert default_template_dir() == tmp_path / "pwa_template"
