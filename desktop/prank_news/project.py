"""Shared public project naming for the GUI, CLI, and deployment core."""

import re
import secrets
import string


def default_project_name() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "morning-news-" + "".join(secrets.choice(alphabet) for _ in range(6))


def validate_project_name(name: str) -> str:
    if "---" in name:
        raise ValueError("Vercel 專案名稱不可包含三個連續連字號（---）。")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?", name):
        raise ValueError("Vercel 專案名稱請使用 1–100 個小寫英文字母、數字或中間連字號。")
    return name
