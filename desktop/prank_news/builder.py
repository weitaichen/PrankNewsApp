"""Copy the PWA contract into a self-contained static deployment directory."""

import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from email.utils import format_datetime
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

from .models import Episode
from .show import load_show


def default_template_dir() -> Path:
    """Support source checkouts and PyInstaller's bundled data directory."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "pwa_template"
    return Path(__file__).resolve().parents[2] / "pwa_template"


def _build_paths(template_dir: str | Path, out_dir: str | Path) -> tuple[Path, Path]:
    template = Path(template_dir).resolve()
    raw_output = Path(out_dir).absolute()
    if raw_output.is_symlink() or raw_output.is_junction():
        raise ValueError("輸出資料夾不可是符號連結。")
    output = raw_output.resolve()
    if not template.is_dir():
        raise FileNotFoundError(f"找不到 PWA 範本資料夾：{template}")
    # Validate absolute deletion targets before touching an existing directory.
    if (
        output == Path(output.anchor)
        or template.is_relative_to(output)
        or output.is_relative_to(template)
        or Path(__file__).resolve().is_relative_to(output)
        or Path.cwd().resolve().is_relative_to(output)
    ):
        raise ValueError("輸出資料夾不可包含程式或範本，也不可位於範本內。")
    if output.exists() and not output.is_dir():
        raise ValueError("輸出路徑必須是資料夾。")
    return template, output


def build_app(
    template_dir: str | Path,
    out_dir: str | Path,
    episode: Episode,
    cover_path: str | Path | None = None,
) -> Path:
    template, output = _build_paths(template_dir, out_dir)
    audio = Path(episode.audio_path).resolve()
    if not audio.is_file():
        raise FileNotFoundError(f"找不到音檔：{audio}")
    cover = Path(cover_path).resolve() if cover_path is not None else None
    if cover is not None and not cover.is_file():
        raise FileNotFoundError(f"找不到封面：{cover}")
    if not math.isfinite(episode.duration_sec) or episode.duration_sec <= 0:
        raise ValueError("音檔長度必須是正數。")

    output.parent.mkdir(parents=True, exist_ok=True)
    # Stage source files before clearing output; audio/cover may live inside it.
    with tempfile.TemporaryDirectory(prefix="prank-build-", dir=output.parent) as temp:
        staged = Path(temp) / "app"
        shutil.copytree(
            template,
            staged,
            ignore=shutil.ignore_patterns(
                "tests", "README.md", "episode.json", "episode.mp3",
                ".git", ".vercel", "__pycache__", ".pytest_cache",
                "node_modules", "show.json", "episodes.json", "episodes", "feed.xml", "podcast-cover.png",
            ),
        )
        shutil.copy2(audio, staged / "episode.mp3")
        if cover is not None:
            shutil.copy2(cover, staged / "cover.png")
        build_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex
        worker = staged / "sw.js"
        worker.write_text(worker.read_text(encoding="utf-8").replace("__BUILD_ID__", build_id), encoding="utf-8")
        metadata = {
            "buildId": build_id,
            "show": episode.show,
            "title": episode.title,
            "anchor": episode.anchor,
            "published": episode.published,
            "durationSec": round(episode.duration_sec, 3),
            "audio": f"episode.mp3?v={build_id}",
            "cover": f"cover.png?v={build_id}",
            "description": "今日頭條新聞",
        }
        (staged / "episode.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        config_path = staged / "vercel.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        config.pop("name", None)
        config["headers"] = config.get("headers", []) + [
                {"source": path, "headers": [{"key": "Cache-Control", "value": "no-cache"}]}
                for path in ("/sw.js", "/episode.json")
            ] + [{
                "source": "/episode.mp3",
                "headers": [{"key": "Accept-Ranges", "value": "bytes"}],
            }]
        (staged / "vercel.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            shutil.rmtree(output)
        staged.replace(output)
    return output


ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
FONT_PATHS = [Path("C:/Windows/Fonts") / name for name in ("msjhbd.ttc", "msjh.ttc", "mingliu.ttc")]


def _show_cover(title: str, template: Path, destination: Path) -> None:
    font_path = None
    for path in FONT_PATHS:
        try:
            ImageFont.truetype(str(path), 120)
            font_path = path
            break
        except OSError:
            continue
    if font_path is None:
        with Image.open(template / "cover.png") as source:
            cover = source.convert("RGB").resize((1400, 1400), Image.Resampling.LANCZOS)
    else:
        cover = Image.new("RGB", (1400, 1400), "#111820")
        draw = ImageDraw.Draw(cover)
        draw.rounded_rectangle((100, 100, 1300, 1300), radius=70, outline="#2d475b", width=5)
        # Wrap by measured glyph width, shrinking long titles to fit the cover.
        for size in range(160, 23, -4):
            font = ImageFont.truetype(str(font_path), size)
            lines, line = [], ""
            for char in title:
                if line and draw.textlength(line + char, font=font) > 1080:
                    lines.append(line)
                    line = ""
                line += char
            lines.append(line)
            if len(lines) * (size * 1.4) <= 950:
                break
        y = (1400 - len(lines) * size * 1.4) / 2
        for line in lines:
            draw.text((700, y), line, font=font, fill="#f4f6f8", anchor="mt")
            y += size * 1.4
    cover.save(destination, format="PNG")
    cover.resize((512, 512), Image.Resampling.LANCZOS).save(destination.parent / "cover.png", format="PNG")


def build_show_site(show_dir: str | Path, template_dir: str | Path,
                    out_dir: str | Path, base_url: str) -> Path:
    template, output = _build_paths(template_dir, out_dir)
    directory = Path(show_dir).resolve()
    if directory.is_relative_to(output) or output.is_relative_to(directory):
        raise ValueError("輸出資料夾不可包含節目庫，也不可位於節目庫內。")
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("節目網址必須是 https 絕對網址，且不可含路徑或查詢。")
    base_url = base_url.rstrip("/")
    show = load_show(directory.name, root_dir=directory.parent)
    episodes = show.episodes
    if not episodes:
        raise ValueError("節目尚無單集，請先產生語音。")
    latest = episodes[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="show-build-", dir=output.parent) as temp:
        staging = Path(temp)
        _show_cover(show.title, template, staging / "podcast-cover.png")
        current = Episode(show.title, latest["title"], show.anchor, latest["published"],
                          latest["durationSec"], "", directory / latest["file"])
        site = build_app(template, staging / "site", current, staging / "cover.png")
        (site / "episode.mp3").unlink()
        shutil.copy2(staging / "podcast-cover.png", site / "podcast-cover.png")
        (site / "episodes").mkdir()
        for episode in episodes:
            source = (directory / episode["file"]).resolve()
            if (source.parent != directory / "episodes" or episode["file"] != f"episodes/{episode['id']}.mp3"
                    or not all(char.isascii() and (char.isalnum() or char == "-") for char in episode["id"])):
                raise ValueError("單集音檔路徑不正確。")
            shutil.copy2(source, site / episode["file"])
        metadata_path = site / "episode.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # Use the neutral episode ID for both worker and media cache versions.
        worker = site / "sw.js"
        worker.write_text(worker.read_text(encoding="utf-8").replace(metadata["buildId"], latest["id"]), encoding="utf-8")
        metadata.update(buildId=latest["id"], audio=f"{latest['file']}?v={latest['id']}",
                        cover=f"cover.png?v={latest['id']}", feedUrl=f"{base_url}/feed.xml")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        ET.register_namespace("itunes", ITUNES)
        ET.register_namespace("content", CONTENT)
        rss = ET.Element("rss", {"version": "2.0", "xmlns:content": CONTENT})
        channel = ET.SubElement(rss, "channel")
        def element(parent, tag, value=None, **attrs):
            node = ET.SubElement(parent, tag, attrs)
            if value is not None:
                node.text = str(value)
            return node
        for tag, text in (("title", show.title), ("link", base_url), ("language", "zh-tw"),
                          ("description", show.description), (f"{{{ITUNES}}}author", show.anchor),
                          (f"{{{ITUNES}}}summary", show.description), (f"{{{ITUNES}}}explicit", "false"),
                          (f"{{{ITUNES}}}type", "episodic"), (f"{{{ITUNES}}}block", "Yes"),
                          ("lastBuildDate", format_datetime(datetime.now(timezone.utc)))):
            element(channel, tag, text)
        element(channel, f"{{{ITUNES}}}image", href=f"{base_url}/podcast-cover.png")
        element(channel, f"{{{ITUNES}}}category", text="News")
        for episode in episodes:
            item = element(channel, "item")
            element(item, "title", episode["title"])
            element(item, "description", "今日頭條新聞")
            element(item, "guid", episode["id"], isPermaLink="false")
            element(item, "pubDate", format_datetime(datetime.fromisoformat(episode["published"])))
            element(item, "enclosure", url=f"{base_url}/{episode['file']}",
                    length=str((site / episode["file"]).stat().st_size), type="audio/mpeg")
            element(item, f"{{{ITUNES}}}duration", round(episode["durationSec"]))
            element(item, f"{{{ITUNES}}}episodeType", "full")
        ET.ElementTree(rss).write(site / "feed.xml", encoding="utf-8", xml_declaration=True)
        config_path = site / "vercel.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["headers"].extend([
            {"source": "/feed.xml", "headers": [
                {"key": "Content-Type", "value": "application/rss+xml; charset=utf-8"},
                {"key": "Cache-Control", "value": "no-cache"}]},
            {"source": "/episodes/(.*)", "headers": [{"key": "Accept-Ranges", "value": "bytes"}]},
        ])
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            shutil.rmtree(output)
        site.replace(output)
    return output
