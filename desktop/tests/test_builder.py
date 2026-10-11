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
        "index.html", "sw.js", "manifest.json", "cover.png", "assets",
        "episode.json", "episode.mp3", "vercel.json",
    }
    assert (output / "assets" / "app.js").is_file()
    assert (output / "episode.mp3").read_bytes() == episode.audio_path.read_bytes()
    assert (output / "cover.png").read_bytes() == (template / "cover.png").read_bytes()
    built = json.loads((output / "episode.json").read_text(encoding="utf-8"))
    build_id = built["buildId"]
    assert built == {
        "buildId": build_id,
        "show": episode.show, "title": episode.title, "anchor": episode.anchor,
        "published": "2026-10-04", "durationSec": 180.25,
        "audio": f"episode.mp3?v={build_id}", "cover": f"cover.png?v={build_id}",
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


def test_each_build_versions_worker_and_media_together(tmp_path, template, episode):
    (template / "sw.js").write_text("const CACHE_VERSION = '__BUILD_ID__';", encoding="utf-8")
    builds = []
    for name in ("one", "two"):
        output = build_app(template, tmp_path / name, episode)
        metadata = json.loads((output / "episode.json").read_text(encoding="utf-8"))
        build_id = metadata["buildId"]
        assert build_id in (output / "sw.js").read_text(encoding="utf-8")
        assert metadata["audio"].endswith(f"?v={build_id}")
        assert metadata["cover"].endswith(f"?v={build_id}")
        builds.append(build_id)
    assert builds[0] != builds[1]
    assert "__BUILD_ID__" in (template / "sw.js").read_text(encoding="utf-8")


def test_builder_excludes_deployment_and_node_directories(tmp_path, template, episode):
    for name in (".vercel", "node_modules"):
        (template / name).mkdir()
        (template / name / "private.json").write_text("private")
    output = build_app(template, tmp_path / "app", episode)
    assert not (output / ".vercel").exists()
    assert not (output / "node_modules").exists()
