import json
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from prank_news import deploy as module


@pytest.mark.parametrize("stdout, expected", [
    ("https://news-123.vercel.app\n", "https://news-123.vercel.app"),
    ("Inspect: https://vercel.com/team/project/123\nProduction: https://news-123.vercel.app [3s]\n", "https://news-123.vercel.app"),
    ("\x1b[32mhttps://news-123.vercel.app\x1b[0m\n", "https://news-123.vercel.app"),
    ("Production: https://news.example.com [3s]\n", "https://news.example.com"),
])
def test_deploy_url_and_command(monkeypatch, tmp_path, stdout, expected):
    monkeypatch.setattr(module.shutil, "which", lambda name: "C:/node/npx.cmd")
    captured = {}

    def runner(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    assert module.deploy(tmp_path, "prank-news", runner) == expected
    assert captured["command"] == [
        "C:/node/npx.cmd", "--yes", "vercel", "deploy", "--prod", "--yes",
    ]
    assert json.loads((tmp_path / "vercel.json").read_text())["name"] == "prank-news"
    assert captured["cwd"] == tmp_path
    assert captured["stdin"] == subprocess.DEVNULL


def test_missing_npx(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(module.DeploymentError, match="npx vercel login"):
        module.deploy(tmp_path, "prank-news")


def test_not_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    result = SimpleNamespace(returncode=1, stdout="", stderr="No existing credentials found. Please run vercel login")
    with pytest.raises(module.DeploymentError, match="npx vercel login"):
        module.deploy(tmp_path, "prank-news", lambda *a, **k: result)


def test_dashboard_url_is_not_deployment(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    result = SimpleNamespace(returncode=0, stdout="Inspect: https://vercel.com/team/project/123", stderr="")
    with pytest.raises(module.DeploymentError, match="未回傳部署網址"):
        module.deploy(tmp_path, "prank-news", lambda *a, **k: result)


def test_qr_is_png(tmp_path):
    path = module.make_qr("https://news.vercel.app", tmp_path / "qr" / "code.png")
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.width == image.height > 0


def test_project_config_preserves_cache_headers(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    headers = [{"source": "/episode.json", "headers": [{"key": "Cache-Control", "value": "no-cache"}]}]
    (tmp_path / "vercel.json").write_text(json.dumps({"headers": headers}))
    result = SimpleNamespace(returncode=0, stdout="https://news.vercel.app", stderr="")
    module.deploy(tmp_path, "prank-news", lambda *a, **k: result)
    assert json.loads((tmp_path / "vercel.json").read_text()) == {"name": "prank-news", "headers": headers}
