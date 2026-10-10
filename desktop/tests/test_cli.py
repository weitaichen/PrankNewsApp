import json

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
