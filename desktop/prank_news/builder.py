"""Copy the PWA contract into a self-contained static deployment directory."""

import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

from .models import Episode


def default_template_dir() -> Path:
    """Support source checkouts and PyInstaller's bundled data directory."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "pwa_template"
    return Path(__file__).resolve().parents[2] / "pwa_template"


def build_app(
    template_dir: str | Path,
    out_dir: str | Path,
    episode: Episode,
    cover_path: str | Path | None = None,
) -> Path:
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
            ),
        )
        shutil.copy2(audio, staged / "episode.mp3")
        if cover is not None:
            shutil.copy2(cover, staged / "cover.png")
        metadata = {
            "show": episode.show,
            "title": episode.title,
            "anchor": episode.anchor,
            "published": episode.published,
            "durationSec": round(episode.duration_sec, 3),
            "audio": "episode.mp3",
            "cover": "cover.png",
            "description": "今日頭條新聞",
        }
        (staged / "episode.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        config = {
            "headers": [
                {"source": path, "headers": [{"key": "Cache-Control", "value": "no-cache"}]}
                for path in ("/sw.js", "/episode.json")
            ] + [{
                "source": "/episode.mp3",
                "headers": [{"key": "Accept-Ranges", "value": "bytes"}],
            }],
        }
        (staged / "vercel.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        if output.exists():
            shutil.rmtree(output)
        staged.replace(output)
    return output
