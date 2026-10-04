"""Synchronous edge-tts interface with sentence-based recovery for long text."""

import asyncio
import re
import tempfile
from pathlib import Path

import edge_tts
from mutagen.mp3 import MP3


class SynthesisError(RuntimeError):
    """Speech synthesis or MP3 validation failed."""


def _chunks(text: str, limit: int = 1000) -> list[str]:
    sentences = re.findall(r"[^。！？.!?\n]+[。！？.!?\n]*|[。！？.!?\n]+", text)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        for offset in range(0, len(sentence), limit):
            piece = sentence[offset:offset + limit]
            if current and len(current) + len(piece) > limit:
                result.append(current)
                current = ""
            current += piece
    if current:
        result.append(current)
    return result


async def _save(text: str, path: Path, voice: str, rate: str) -> float:
    try:
        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
    except Exception:
        chunks = _chunks(text)
        if len(chunks) < 2:
            raise
        # edge-tts emits MPEG audio frames; joining their bytes requires no ffmpeg.
        # Sum per-part durations: MP3 parsers may only count a first stream header.
        duration = 0.0
        with tempfile.TemporaryDirectory(prefix="tts-parts-", dir=path.parent) as temp:
            with path.open("wb") as output:
                for index, chunk in enumerate(chunks):
                    part = Path(temp) / f"{index}.mp3"
                    await edge_tts.Communicate(chunk, voice, rate=rate).save(str(part))
                    duration += MP3(part).info.length
                    output.write(part.read_bytes())
        return duration
    return MP3(path).info.length


def synthesize(text: str, out_path: str | Path, voice: str, rate: str = "+0%") -> float:
    """Save an MP3 and return its measured duration in seconds.

    Call from a GUI worker thread, not a thread with a running asyncio loop.
    Failed attempts leave an existing destination intact.
    """
    if not text.strip():
        raise ValueError("播報稿不可空白。")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise SynthesisError("同步 synthesize 請在 GUI 工作執行緒呼叫，不可在 asyncio 事件迴圈中呼叫。")
    destination = Path(out_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="tts-", dir=destination.parent) as temp:
            audio = Path(temp) / "speech.mp3"
            duration = asyncio.run(_save(text, audio, voice, rate))
            if duration <= 0 or not audio.stat().st_size:
                raise ValueError("MP3 沒有音訊。")
            audio.replace(destination)
        return duration
    except Exception as exc:
        raise SynthesisError(f"語音合成失敗（{type(exc).__name__}），請確認網路與語音名稱後重試。") from exc
