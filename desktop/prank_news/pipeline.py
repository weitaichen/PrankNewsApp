"""Blocking orchestration intended for a desktop GUI worker thread."""

from collections.abc import Callable
from datetime import date
from pathlib import Path
import xml.etree.ElementTree as ET

from .builder import build_show_site, default_template_dir, validate_show_build
from .deploy import DeploymentError, deploy as deploy_app, make_qr
from .models import Episode, NewsRequest
from .project import default_project_name
from .script_gen import DEFAULT_SHOW, DEFAULT_ANCHOR, generate_script, parse_response
from .tts import synthesize
from .show import (Show, candidate_episode, show_lock, save_base_url,
                   create_show, list_shows, load_show, contains_passenger,
                   validate_show_privacy, safe_metadata, DEFAULT_DESCRIPTION)

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
        _, _, script = generate_script(request)
    else:
        _, _, script = parse_response(script_text)
    if not script.strip():
        raise ValueError("播報稿不可空白。")
    progress("tts", "正在合成語音…")
    audio = directory / "episode.mp3"
    duration = synthesize(script, audio, request.voice)
    today = date.today()
    episode = Episode(
        show=request.show_title,
        title=f"{today.year}年{today.month}月{today.day}日 晨間新聞",
        anchor=request.anchor_name,
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
    show: Show | None = None,
    shows_root: str | Path | None = None,
) -> dict:
    """Append one episode and rebuild the fixed show's RSS and fallback player."""
    progress("build", "正在建立節目訂閱與播放器…")
    sanitize_metadata(episode)
    if show is None:
        if project_name:
            try:
                show = load_show(project_name, root_dir=shows_root)
            except FileNotFoundError:
                show = create_show(episode.show, episode.anchor, project_name,
                                   root_dir=shows_root, passenger_names=episode.passenger_names)
        else:
            show = recent_or_default_show(episode.passenger_names, root_dir=shows_root)
    template = template_dir if template_dir is not None else default_template_dir()
    with show_lock(show):
        show = load_show(show.project, root_dir=show.directory.parent)
        validate_show_privacy(show, episode.passenger_names)
        base_url = show.base_url
        validate_show_build(show.directory, template, out_dir, base_url)
        with candidate_episode(show, episode.audio_path, episode.duration_sec,
                               passenger_names=episode.passenger_names) as (item, retained):
            output = build_show_site(show.directory, template, out_dir, base_url, episodes=retained)
        # The library is committed once the build succeeds. Deployment failures
        # keep the new episode and built output so the user can redeploy it.
        episode.show, episode.anchor, episode.title = show.title, show.anchor, item["title"]
        episode.audio_path = output / item["file"]
        url = None
        qr = None
        if deploy:
            progress("deploy", "正在部署至 Vercel…")
            url = _deploy_show_locked(show, output, template, retained, episode.passenger_names)
            base_url = url
            qr = make_qr(url, output / "qr.png")
    progress("done", "新聞 App 已完成。")
    return {"out_dir": output, "url": url, "feed_url": f"{base_url}/feed.xml", "qr_path": qr}


def _deploy_show_locked(show: Show, output: Path, template, episodes: list[dict],
                        passenger_names: list[str]) -> str:
    def rebuild(base_url):
        validate_show_build(show.directory, template, output, base_url)
        if contains_passenger(base_url, passenger_names):
            raise ValueError("公開網址含乘客名字，請調整 production alias。")
        save_base_url(show, base_url)
        build_show_site(show.directory, template, output, base_url, episodes=episodes)

    url = deploy_app(output, show.project, rebuild_for_url=rebuild)
    save_base_url(show, url)
    return url


def deploy_built_show(show: Show, out_dir: str | Path, *, template_dir=None) -> str:
    """GUI redeployment shares URL reconciliation without adding another episode."""
    output = Path(out_dir).resolve()
    with show_lock(show):
        show = load_show(show.project, root_dir=show.directory.parent)
        episodes = show.episodes
        guid = ET.parse(output / "feed.xml").findtext("channel/item/guid")
        if not episodes or guid != episodes[0]["id"]:
            raise DeploymentError("節目已有新單集，請重新建置後部署。")
        return _deploy_show_locked(show, output, template_dir or default_template_dir(), episodes, [])


def recent_or_default_show(passenger_names: list[str], *, root_dir=None) -> Show:
    shows = list_shows(root_dir=root_dir)
    if shows:
        validate_show_privacy(shows[0], passenger_names)
        return shows[0]
    return create_show(
        safe_metadata(DEFAULT_SHOW, DEFAULT_SHOW, passenger_names, "新聞快報"),
        safe_metadata(DEFAULT_ANCHOR, DEFAULT_ANCHOR, passenger_names, "主播"),
        description=safe_metadata(DEFAULT_DESCRIPTION, DEFAULT_DESCRIPTION, passenger_names, "每日新聞"),
        root_dir=root_dir, passenger_names=passenger_names,
    )


def generate_and_deploy(request: NewsRequest, show: Show, work_dir: str | Path,
                        out_dir: str | Path, *, deploy: bool = True,
                        progress: Progress = _no_progress, script_text: str | None = None,
                        template_dir: str | Path | None = None) -> dict:
    validate_show_privacy(show, request.passenger_names)
    request.show_title, request.anchor_name = show.title, show.anchor
    episode = generate_episode(request, work_dir, progress, script_text=script_text)
    return build_and_deploy(episode, out_dir, deploy, progress, show=show, template_dir=template_dir)
