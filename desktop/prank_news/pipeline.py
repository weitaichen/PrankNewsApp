"""Blocking orchestration intended for a desktop GUI worker thread."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

from .builder import build_app, default_template_dir
from .deploy import deploy as deploy_app, make_qr
from .models import Episode, NewsRequest
from .project import default_project_name
from .script_gen import DEFAULT_SHOW, DEFAULT_ANCHOR, generate_script, parse_response
from .tts import synthesize

Progress = Callable[[str, str], None]


def _no_progress(stage: str, message: str) -> None:
    pass


def sanitize_metadata(episode: Episode) -> None:
    """Keep passenger names and two-character given-name fragments private."""
    fragments = set()
    for name in episode.passenger_names:
        name = name.strip()
        if not name:
            continue
        fragments.add(name)
        # Every fragment of length >= 2 contains one of these adjacent pairs.
        # Starting after the first character also covers compound family names.
        fragments.update(name[start:start + 2] for start in range(1, len(name) - 1))
    for field, fallback in (("show", DEFAULT_SHOW), ("anchor", DEFAULT_ANCHOR),
                            ("title", DEFAULT_SHOW)):
        if any(fragment.casefold() in getattr(episode, field).casefold() for fragment in fragments):
            # A passenger may coincidentally have the default anchor's name.
            if any(fragment.casefold() in fallback.casefold() for fragment in fragments):
                fallback = "主播" if field == "anchor" else "新聞快報"
            setattr(episode, field, fallback)


def synthesize_episode(
    show: str,
    anchor: str,
    script: str,
    voice: str,
    work_dir: str | Path,
    progress: Progress = _no_progress,
    *,
    passenger_names: list[str] | None = None,
) -> Episode:
    """Synthesize an edited script verbatim, without Claude or metadata parsing."""
    if not script.strip():
        raise ValueError("播報稿不可空白。")
    if not show.strip() or not anchor.strip():
        raise ValueError("節目名與主播名不可空白。")
    if not voice.strip():
        raise ValueError("主播聲音不可空白。")
    directory = Path(work_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    progress("tts", "正在合成語音…")
    audio = directory / "episode.mp3"
    duration = synthesize(script, audio, voice)
    today = date.today()
    episode = Episode(
        show=show.strip(),
        title=f"{today.year}年{today.month}月{today.day}日 晨間新聞",
        anchor=anchor.strip(),
        published=today.isoformat(),
        duration_sec=duration,
        script=script,
        audio_path=audio,
        passenger_names=list(passenger_names or []),
    )
    progress("done", "語音已完成。")
    return episode


def generate_episode(
    request: NewsRequest,
    work_dir: str | Path,
    progress: Progress = _no_progress,
    *,
    script_text: str | None = None,
) -> Episode:
    """Generate script/audio; script_text supports offline-script CLI workflows."""
    directory = Path(work_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    progress("script", "正在產生新聞播報稿…" if script_text is None else "正在讀取指定播報稿…")
    if script_text is None:
        show, anchor, script = generate_script(request)
    else:
        show, anchor, script = parse_response(script_text)
    if not script.strip():
        raise ValueError("播報稿不可空白。")
    progress("tts", "正在合成語音…")
    audio = directory / "episode.mp3"
    duration = synthesize(script, audio, request.voice)
    today = date.today()
    episode = Episode(
        show=show,
        title=f"{today.year}年{today.month}月{today.day}日 晨間新聞",
        anchor=anchor,
        published=today.isoformat(),
        duration_sec=duration,
        script=script,
        audio_path=audio,
        passenger_names=list(request.passenger_names),
    )
    progress("done", "播報稿與語音已完成。")
    return episode


def build_and_deploy(
    episode: Episode,
    out_dir: str | Path,
    deploy: bool = True,
    progress: Progress = _no_progress,
    *,
    template_dir: str | Path | None = None,
    project_name: str | None = None,
    cover_path: str | Path | None = None,
) -> dict:
    """Return out_dir (Path), url (str | None), qr_path (Path | None)."""
    progress("build", "正在建立新聞 App…")
    sanitize_metadata(episode)
    output = build_app(
        template_dir if template_dir is not None else default_template_dir(),
        out_dir, episode, cover_path,
    )
    # The builder may have replaced the original directory containing the audio.
    episode.audio_path = output / "episode.mp3"
    url = None
    qr = None
    if deploy:
        progress("deploy", "正在部署至 Vercel…")
        name = project_name or default_project_name()
        url = deploy_app(output, name)
        qr = make_qr(url, output / "qr.png")
    progress("done", "新聞 App 已完成。")
    return {"out_dir": output, "url": url, "qr_path": qr}
