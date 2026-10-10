"""Local show library. Only neutral metadata and audio belong in this directory."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .project import default_project_name, validate_project_name

DEFAULT_SHOW = "晨間新聞快報"
DEFAULT_ANCHOR = "主播 林雅婷"
DEFAULT_DESCRIPTION = "每日晨間新聞，快速掌握今日大小事。"
MAX_EPISODES = 20


def default_shows_root() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "PrankNews" / "shows"


def contains_passenger(text: str, names: list[str]) -> bool:
    fragments = set()
    for name in names:
        name = name.strip()
        if name:
            fragments.add(name.casefold())
            fragments.update(name[i:i + 2].casefold() for i in range(1, len(name) - 1))
    return any(fragment in text.casefold() for fragment in fragments)


def safe_metadata(value: str, fallback: str, names: list[str], neutral: str) -> str:
    if contains_passenger(value, names):
        value = fallback
    if contains_passenger(value, names):
        value = neutral
    if contains_passenger(value, names):
        raise ValueError("節目資料與乘客名字重疊，請調整節目設定。")
    return value


def _write_json(path: Path, data) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class Show:
    project: str
    title: str
    anchor: str
    description: str
    created: str
    directory: Path

    @property
    def episodes(self) -> list[dict]:
        return json.loads((self.directory / "episodes.json").read_text(encoding="utf-8"))


def create_show(title: str = DEFAULT_SHOW, anchor: str = DEFAULT_ANCHOR,
                project: str | None = None, description: str = DEFAULT_DESCRIPTION,
                *, root_dir: str | Path | None = None,
                passenger_names: list[str] | None = None) -> Show:
    project = validate_project_name(project or default_project_name())
    data = dict(project=project, title=title.strip(), anchor=anchor.strip(),
                description=description.strip(), created=datetime.now(timezone.utc).isoformat())
    if any(not data[key] for key in ("title", "anchor", "description")):
        raise ValueError("節目名、主播名與說明不可空白。")
    if any(contains_passenger(value, passenger_names or []) for value in data.values()):
        raise ValueError("節目設定不可包含乘客名字或去姓的名字片段，請使用中性節目名與主播名。")
    root = Path(root_dir) if root_dir is not None else default_shows_root()
    directory = root / project
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "episodes").mkdir()
    _write_json(directory / "show.json", data)
    _write_json(directory / "episodes.json", [])
    show = Show(**data, directory=directory.resolve())
    mark_used(show)
    return show


def load_show(project: str, *, root_dir: str | Path | None = None) -> Show:
    validate_project_name(project)
    root = Path(root_dir) if root_dir is not None else default_shows_root()
    directory = (root / project).resolve()
    data = json.loads((directory / "show.json").read_text(encoding="utf-8"))
    if data["project"] != project:
        raise ValueError("節目資料的專案名稱與資料夾不相符。")
    return Show(**data, directory=directory)


def list_shows(*, root_dir: str | Path | None = None) -> list[Show]:
    root = Path(root_dir) if root_dir is not None else default_shows_root()
    if not root.exists():
        return []
    shows = [load_show(path.parent.name, root_dir=root) for path in root.glob("*/show.json")]
    last = (root / ".last-show").read_text(encoding="utf-8").strip() if (root / ".last-show").exists() else ""
    return sorted(shows, key=lambda show: (show.project == last, show.created), reverse=True)


def mark_used(show: Show) -> None:
    (show.directory.parent / ".last-show").write_text(show.project, encoding="utf-8")


def validate_show_privacy(show: Show, passenger_names: list[str]) -> None:
    values = [show.project, show.title, show.anchor, show.description, show.created]
    values.extend(json.dumps(item, ensure_ascii=False) for item in show.episodes)
    if any(contains_passenger(value, passenger_names) for value in values):
        raise ValueError("節目資料含乘客名字或去姓片段，請選擇或建立中性節目。")


def _chinese_number(number: int) -> str:
    digits = "零一二三四五六七八九"
    if number < 10:
        return digits[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return (digits[tens] if tens > 1 else "") + "十" + (digits[ones] if ones else "")
    return str(number)


def _episode_number(title: str) -> int:
    suffix = re.search(r"（(.+)）$", title)
    if not suffix:
        return 1
    text = suffix[1]
    if text.isdecimal():
        return int(text)
    return next((n for n in range(2, 100) if _chinese_number(n) == text), 1)


def add_episode(show: Show, mp3_path: str | Path, duration_sec: float,
                *, when: datetime | None = None, passenger_names: list[str] | None = None) -> dict:
    if isinstance(duration_sec, bool) or not math.isfinite(duration_sec) or duration_sec <= 0:
        raise ValueError("音檔長度必須是正數。")
    names = passenger_names or []
    validate_show_privacy(show, names)
    published = when or datetime.now().astimezone()
    if published.utcoffset() is None:
        raise ValueError("發布時間必須包含時區。")
    episodes = show.episodes
    same_day = [item for item in episodes if datetime.fromisoformat(item["published"]).date() == published.date()]
    number = max((_episode_number(item["title"]) for item in same_day), default=0) + 1
    title = f"{published.month}月{published.day}日 晨間新聞"
    if number > 1:
        title += f"（{_chinese_number(number)}）"
    title = safe_metadata(title, "今日新聞", names, "新聞快報")
    for attempt in range(100):
        build_id = published.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex
        if contains_passenger(build_id.split("-")[0], names):
            build_id = uuid4().hex
        file = f"episodes/{build_id}.mp3"
        if not contains_passenger(file, names) and not (show.directory / file).exists():
            break
        if contains_passenger("episodes/.mp3", names):
            raise ValueError("音檔路徑與乘客名字重疊，請調整乘客名字。")
    else:
        raise ValueError("無法產生不含乘客名字的單集 ID，請調整乘客名字。")
    destination = show.directory / file
    shutil.copy2(mp3_path, destination)
    episode = dict(id=build_id, title=title, published=published.isoformat(),
                   durationSec=round(duration_sec, 3), file=file, bytes=destination.stat().st_size)
    retained = [episode, *episodes][:MAX_EPISODES]
    _write_json(show.directory / "episodes.json", retained)
    for old in episodes[MAX_EPISODES - 1:]:
        path = (show.directory / old["file"]).resolve()
        if path.parent != (show.directory / "episodes").resolve():
            raise ValueError("單集檔案路徑必須位於節目的 episodes 資料夾。")
        path.unlink(missing_ok=True)
    mark_used(show)
    return episode
