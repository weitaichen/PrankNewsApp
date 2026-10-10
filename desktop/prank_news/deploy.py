"""Optional Vercel deployment and QR generation; credentials stay in the CLI."""

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import qrcode


class DeploymentError(RuntimeError):
    """Vercel CLI is unavailable, unauthenticated, or deployment failed."""


def _deployment_url(stdout: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout)
    # Prefer a standalone URL: Vercel's stdout contract is the deployed URL.
    for line in reversed(cleaned.splitlines()):
        candidate = line.strip()
        if re.fullmatch(r"https://[^\s<>]+", candidate):
            return candidate.rstrip(".,;)")
    matches = re.findall(r"https://[^\s<>\x1b]+", cleaned)
    for candidate in reversed(matches):
        candidate = candidate.rstrip(".,;)]}")
        hostname = urlsplit(candidate).hostname or ""
        if hostname.endswith(".vercel.app"):
            return candidate
    # Custom domains can be reported on a labelled Production/Aliased line.
    for line in reversed(cleaned.splitlines()):
        if re.search(r"\b(?:Production|Aliased|Deployed)\s*:", line, re.I):
            match = re.search(r"https://[^\s<>]+", line)
            if match:
                return match.group().rstrip(".,;)]}")
    raise DeploymentError("Vercel 未回傳部署網址，請檢查部署狀態後重試。")


def deploy(out_dir: str | Path, project_name: str, runner: Callable | None = None) -> str:
    directory = Path(out_dir).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"找不到部署資料夾：{directory}")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?", project_name):
        raise ValueError("Vercel 專案名稱請使用 1–100 個小寫英文字母、數字或連字號。")
    executable = shutil.which("npx")
    if not executable:
        raise DeploymentError("找不到 npx。請先安裝 Node.js，再執行 npx vercel login 登入。")
    # --project requires an existing project. For a freshly built, unlinked app,
    # CLI setup reads localConfig.name and --yes can create the named project.
    # Preserve builder headers. No credentials or project-link tokens are written.
    # https://github.com/vercel/vercel/blob/main/packages/cli/src/commands/deploy/index.ts
    # https://vercel.com/docs/cli/deploy#yes
    config_path = directory / "vercel.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DeploymentError("vercel.json 不是有效 JSON，請重新建置 App。") from exc
    if not isinstance(config, dict):
        raise DeploymentError("vercel.json 必須是 JSON 物件，請重新建置 App。")
    config["name"] = project_name
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    command = [executable, "--yes", "vercel", "deploy", "--prod", "--yes"]
    try:
        completed = (runner or subprocess.run)(
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
    return _deployment_url(completed.stdout)


def make_qr(url: str, png_path: str | Path) -> Path:
    path = Path(png_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url).save(path, format="PNG")
    return path
