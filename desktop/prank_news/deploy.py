"""Vercel deployment with a verified anonymous production URL for QR codes."""

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import qrcode

from .project import validate_project_name


class DeploymentError(RuntimeError):
    """Vercel CLI failed or the deployed app is not publicly accessible."""


def _deployment_url(output: str, project_name: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    # Generated deployment URLs can require authentication, even with --prod.
    for line in reversed(cleaned.splitlines()):
        if re.search(r"\bAliased\s*:", line, re.I):
            match = re.search(r"https://[^\s<>]+", line)
            if match:
                return match.group().rstrip(".,;)]}")
    return f"https://{project_name}.vercel.app"


def check_public_episode(url: str, *, checker: Callable | None = None,
                         expected_guid: str | None = None, feed_only: bool = False) -> None:
    """Check the actual RSS enclosure and this build's GUID without credentials.

    feed_only is a preliminary alias check before rebuilding URLs. The final
    check must include JSON and Range before delivering any subscription URL.
    """
    check = checker or urlopen
    def verify_response(response, status):
        host = (urlsplit(response.geturl()).hostname or "").lower()
        if response.status != status or host == "vercel.com" or host.endswith(".vercel.com"):
            raise ValueError(f"公開網址導向登入頁或未回傳 HTTP {status}。")
    request = Request(url.rstrip("/") + "/feed.xml", headers={"Accept": "application/rss+xml"})
    with check(request, timeout=20) as response:
        verify_response(response, 200)
        body = response.read()
        try:
            feed = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ValueError("feed.xml 不是有效 XML。") from exc
        if b"<rss" not in body or feed.tag != "rss":
            raise ValueError("feed.xml 必須是 RSS。")
        latest = feed.find("channel/item")
        guid = latest.findtext("guid") if latest is not None else None
        if not guid or (expected_guid is not None and guid != expected_guid):
            raise ValueError("RSS 最新 GUID 與本次本機單集不符，可能仍是舊部署或快取。")
        enclosure = latest.find("enclosure")
        audio_url = enclosure.get("url", "") if enclosure is not None else ""
        parsed = urlsplit(audio_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("RSS 最新 enclosure 必須是完整的 https 音檔網址。")
    if feed_only:
        return
    request = Request(url.rstrip("/") + "/episode.json", headers={"Accept": "application/json"})
    with check(request, timeout=20) as response:
        verify_response(response, 200)
        metadata = json.load(response)
        if not isinstance(metadata, dict):
            raise ValueError("episode.json 必須是 JSON 物件。")
        if expected_guid is not None and (
            metadata.get("buildId") != expected_guid
            or metadata.get("feedUrl") != url.rstrip("/") + "/feed.xml"
        ):
            raise ValueError("播放器仍指向舊單集或舊訂閱網址，請等待部署更新後重試。")
    audio = metadata.get("audio")
    if not isinstance(audio, str) or not audio.strip():
        raise ValueError("episode.json 缺少最新音檔。")
    if parsed.scheme != "https" or parsed.netloc != urlsplit(url).netloc:
        raise ValueError("RSS enclosure 必須是同源 https 網址。")
    request = Request(audio_url, headers={"Range": "bytes=0-1", "Accept": "audio/mpeg"})
    with check(request, timeout=20) as response:
        verify_response(response, 206)
        if len(response.read(2)) != 2:
            raise ValueError("RSS enclosure 的 Range 回應缺少音檔資料。")


def _remove_mismatched_link(directory: Path, project_name: str) -> None:
    link = directory / ".vercel"
    if not link.exists() and not link.is_symlink():
        return
    try:
        info = json.loads((link / "project.json").read_text(encoding="utf-8"))
        name = info.get("projectName", info.get("name"))
    except (OSError, ValueError, AttributeError):
        name = None
    if name == project_name:
        return
    # Check the recursive deletion target and never follow symlinks/junctions.
    if link.is_symlink():
        link.unlink()
    elif link.is_junction():
        link.rmdir()
    elif link.is_dir() and link.resolve().parent == directory:
        shutil.rmtree(link)
    else:
        link.unlink()


def _run_vercel(command: list[str], directory: Path, runner: Callable):
    try:
        completed = runner(
            command, cwd=directory, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise DeploymentError("找不到 npx。請安裝 Node.js，再執行 npx vercel login。") from exc
    except subprocess.TimeoutExpired as exc:
        raise DeploymentError("Vercel 部署逾時（600 秒）。請檢查部署狀態後重試。") from exc
    except OSError as exc:
        raise DeploymentError("無法執行 Vercel CLI，請確認 Node.js 並執行 npx vercel login。") from exc
    if completed.returncode:
        diagnostic = f"{completed.stdout}\n{completed.stderr}".lower()
        if any(term in diagnostic for term in (
            "login", "log in", "not authenticated", "no existing credentials",
            "invalid token", "token is not valid", "unauthorized", "authentication",
        )):
            raise DeploymentError("Vercel 尚未登入或登入已失效。請先執行 npx vercel login。")
        raise DeploymentError("Vercel 部署失敗，請檢查專案設定；尚未登入請執行 npx vercel login。")
    return completed


def deploy(
    out_dir: str | Path, project_name: str, runner: Callable | None = None,
    *, public_check: Callable | None = None, attempts: int = 3,
    retry_delay: float = 2, sleeper: Callable = time.sleep,
    rebuild_for_url: Callable[[str], None] | None = None,
) -> str:
    directory = Path(out_dir).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"找不到部署資料夾：{directory}")
    validate_project_name(project_name)
    if attempts < 1:
        raise ValueError("公開網址檢查次數必須至少一次。")
    executable = shutil.which("npx")
    if not executable:
        raise DeploymentError("找不到 npx。請先安裝 Node.js，再執行 npx vercel login 登入。")
    config_path = directory / "vercel.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DeploymentError("vercel.json 不是有效 JSON，請重新建置 App。") from exc
    if not isinstance(config, dict):
        raise DeploymentError("vercel.json 必須是 JSON 物件，請重新建置 App。")
    if "name" in config:
        del config["name"]
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    _remove_mismatched_link(directory, project_name)
    # Link's --yes --project can create a new project (setupAndLink/createProject).
    # Deploy's --project alone requires an existing project. Deprecated config.name
    # is not used. Local npx help was blocked by sandbox npm access; verified with
    # https://vercel.com/docs/cli/link and the official commands/link/index.ts.
    commands = [
        [executable, "--yes", "vercel", "link", "--yes", "--project", project_name],
        [executable, "--yes", "vercel", "deploy", "--prod", "--yes"],
    ]
    local_feed = directory / "feed.xml"
    expected_guid = None
    built_url = None
    if local_feed.exists():
        feed = ET.parse(local_feed)
        expected_guid = feed.findtext("channel/item/guid")
        built_url = (feed.findtext("channel/link") or "").rstrip("/")
        if not expected_guid:
            raise DeploymentError("本機 RSS 缺少最新單集 GUID，請重新建置。")

    def verify(url, *, feed_only=False):
        for attempt in range(attempts):
            try:
                if public_check is not None:
                    public_check(url)
                else:
                    check_public_episode(url, expected_guid=expected_guid, feed_only=feed_only)
                return
            except (OSError, ValueError) as exc:
                if attempt == attempts - 1:
                    raise DeploymentError(
                        "無法匿名讀取本次最新 GUID 的 feed.xml、episode.json 或 RSS enclosure 音檔 Range；"
                        "可能是舊部署、快取或 Vercel 部署保護，請至專案 "
                        "Settings → Deployment Protection 關閉 Vercel Authentication。"
                        "若已關閉，請確認網路與 alias 已生效後重試。"
                    ) from exc
                sleeper(retry_delay)

    _run_vercel(commands[0], directory, runner or subprocess.run)
    if expected_guid is None and public_check is None:
        raise DeploymentError("找不到本機 feed.xml，請先建置節目。")
    for deployment in range(2):
        completed = _run_vercel(commands[1], directory, runner or subprocess.run)
        url = _deployment_url(f"{completed.stdout}\n{completed.stderr}", project_name).rstrip("/")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise DeploymentError("部署回傳的 production alias 不是有效的 https 網站網址。")
        if rebuild_for_url is not None and url != built_url:
            if deployment:
                raise DeploymentError("重新部署後公開網址再次改變，請確認 production alias 後重試。")
            # Check the new alias's feed/GUID before persisting it. Old enclosure
            # URLs may be unreachable until the corrected build is deployed.
            verify(url, feed_only=True)
            rebuild_for_url(url)
            built_url = url
            # Rebuilding replaces the output, including .vercel/project.json.
            # Explicitly relink so the second deploy cannot infer another project.
            _run_vercel(commands[0], directory, runner or subprocess.run)
            continue
        verify(url)
        return url


def make_qr(url: str, png_path: str | Path) -> Path:
    path = Path(png_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url).save(path, format="PNG")
    return path
