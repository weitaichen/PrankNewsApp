import json
import re

import pytest

from prank_news import cli, pipeline


def test_cli_script_file_full_local_build(monkeypatch, tmp_path, template, capsys):
    def forbidden(*args):
        raise AssertionError("offline CLI must not call Claude or deploy")

    monkeypatch.setattr(pipeline, "generate_script", forbidden)
    monkeypatch.setattr(pipeline, "deploy_app", forbidden)

    def synthesize(text, path, voice):
        assert text == "各位聽眾早安，測試的吐司正在唱歌。"
        path.write_bytes(b"mock-audio")
        return 7.5

    monkeypatch.setattr(pipeline, "synthesize", synthesize)
    script = tmp_path / "script.txt"
    script.write_text("各位聽眾早安，測試的吐司正在唱歌。", encoding="utf-8-sig")
    output = tmp_path / "app"
    assert cli.main([
        "--name", "測試", "--name", "小明", "--script-file", str(script),
        "--out", str(output), "--template", str(template),
    ]) == 0
    metadata = json.loads((output / "episode.json").read_text(encoding="utf-8"))
    assert metadata["durationSec"] == 7.5
    captured = capsys.readouterr()
    assert "[script]" in captured.out and "[tts]" in captured.out and "[build]" in captured.out
    assert "資料夾：" in captured.out
    assert "[deploy]" not in captured.out


def test_cli_invalid_request_returns_failure(capsys):
    assert cli.main(["--name", "測試", "--minutes", "99"]) == 1
    assert "0.5–15" in capsys.readouterr().err


def test_cli_default_project_uses_core_generator(monkeypatch, tmp_path, template):
    names = []
    def tts(text, path, voice):
        path.write_bytes(b"audio")
        return 1
    monkeypatch.setattr(pipeline, "synthesize", tts)
    monkeypatch.setattr(pipeline, "deploy_app", lambda directory, name, **kwargs: names.append(name) or f"https://{name}.vercel.app")
    script = tmp_path / "script.txt"
    script.write_text("早安。", encoding="utf-8")
    assert cli.main(["--name", "王小明", "--script-file", str(script), "--deploy",
                     "--out", str(tmp_path / "app"), "--template", str(template)]) == 0
    assert re.fullmatch(r"morning-news-[a-z0-9]{6}", names[0])


def test_cli_rejects_symlink_output_without_deleting_target(monkeypatch, tmp_path, template, capsys):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep")
    output = tmp_path / "linked-output"
    try:
        output.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"此 Windows 環境無建立 symlink 權限：{exc}")
    def tts(text, path, voice):
        path.write_bytes(b"audio")
        return 1
    monkeypatch.setattr(pipeline, "synthesize", tts)
    script = tmp_path / "script.txt"
    script.write_text("早安。", encoding="utf-8")
    assert cli.main(["--name", "王小明", "--script-file", str(script), "--out", str(output),
                     "--template", str(template)]) == 1
    assert "連結" in capsys.readouterr().err
    assert output.is_symlink() and marker.read_text() == "keep"


def test_cli_new_existing_and_recent_show_keep_project(monkeypatch, tmp_path, template, capsys):
    from prank_news.show import list_shows, load_show
    def tts(text, path, voice):
        path.write_bytes(b"audio")
        return 5
    monkeypatch.setattr(pipeline, "synthesize", tts)
    monkeypatch.setattr(pipeline, "generate_script", lambda *args: pytest.fail("script-file must skip Claude"))
    projects = []
    monkeypatch.setattr(pipeline, "deploy_app", lambda directory, project, **kwargs: projects.append(project) or f"https://{project}.vercel.app")
    script = tmp_path / "script.txt"
    script.write_text("節目：小明專屬\n主播：王小明\n\n王小明早安。", encoding="utf-8")
    common = ["--name", "王小明", "--script-file", str(script), "--template", str(template), "--deploy"]
    assert cli.main(common + ["--new-show", "固定晨報", "--anchor", "主播", "--project", "morning-news-fixed",
                              "--out", str(tmp_path / "one")]) == 0
    assert cli.main(common + ["--show", "morning-news-fixed", "--out", str(tmp_path / "two")]) == 0
    assert cli.main(common + ["--out", str(tmp_path / "three")]) == 0
    show = load_show("morning-news-fixed")
    assert projects == [show.project] * 3
    assert len(show.episodes) == 3 and len(list_shows()) == 1
    metadata = json.loads((tmp_path / "three" / "episode.json").read_text(encoding="utf-8"))
    assert metadata["show"] == "固定晨報" and metadata["anchor"] == "主播"
    assert "小明" not in json.dumps(metadata, ensure_ascii=False)
    assert "訂閱網址：https://morning-news-fixed.vercel.app/feed.xml" in capsys.readouterr().out


def test_cli_rejects_new_show_with_given_name_before_synthesis(monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "synthesize", lambda *args: pytest.fail("invalid show must not synthesize"))
    assert cli.main(["--name", "王小明", "--new-show", "小明晨報"]) == 1
    assert "乘客名字" in capsys.readouterr().err
