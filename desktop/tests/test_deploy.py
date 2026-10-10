import json
import subprocess
import io
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from PIL import Image

from prank_news import deploy as module


@pytest.mark.parametrize("stdout, expected", [
    ("https://news-123.vercel.app\n", "https://morning-news.vercel.app"),
    ("Inspect: https://vercel.com/team/project/123\nProduction: https://news-123.vercel.app [3s]\n", "https://morning-news.vercel.app"),
    ("\x1b[32mAliased: https://news.vercel.app\x1b[0m\n", "https://news.vercel.app"),
    ("Aliased: https://news.example.com [3s]\n", "https://news.example.com"),
])
def test_deploy_url_and_command(monkeypatch, tmp_path, stdout, expected):
    monkeypatch.setattr(module.shutil, "which", lambda name: "C:/node/npx.cmd")
    captured = {}
    commands = []

    def runner(command, **kwargs):
        captured.update(command=command, **kwargs)
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    checked = []
    assert module.deploy(tmp_path, "morning-news", runner, public_check=checked.append) == expected
    assert checked == [expected]
    assert commands == [
        ["C:/node/npx.cmd", "--yes", "vercel", "link", "--yes", "--project", "morning-news"],
        ["C:/node/npx.cmd", "--yes", "vercel", "deploy", "--prod", "--yes"],
    ]
    assert not (tmp_path / "vercel.json").exists()
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
    assert module.deploy(tmp_path, "morning-news", lambda *a, **k: result,
                         public_check=lambda url: None) == "https://morning-news.vercel.app"


def test_qr_is_png(tmp_path):
    path = module.make_qr("https://news.vercel.app", tmp_path / "qr" / "code.png")
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.width == image.height > 0


def test_project_config_preserves_cache_headers(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    headers = [{"source": "/episode.json", "headers": [{"key": "Cache-Control", "value": "no-cache"}]}]
    (tmp_path / "vercel.json").write_text(json.dumps({"headers": headers, "name": "deprecated"}))
    result = SimpleNamespace(returncode=0, stdout="https://news.vercel.app", stderr="")
    module.deploy(tmp_path, "morning-news", lambda *a, **k: result, public_check=lambda url: None)
    assert json.loads((tmp_path / "vercel.json").read_text()) == {"headers": headers}


def test_alias_on_stderr_wins_over_generated_url(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    result = SimpleNamespace(returncode=0, stdout="https://generated-protected.vercel.app",
                             stderr="Aliased: https://public.example.com [3s]")
    checked = []
    assert module.deploy(tmp_path, "morning-news", lambda *a, **k: result,
                         public_check=checked.append) == "https://public.example.com"
    assert checked == ["https://public.example.com"]


@pytest.mark.parametrize("link_content, keep", [
    ('{"projectName":"old-news"}', False), ('{"projectId":"unknown"}', False),
    ('not JSON', False), ('[]', False), (None, False),
    ('{"projectName":"morning-news"}', True),
])
def test_project_link_removed_before_relink(monkeypatch, tmp_path, link_content, keep):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    link = tmp_path / ".vercel"
    link.mkdir()
    if link_content is not None:
        (link / "project.json").write_text(link_content)
    (link / "stale").write_text("old")
    calls = []

    def runner(command, **kwargs):
        if not calls:
            assert link.exists() is keep
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    module.deploy(tmp_path, "morning-news", runner, public_check=lambda url: None)
    assert calls[0][-2:] == ["--project", "morning-news"]
    assert calls[1][3:] == ["deploy", "--prod", "--yes"]


def test_public_check_retries_alias_delay_and_reports_protection(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda name: "npx")
    runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")
    checks, sleeps = [], []

    def eventually(url):
        checks.append(url)
        if len(checks) < 3:
            raise HTTPError(url, 403, "Forbidden", {}, None)

    module.deploy(tmp_path, "morning-news", runner, public_check=eventually, sleeper=sleeps.append)
    assert len(checks) == 3 and sleeps == [2, 2]

    def protected(url):
        raise HTTPError(url, 401, "Unauthorized", {}, None)

    with pytest.raises(module.DeploymentError, match="Settings → Deployment Protection 關閉 Vercel Authentication"):
        module.deploy(tmp_path, "morning-news", runner, public_check=protected, sleeper=lambda delay: None)


@pytest.mark.parametrize("status, destination, body, valid", [
    (200, "https://news.vercel.app/episode.json", b'{"title":"news"}', True),
    (403, "https://news.vercel.app/episode.json", b'{}', False),
    (200, "https://vercel.com/login", b'{}', False),
    (200, "https://news.vercel.app/episode.json", b'<html>login</html>', False),
    (200, "https://news.vercel.app/episode.json", b'[]', False),
])
def test_anonymous_episode_get_validates_json_and_redirect(monkeypatch, status, destination, body, valid):
    class Response(io.BytesIO):
        def geturl(self):
            return destination

    response = Response(body)
    response.status = status

    def opener(request, **kwargs):
        assert request.full_url == "https://news.vercel.app/episode.json"
        assert request.get_method() == "GET"
        assert set(key.lower() for key in request.headers) == {"accept"}
        return response

    monkeypatch.setattr(module, "urlopen", opener)
    if valid:
        module.check_public_episode("https://news.vercel.app")
    else:
        with pytest.raises(ValueError):
            module.check_public_episode("https://news.vercel.app")
