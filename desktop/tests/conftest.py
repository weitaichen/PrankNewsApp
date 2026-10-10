import pytest

from prank_news.models import Episode, NewsRequest


@pytest.fixture
def request_data():
    return NewsRequest(["王小明", "陳小美"], 3, "早餐店的吐司開始唱歌")


@pytest.fixture
def template(tmp_path):
    root = tmp_path / "template"
    root.mkdir()
    for name, content in {
        "index.html": "<html>news</html>", "sw.js": "// service worker",
        "manifest.webmanifest": "{}", "README.md": "private documentation",
        "episode.json": "old metadata", "episode.mp3": "old audio",
    }.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "cover.png").write_bytes(b"template-cover")
    (root / "tests").mkdir()
    (root / "tests" / "test.js").write_text("test")
    (root / "assets").mkdir()
    (root / "assets" / "app.js").write_text("// app")
    return root


@pytest.fixture
def episode(tmp_path):
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"fake-mp3-for-copy-test")
    return Episode(
        "晨間新聞快報", "2026年10月4日 晨間新聞", "主播 林雅婷",
        "2026-10-04", 180.25, "各位聽眾早安。\n\n王小明的吐司開始唱歌。", audio,
    )
