from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from prank_news import builder, pipeline
from prank_news.show import create_show, add_episode

WHEN = datetime(2026, 10, 10, 8, tzinfo=timezone(timedelta(hours=8)))


def test_rss_namespaces_https_enclosures_order_guids_and_latest_player(tmp_path, template):
    show = create_show('晨間 & <新聞> "快報"', '主播 & 林雅婷', project="morning-news-rss",
                       description="今日 & 明日 <新聞>")
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"audio-one")
    first = add_episode(show, audio, 20.7, when=WHEN)
    audio.write_bytes(b"audio-two-longer")
    latest = add_episode(show, audio, 30, when=WHEN + timedelta(minutes=5))
    (template / "sw.js").write_text("const CACHE_VERSION = '__BUILD_ID__';")
    original_header = {"source": "/(.*)", "headers": [{"key": "X-Content-Type-Options", "value": "nosniff"}]}
    (template / "vercel.json").write_text(json.dumps({"headers": [original_header]}))
    base = "https://morning-news-rss.vercel.app"
    output = builder.build_show_site(show.directory, template, tmp_path / "app", base)
    body = (output / "feed.xml").read_text(encoding="utf-8")
    assert f'xmlns:itunes="{builder.ITUNES}"' in body
    assert f'xmlns:content="{builder.CONTENT}"' in body
    channel = ET.fromstring(body).find("channel")
    assert channel.findtext("title") == show.title
    assert channel.findtext("link") == base
    assert channel.findtext("language") == "zh-tw"
    assert channel.findtext("description") == show.description
    ns = {"itunes": builder.ITUNES}
    for tag, value in {"author": show.anchor, "summary": show.description, "block": "Yes",
                       "explicit": "false", "type": "episodic"}.items():
        assert channel.findtext(f"itunes:{tag}", namespaces=ns) == value
    assert channel.find("itunes:image", ns).attrib == {"href": f"{base}/podcast-cover.png"}
    assert channel.find("itunes:category", ns).attrib == {"text": "News"}
    assert parsedate_to_datetime(channel.findtext("lastBuildDate")).utcoffset() is not None
    items = channel.findall("item")
    assert [item.findtext("guid") for item in items] == [latest["id"], first["id"]]
    assert len({item.findtext("guid") for item in items}) == 2
    for node, item in zip(items, [latest, first]):
        assert node.find("guid").get("isPermaLink") == "false"
        enclosure = node.find("enclosure")
        assert enclosure.get("url") == f"{base}/{item['file']}"
        assert enclosure.get("type") == "audio/mpeg"
        assert int(enclosure.get("length")) == item["bytes"] == (output / item["file"]).stat().st_size
        assert parsedate_to_datetime(node.findtext("pubDate")) == datetime.fromisoformat(item["published"])
        assert node.findtext("itunes:duration", namespaces=ns) == str(round(item["durationSec"]))
        assert node.findtext("itunes:episodeType", namespaces=ns) == "full"
    metadata = json.loads((output / "episode.json").read_text(encoding="utf-8"))
    assert metadata["show"] == show.title and metadata["anchor"] == show.anchor
    assert metadata["title"] == latest["title"]
    assert metadata["audio"] == f"{latest['file']}?v={metadata['buildId']}"
    assert metadata["feedUrl"] == f"{base}/feed.xml"
    assert metadata["buildId"] in (output / "sw.js").read_text()
    headers = json.loads((output / "vercel.json").read_text())["headers"]
    assert original_header in headers
    assert {entry["source"] for entry in headers} >= {"/sw.js", "/episode.json", "/feed.xml", "/episodes/(.*)"}
    assert next(h for h in headers if h["source"] == "/feed.xml")["headers"] == [
        {"key": "Content-Type", "value": "application/rss+xml; charset=utf-8"},
        {"key": "Cache-Control", "value": "no-cache"}]
    assert not (output / "show.json").exists() and not (output / "episodes.json").exists()
    assert not (output / "episode.mp3").exists()


def test_missing_fonts_resize_template_to_rgb_cover(monkeypatch, tmp_path, template):
    monkeypatch.setattr(builder, "FONT_PATHS", [tmp_path / "missing.ttf"])
    Image.new("RGBA", (20, 20), (35, 45, 55, 100)).save(template / "cover.png")
    show = create_show()
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"audio")
    add_episode(show, audio, 2)
    output = builder.build_show_site(show.directory, template, tmp_path / "app", f"https://{show.project}.vercel.app")
    for name, size in (("podcast-cover.png", 1400), ("cover.png", 512)):
        with Image.open(output / name) as image:
            assert image.size == (size, size) and image.mode == "RGB" and image.format == "PNG"
            assert image.getpixel((0, 0)) == (35, 45, 55)


def test_system_font_cover_is_1400_rgb(tmp_path, template):
    if not any(path.exists() for path in builder.FONT_PATHS):
        pytest.skip("此環境沒有 Windows 中文字型")
    builder._show_cover("晨間新聞快報", template, tmp_path / "podcast-cover.png")
    with Image.open(tmp_path / "podcast-cover.png") as cover:
        assert cover.mode == "RGB" and cover.size == (1400, 1400)
        assert len(cover.getcolors(2_000_000)) > 2


@pytest.mark.parametrize("url", ["http://news.test", "/relative", "https://news.test/path", "https://user@news.test", "https://news.test?query=1"])
def test_invalid_base_url_preserves_output(tmp_path, template, url):
    show = create_show()
    output = tmp_path / "app"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="https"):
        builder.build_show_site(show.directory, template, output, url)
    assert marker.read_text() == "keep"


def test_show_library_cannot_be_replaced_by_build(tmp_path, template):
    show = create_show()
    with pytest.raises(ValueError, match="節目庫"):
        builder.build_show_site(show.directory, template, show.directory, f"https://{show.project}.vercel.app")
    assert (show.directory / "show.json").is_file()


def test_passenger_and_script_never_enter_metadata_or_filenames(monkeypatch, tmp_path, template, request_data):
    request_data.show_title = "固定晨報"
    request_data.anchor_name = "主播"
    show = create_show(request_data.show_title, request_data.anchor_name)
    monkeypatch.setattr(pipeline, "generate_script", lambda request: ("小明專屬", "小美", "王小明與陳小美，吐司唱歌。"))
    def tts(script, path, voice):
        path.write_bytes(b"audio")
        return 3
    monkeypatch.setattr(pipeline, "synthesize", tts)
    episode = pipeline.generate_episode(request_data, tmp_path / "work")
    assert episode.show == show.title and episode.anchor == show.anchor
    result = pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False, show=show, template_dir=template)
    for path in [show.directory / "show.json", show.directory / "episodes.json",
                 result["out_dir"] / "feed.xml", result["out_dir"] / "episode.json"]:
        text = path.read_text(encoding="utf-8")
        for private in ("王小明", "小明", "陳小美", "小美", "吐司唱歌"):
            assert private not in text
    for directory in (show.directory, result["out_dir"]):
        for path in directory.rglob("*"):
            assert all(name not in path.name for name in ("王小明", "小明", "陳小美", "小美"))
