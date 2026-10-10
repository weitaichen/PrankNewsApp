import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import pytest

from prank_news import deploy as deployment, gui, pipeline
from prank_news.show import create_show, load_show

ALIAS = "https://public.example.test"


class Response(io.BytesIO):
    def __init__(self, body, status, url):
        super().__init__(body)
        self.status, self.url = status, url

    def geturl(self):
        return self.url


@pytest.fixture
def hosting(monkeypatch):
    uploads, requests, sleeps = [], [], []
    state = {"stale_feeds": 0, "alias": ALIAS}

    def runner(command, **kwargs):
        directory = kwargs["cwd"]
        link = directory / ".vercel" / "project.json"
        if "link" in command:
            assert command[-2:] == ["--project", state["project"]]
            link.parent.mkdir(exist_ok=True)
            link.write_text(json.dumps({"projectName": command[-1]}))
        if "deploy" in command:
            assert link.exists(), "rebuilding must relink before the second deploy"
            assert json.loads(link.read_text())["projectName"] == state["project"]
            uploads.append({str(path.relative_to(directory)).replace("\\", "/"): path.read_bytes()
                            for path in directory.rglob("*") if path.is_file()})
            if len(uploads) == 2 and state.get("second_alias"):
                state["alias"] = state["second_alias"]
        return SimpleNamespace(returncode=0, stdout=f"Aliased: {state['alias']}\n", stderr="")

    def checker(request, **kwargs):
        assert not any(key.lower() in {"authorization", "cookie"} for key in request.headers)
        requests.append(request)
        url = request.full_url
        parsed = urlsplit(url)
        # The guessed default domain is deliberately unavailable.
        if f"https://{parsed.netloc}" != state["alias"]:
            raise HTTPError(url, 404, "Unknown domain", {}, None)
        path = parsed.path.lstrip("/")
        body = uploads[-1][path]
        if path == "feed.xml" and state["stale_feeds"]:
            state["stale_feeds"] -= 1
            feed = ET.fromstring(body)
            feed.find("channel/item/guid").text = "old-deployment-guid"
            body = ET.tostring(feed)
        if path == "episode.json":
            metadata = json.loads(body)
            # Range must follow RSS even if JSON points to a different file.
            metadata["audio"] = "episodes/json-only.mp3"
            if state.get("stale_player"):
                metadata["feedUrl"] = "https://old.example.test/feed.xml"
            body = json.dumps(metadata).encode()
        status = 200
        if request.get_header("Range"):
            assert request.get_header("Range") == "bytes=0-1"
            status, body = 206, body[:2]
        return Response(body, status, url)

    monkeypatch.setattr(deployment.shutil, "which", lambda name: "fake-npx")
    monkeypatch.setattr(deployment, "urlopen", checker)
    def deploy(directory, project, **kwargs):
        state["project"] = project
        return deployment.deploy(directory, project, runner=runner, sleeper=sleeps.append, **kwargs)
    monkeypatch.setattr(pipeline, "deploy_app", deploy)
    return SimpleNamespace(uploads=uploads, requests=requests, sleeps=sleeps, state=state)


def assert_alias(show, output, feed_url, hosting):
    persisted = load_show(show.project)
    assert persisted.base_url == ALIAS
    assert json.loads((show.directory / "show.json").read_text(encoding="utf-8"))["baseUrl"] == ALIAS
    channel = ET.parse(output / "feed.xml").find("channel")
    assert channel.findtext("link") == ALIAS
    assert channel.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}image").get("href") == f"{ALIAS}/podcast-cover.png"
    assert channel.findtext("item/guid") == show.episodes[0]["id"]
    assert channel.find("item/enclosure").get("url") == f"{ALIAS}/{show.episodes[0]['file']}"
    assert json.loads((output / "episode.json").read_text(encoding="utf-8"))["feedUrl"] == feed_url == f"{ALIAS}/feed.xml"
    assert len(hosting.uploads) == 2
    assert [request.full_url for request in hosting.requests if request.get_header("Range")] == [channel.find("item/enclosure").get("url")]


def test_generate_deploy_reconciles_alias_and_reuses_saved_url(monkeypatch, tmp_path, template,
                                                             request_data, episode, hosting):
    show = create_show(project="morning-news-alias")
    monkeypatch.setattr(pipeline, "generate_episode", lambda *a, **k: episode)
    result = pipeline.generate_and_deploy(request_data, show, tmp_path / "work", tmp_path / "app",
                                         template_dir=template)
    assert result["url"] == ALIAS and result["qr_path"].is_file()
    assert_alias(show, result["out_dir"], result["feed_url"], hosting)
    # The original Show instance predates baseUrl. The lock reload must read it.
    next_result = pipeline.build_and_deploy(episode, tmp_path / "next", show=show, template_dir=template)
    assert next_result["feed_url"] == f"{ALIAS}/feed.xml"
    assert len(hosting.uploads) == 3  # One deployment on subsequent builds.


def test_gui_separate_deploy_shows_verified_subscription(monkeypatch, tmp_path, template,
                                                       episode, hosting):
    show = create_show(project="morning-news-gui-alias")
    result = pipeline.build_and_deploy(episode, tmp_path / "app", deploy=False, show=show,
                                      template_dir=template)
    window = gui.PrankNewsWindow.__new__(gui.PrankNewsWindow)
    window.selected_show, window.out_dir = show, result["out_dir"]
    window.project = SimpleNamespace(get=lambda: show.project)
    shown = {}
    window.url = SimpleNamespace(set=lambda url: shown.update(url=url))
    window.feed_url = SimpleNamespace(set=lambda url: shown.update(feed_url=url))
    window.status = SimpleNamespace(set=lambda *a: None)
    window.qr_label = SimpleNamespace(configure=lambda **k: None)
    window.root = None
    window._clear_deployment = window._progress = lambda *a: None
    window._start = lambda job, completed, message: completed(job())
    monkeypatch.setattr(pipeline, "default_template_dir", lambda: template)
    monkeypatch.setattr(gui.ImageTk, "PhotoImage", lambda *a, **k: "image")
    window._deploy()
    assert shown["url"] == ALIAS
    assert_alias(show, result["out_dir"], shown["feed_url"], hosting)
    assert len(show.episodes) == 1  # Redeployment does not append another episode.


@pytest.mark.parametrize("stale_feeds, succeeds", [(2, True), (3, False)])
def test_guid_mismatch_retries_then_succeeds_or_errors(tmp_path, template, episode, hosting,
                                                     stale_feeds, succeeds):
    show = create_show(project="morning-news-stale")
    hosting.state["alias"] = show.base_url
    hosting.state["stale_feeds"] = stale_feeds
    if succeeds:
        result = pipeline.build_and_deploy(episode, tmp_path / "app", show=show, template_dir=template)
        assert result["feed_url"] == f"{show.base_url}/feed.xml"
    else:
        with pytest.raises(deployment.DeploymentError, match="最新 GUID") as error:
            pipeline.build_and_deploy(episode, tmp_path / "app", show=show, template_dir=template)
        assert "GUID" in str(error.value.__cause__)
        assert not any(request.get_header("Range") for request in hosting.requests)
        assert load_show(show.project).baseUrl is None
    assert hosting.sleeps == [2, 2]
    assert sum(request.full_url.endswith("feed.xml") for request in hosting.requests) == 3
    assert len(hosting.uploads) == 1
    assert len(show.episodes) == 1


def test_unverified_alias_is_not_persisted(tmp_path, template, episode, hosting):
    show = create_show(project="morning-news-unverified")
    hosting.state["stale_feeds"] = 3
    with pytest.raises(deployment.DeploymentError):
        pipeline.build_and_deploy(episode, tmp_path / "app", show=show, template_dir=template)
    assert load_show(show.project).baseUrl is None
    assert len(hosting.uploads) == 1


def test_alias_reconciliation_redeploys_at_most_once(tmp_path, template, episode, hosting):
    show = create_show(project="morning-news-changing-alias")
    hosting.state["second_alias"] = "https://another.example.test"
    with pytest.raises(deployment.DeploymentError, match="公開網址再次改變"):
        pipeline.build_and_deploy(episode, tmp_path / "app", show=show, template_dir=template)
    assert len(hosting.uploads) == 2
    assert load_show(show.project).base_url == ALIAS
    assert len(show.episodes) == 1


def test_stale_player_subscription_is_not_delivered(tmp_path, template, episode, hosting):
    show = create_show(project="morning-news-stale-player")
    hosting.state["stale_player"] = True
    with pytest.raises(deployment.DeploymentError) as error:
        pipeline.build_and_deploy(episode, tmp_path / "app", show=show, template_dir=template)
    assert "舊訂閱網址" in str(error.value.__cause__)
    assert len(hosting.uploads) == 2 and hosting.sleeps == [2, 2]
    assert len(show.episodes) == 1


def test_gui_refuses_to_overwrite_newer_episode(tmp_path, template, episode, hosting):
    show = create_show(project="morning-news-newer")
    first = pipeline.build_and_deploy(episode, tmp_path / "old", deploy=False, show=show, template_dir=template)
    pipeline.build_and_deploy(episode, tmp_path / "new", deploy=False, show=show, template_dir=template)
    with pytest.raises(deployment.DeploymentError, match="已有新單集"):
        pipeline.deploy_built_show(show, first["out_dir"], template_dir=template)
    assert not hosting.uploads
