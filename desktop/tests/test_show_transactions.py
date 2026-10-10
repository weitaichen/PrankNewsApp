from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from prank_news import builder, pipeline, show as library
from prank_news.deploy import DeploymentError


def full_show(episode):
    show = library.create_show(project="morning-news-full")
    when = datetime(2026, 10, 10, tzinfo=timezone.utc)
    for i in range(20):
        library.add_episode(show, episode.audio_path, 10, when=when + timedelta(minutes=i))
    return show


def snapshot(show):
    return {path.name: path.read_bytes() for path in
            [show.directory / "episodes.json", *(show.directory / "episodes").glob("*.mp3")]}


@pytest.mark.parametrize("failure", ["output", "template", "copy", "index"])
def test_failed_build_preserves_twenty_episodes(monkeypatch, tmp_path, template, episode, failure):
    show = full_show(episode)
    original = snapshot(show)
    output = tmp_path / "app"
    if failure == "output":
        output = show.directory
        monkeypatch.setattr(library.shutil, "copy2", lambda *a: pytest.fail("preflight must reject before copy"))
    elif failure == "template":
        (template / "sw.js").unlink()
        monkeypatch.setattr(library.shutil, "copy2", lambda *a: pytest.fail("validate template before copy"))
    elif failure == "copy":
        copy = builder.shutil.copy2
        def fail_mid_build(source, destination, *args, **kwargs):
            if Path(destination).name == "podcast-cover.png":
                raise OSError("素材複製失敗")
            return copy(source, destination, *args, **kwargs)
        monkeypatch.setattr(builder.shutil, "copy2", fail_mid_build)
    else:
        monkeypatch.setattr(library, "_write_json", lambda *a: (_ for _ in ()).throw(OSError("索引寫入失敗")))
    with pytest.raises((ValueError, OSError)):
        pipeline.build_and_deploy(episode, output, deploy=False, show=show, template_dir=template)
    assert snapshot(show) == original
    assert len(show.episodes) == 20
    assert not list(show.directory.glob("*.tmp"))


def test_deployment_failure_keeps_committed_new_episode(monkeypatch, tmp_path, template, episode):
    show = full_show(episode)
    old = show.episodes
    def fail(*args, **kwargs):
        raise DeploymentError("假部署失敗")
    monkeypatch.setattr(pipeline, "deploy_app", fail)
    with pytest.raises(DeploymentError):
        pipeline.build_and_deploy(episode, tmp_path / "app", show=show, template_dir=template)
    current = show.episodes
    assert len(current) == 20 and current[1:] == old[:19]
    assert (show.directory / current[0]["file"]).is_file()
    assert not (show.directory / old[-1]["file"]).exists()
    assert episode.audio_path.is_file()


def test_lock_remains_held_during_build(monkeypatch, tmp_path, template, episode):
    show = library.create_show(project="morning-news-build-lock")
    build = pipeline.build_show_site
    checked = []
    monkeypatch.setattr(library, "LOCK_TIMEOUT", 0.05)
    def competing_build(*args, **kwargs):
        # The candidate exists, but its index has not been committed yet.
        assert show.episodes == []
        with pytest.raises(TimeoutError, match="另一個視窗正在製作這個節目"):
            library.add_episode(show, episode.audio_path, 1)
        checked.append(True)
        return build(*args, **kwargs)
    monkeypatch.setattr(pipeline, "build_show_site", competing_build)
    pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False, show=show, template_dir=template)
    assert checked == [True] and len(show.episodes) == 1


def test_interleaved_builds_reload_index_under_lock(monkeypatch, tmp_path, template, episode):
    show = library.create_show(project="morning-news-concurrent")
    stale_show = library.load_show(show.project)
    copying, release, second_started = threading.Event(), threading.Event(), threading.Event()
    copy = library.shutil.copy2
    calls = []
    def pause_first_copy(source, destination, *args, **kwargs):
        if Path(destination).parent == show.directory / "episodes":
            calls.append(destination)
            if len(calls) == 1:
                copying.set()
                assert release.wait(10)
        return copy(source, destination, *args, **kwargs)
    monkeypatch.setattr(library.shutil, "copy2", pause_first_copy)
    # Separate Episode objects, just as two windows would have.
    from dataclasses import replace
    second_episode = replace(episode)
    def second():
        second_started.set()
        return pipeline.build_and_deploy(second_episode, tmp_path / "second", deploy=False,
                                         show=stale_show, template_dir=template)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(pipeline.build_and_deploy, episode, tmp_path / "first", False,
                            show=show, template_dir=template)
        try:
            assert copying.wait(10)
            other = pool.submit(second)
            assert second_started.wait(10)
            assert not other.done()
        finally:
            release.set()
        first.result(timeout=20)
        other.result(timeout=20)
    items = show.episodes
    assert len(items) == 2 and len({item["id"] for item in items}) == 2
    assert items[0]["title"].endswith("（二）")
    assert len(list((show.directory / "episodes").glob("*.mp3"))) == 2
    import xml.etree.ElementTree as ET
    assert [item.findtext("guid") for item in ET.parse(tmp_path / "second/feed.xml").findall("channel/item")] == [item["id"] for item in items]


def test_cross_process_lock_timeout_and_crash_release(monkeypatch, tmp_path, episode):
    show = library.create_show(project="morning-news-lock")
    original = snapshot(show)
    code = """
import sys
from prank_news.show import load_show, show_lock
show = load_show(sys.argv[1], root_dir=sys.argv[2])
with show_lock(show):
    print('locked', flush=True)
    sys.stdin.read()
"""
    process = subprocess.Popen([sys.executable, "-c", code, show.project, str(show.directory.parent)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        assert pool.submit(process.stdout.readline).result(timeout=10).strip() == "locked"
        monkeypatch.setattr(library, "LOCK_TIMEOUT", 0.05)
        with pytest.raises(TimeoutError, match="另一個視窗正在製作這個節目"):
            library.add_episode(show, episode.audio_path, 1)
        assert snapshot(show) == original
    finally:
        process.kill()
        process.communicate(timeout=10)
        pool.shutdown(wait=True)
    # OS releases a dead process's lock; the persistent .lock file is harmless.
    item = library.add_episode(show, episode.audio_path, 1)
    assert show.episodes == [item]


def test_atomic_json_uses_unique_temporary_names(monkeypatch, tmp_path):
    names = []
    replace = Path.replace
    def capture(path, target):
        names.append(path.name)
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", capture)
    for i in range(2):
        library._write_json(tmp_path / "episodes.json", [i])
    assert len(set(names)) == 2
    assert json.loads((tmp_path / "episodes.json").read_text()) == [1]
    assert not list(tmp_path.glob("*.tmp"))
