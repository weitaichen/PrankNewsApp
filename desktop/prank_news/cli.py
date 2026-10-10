"""Run with: python -m prank_news.cli --name 王小明 --minutes 3 --topic ..."""

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .builder import default_template_dir
from .models import NewsRequest
from .pipeline import build_and_deploy, generate_episode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="產生輕鬆無害的整人新聞 App")
    parser.add_argument("--name", action="append", required=True, help="乘客名字，可重複指定")
    parser.add_argument("--minutes", type=float, default=3, help="新聞長度（0.5–15 分鐘）")
    parser.add_argument("--topic", default="", help="新聞內容／梗")
    parser.add_argument("--voice", default="zh-TW-HsiaoChenNeural")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--deploy", action="store_true", help="部署至已登入的 Vercel")
    parser.add_argument("--script-file", type=Path, help="UTF-8 播報稿；跳過 Claude")
    parser.add_argument("--template", type=Path, help="指定 PWA 範本（預設 repo 的 pwa_template）")
    parser.add_argument("--project", help="指定 Vercel 專案名稱")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    def progress(stage: str, message: str) -> None:
        print(f"[{stage}] {message}", flush=True)

    try:
        request = NewsRequest(args.name, args.minutes, args.topic, voice=args.voice)
        script = args.script_file.read_text(encoding="utf-8-sig") if args.script_file else None
        template = args.template if args.template is not None else default_template_dir()
        if not template.is_dir():
            raise FileNotFoundError(f"找不到 PWA 範本資料夾：{template}；可用 --template 指定。")
        output = args.out or Path("output") / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        output.parent.mkdir(parents=True, exist_ok=True)
        # Keep synthesis work outside the app directory that build_app replaces.
        with tempfile.TemporaryDirectory(prefix="prank-news-", dir=output.parent) as temp:
            episode = generate_episode(request, temp, progress, script_text=script)
            result = build_and_deploy(
                episode, output, deploy=args.deploy, progress=progress,
                template_dir=template, project_name=args.project,
            )
        print(f"資料夾：{result['out_dir']}")
        if result["url"]:
            print(f"網址：{result['url']}")
            print(f"QR code：{result['qr_path']}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
