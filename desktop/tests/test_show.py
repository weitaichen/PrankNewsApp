from datetime import datetime, timedelta, timezone
import json

import pytest

from prank_news import show as library

WHEN = datetime(2026, 10, 10, 8, tzinfo=timezone(timedelta(hours=8)))


def test_show_defaults_round_trip_recent_selection_and_injected_root(tmp_path):
    root = tmp_path / "library"
    assert library.list_shows(root_dir=root) == []
    first = library.create_show(project="morning-news-one", root_dir=root)
    assert first.directory == root / "morning-news-one"
    assert first.title == "晨間新聞快報" and first.anchor == "主播 林雅婷"
    assert first.description == "每日晨間新聞，快速掌握今日大小事。"
    assert datetime.fromisoformat(first.created).utcoffset() is not None
    assert library.load_show(first.project, root_dir=root) == first
    assert first.episodes == []
    second = library.create_show("另一個節目", project="morning-news-two", root_dir=root)
    assert library.list_shows(root_dir=root) == [second, first]
    library.mark_used(first)
    assert library.list_shows(root_dir=root) == [first, second]
    assert set(json.loads((first.directory / "show.json").read_text(encoding="utf-8"))) == {
        "project", "title", "anchor", "description", "created"}
    with pytest.raises(FileExistsError):
        library.create_show(project=first.project, root_dir=root)


@pytest.mark.parametrize("kwargs", [
    {"title": "王小明新聞"}, {"title": "小明快報"}, {"anchor": "主播 小明"},
    {"description": "王小明專屬"}, {"project": "mary-news", "passenger_names": ["mary"]},
    {"title": "美麗新聞", "passenger_names": ["歐陽美麗"]},
])
def test_create_rejects_passenger_names_and_given_fragments(tmp_path, kwargs):
    kwargs.setdefault("passenger_names", ["王小明"])
    with pytest.raises(ValueError, match="乘客名字"):
        library.create_show(root_dir=tmp_path / "shows", **kwargs)
    assert not (tmp_path / "shows").exists()


def test_neutral_same_day_titles_and_retention_delete_files(tmp_path):
    show = library.create_show(root_dir=tmp_path / "shows")
    audio = tmp_path / "王小明.mp3"
    audio.write_bytes(b"fake-audio")
    items = [library.add_episode(show, audio, 12.5, when=WHEN + timedelta(minutes=i),
                                 passenger_names=["王小明"]) for i in range(22)]
    assert items[0]["title"] == "10月10日 晨間新聞"
    assert items[1]["title"] == "10月10日 晨間新聞（二）"
    assert items[20]["title"] == "10月10日 晨間新聞（二十一）"
    assert items[21]["title"] == "10月10日 晨間新聞（二十二）"
    assert show.episodes == list(reversed(items[2:]))
    assert len(list((show.directory / "episodes").glob("*.mp3"))) == 20
    for item in items[:2]:
        assert not (show.directory / item["file"]).exists()
    for item in items[2:]:
        assert (show.directory / item["file"]).read_bytes() == b"fake-audio"
        assert item["bytes"] == 10
        assert datetime.fromisoformat(item["published"]).utcoffset() == timedelta(hours=8)
    next_day = library.add_episode(show, audio, 1, when=WHEN + timedelta(days=1))
    assert next_day["title"] == "10月11日 晨間新聞"


def test_untimed_and_invalid_duration_do_not_add_episode(tmp_path):
    show = library.create_show(root_dir=tmp_path / "shows")
    for value in (0, -1, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            library.add_episode(show, tmp_path / "missing.mp3", value)
    with pytest.raises(ValueError, match="時區"):
        library.add_episode(show, tmp_path / "missing.mp3", 1, when=WHEN.replace(tzinfo=None))
    assert show.episodes == []


def test_existing_show_name_overlap_is_rejected_without_storing_names(tmp_path):
    show = library.create_show(title="小明晨報", root_dir=tmp_path / "shows")
    with pytest.raises(ValueError, match="乘客名字"):
        library.add_episode(show, tmp_path / "missing.mp3", 1, passenger_names=["王小明"])
    assert show.episodes == []
