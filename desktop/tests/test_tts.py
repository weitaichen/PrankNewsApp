from types import SimpleNamespace

import pytest

from prank_news import tts


def test_synthesize_saves_and_measures_mp3(monkeypatch, tmp_path):
    calls = []

    class Communicate:
        def __init__(self, text, voice, *, rate):
            calls.append((text, voice, rate))

        async def save(self, path):
            from pathlib import Path
            Path(path).write_bytes(b"fake-mp3")

    monkeypatch.setattr(tts.edge_tts, "Communicate", Communicate)
    monkeypatch.setattr(tts, "MP3", lambda path: SimpleNamespace(info=SimpleNamespace(length=12.5)))
    destination = tmp_path / "audio" / "episode.mp3"
    assert tts.synthesize("各位聽眾早安。", destination, "voice", "-5%") == 12.5
    assert calls == [("各位聽眾早安。", "voice", "-5%")]
    assert destination.read_bytes() == b"fake-mp3"


def test_long_text_retries_chunks_and_sums_durations(monkeypatch, tmp_path):
    text = "吐司唱歌。" * 600
    chunks = tts._chunks(text)
    calls = []

    class Communicate:
        def __init__(self, content, voice, *, rate):
            self.content = content

        async def save(self, path):
            from pathlib import Path
            calls.append(self.content)
            if self.content == text:
                Path(path).write_bytes(b"partial-failed-audio")
                raise RuntimeError("long text failed")
            Path(path).write_bytes(b"part")

    monkeypatch.setattr(tts.edge_tts, "Communicate", Communicate)
    monkeypatch.setattr(tts, "MP3", lambda path: SimpleNamespace(info=SimpleNamespace(length=2)))
    output = tmp_path / "episode.mp3"
    assert tts.synthesize(text, output, "voice") == 2 * len(chunks)
    assert "".join(calls[1:]) == text
    assert output.read_bytes() == b"part" * len(chunks)
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_failure_preserves_existing_audio(monkeypatch, tmp_path):
    class Communicate:
        def __init__(self, *args, **kwargs):
            pass

        async def save(self, path):
            raise ConnectionError("offline")

    monkeypatch.setattr(tts.edge_tts, "Communicate", Communicate)
    output = tmp_path / "episode.mp3"
    output.write_bytes(b"keep")
    with pytest.raises(tts.SynthesisError, match="確認網路"):
        tts.synthesize("早安。", output, "voice")
    assert output.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [output]
