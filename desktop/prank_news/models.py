"""Data shared by the CLI, pipeline, and desktop GUI."""

from dataclasses import dataclass, field
import math
from pathlib import Path


@dataclass
class NewsRequest:
    passenger_names: list[str]
    minutes: float
    topic: str
    style: str = "台灣電視新聞"
    voice: str = "zh-TW-HsiaoChenNeural"
    show_title: str = "晨間新聞快報"
    anchor_name: str = "主播 林雅婷"

    def __post_init__(self) -> None:
        if not isinstance(self.passenger_names, list) or not self.passenger_names:
            raise ValueError("請至少輸入一位乘客名字。")
        if any(not isinstance(name, str) or not name.strip() for name in self.passenger_names):
            raise ValueError("乘客名字不可空白。")
        self.passenger_names = [name.strip() for name in self.passenger_names]
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, (int, float)):
            raise ValueError("新聞長度必須是 0.5–15 分鐘。")
        if not math.isfinite(self.minutes) or not 0.5 <= self.minutes <= 15:
            raise ValueError("新聞長度必須是 0.5–15 分鐘。")
        for field in ("topic", "style", "voice", "show_title", "anchor_name"):
            if not isinstance(getattr(self, field), str):
                raise ValueError(f"{field} 必須是文字。")
        if not self.style.strip() or not self.voice.strip():
            raise ValueError("新聞風格與語音不可空白。")
        if not self.show_title.strip() or not self.anchor_name.strip():
            raise ValueError("節目名與主播名不可空白。")
        from .show import safe_metadata
        self.show_title = safe_metadata(self.show_title.strip(), "晨間新聞快報", self.passenger_names, "新聞快報")
        self.anchor_name = safe_metadata(self.anchor_name.strip(), "主播 林雅婷", self.passenger_names, "主播")


@dataclass
class Episode:
    show: str
    title: str
    anchor: str
    published: str
    duration_sec: float
    script: str
    audio_path: Path
    # Private build context: never serialized into the public episode.json.
    passenger_names: list[str] = field(default_factory=list)
