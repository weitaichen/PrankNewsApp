"""Data shared by the CLI, pipeline, and desktop GUI."""

from dataclasses import dataclass
import math
from pathlib import Path


@dataclass
class NewsRequest:
    passenger_names: list[str]
    minutes: float
    topic: str
    style: str = "台灣電視新聞"
    voice: str = "zh-TW-HsiaoChenNeural"

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
        for field in ("topic", "style", "voice"):
            if not isinstance(getattr(self, field), str):
                raise ValueError(f"{field} 必須是文字。")
        if not self.style.strip() or not self.voice.strip():
            raise ValueError("新聞風格與語音不可空白。")


@dataclass
class Episode:
    show: str
    title: str
    anchor: str
    published: str
    duration_sec: float
    script: str
    audio_path: Path
