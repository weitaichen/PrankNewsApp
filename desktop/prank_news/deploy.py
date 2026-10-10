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


def check_public_episode(url: str) -> None:
    """GET without cookies, CLI tokens, or protection bypass credentials."""
    request = Request(url.rstrip("/") + "/episode.json", headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        host = (urlsplit(response.geturl()).hostname or "").lower()
        if response.status != 200 or host == "vercel.com" or host.endswith(".vercel.com"):
            raise ValueError("公開網址導向登入頁或未回傳 HTTP 200。")
        if not isinstance(json.load(response), dict):
            raise ValueError("episode.json 必須是 JSON 物件。")


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
    for command in commands:
        completed = _run_vercel(command, directory, runner or subprocess.run)
    url = _deployment_url(f"{completed.stdout}\n{completed.stderr}", project_name)
    for attempt in range(attempts):
        try:
            (public_check or check_public_episode)(url)
            return url
        except (OSError, ValueError) as exc:
            if attempt == attempts - 1:
                raise DeploymentError(
                    "無法匿名讀取 episode.json；網址受 Vercel 部署保護，請到專案 "
                    "Settings → Deployment Protection 關閉 Vercel Authentication。"
                    "若已關閉，請確認網路與 alias 已生效後重試。"
                ) from exc
            sleeper(retry_delay)


def make_qr(url: str, png_path: str | Path) -> Path:
    path = Path(png_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url).save(path, format="PNG")
    return path
