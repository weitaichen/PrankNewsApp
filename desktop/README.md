# prank_news Python 核心

Python 3.13。從 `desktop/` 執行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m prank_news.cli --name 王小明 --name 陳小美 --minutes 3 --topic "吐司開始唱歌"
python -m prank_news.cli --name 測試 --script-file script.txt --out output/test
```

Claude 流程使用 PATH 上已安裝、已登入的 Claude Code，透過 `claude -p` 與使用者訂閱產稿。`--script-file` 讀取 UTF-8（可含 BOM），直接跳過 Claude。TTS 使用需要網路的 edge-tts，並用 mutagen 測量 MP3 秒數。核心不管理或寫入任何憑證。

範本預設為 repo 根目錄 `pwa_template/`；PyInstaller 模式為 `_MEIPASS/pwa_template`，打包者須加入此 data 目錄。範本尚未整合時可用 `--template <假範本資料夾>` 測試，核心不建立或修改原始範本。

加 `--deploy` 才部署；請先自行安裝 Node.js 並執行 `npx vercel login`。本工具的 `--project prank-news-example` 指定專案名稱，預設使用日期加隨機後綴。核心將名稱加入輸出的 `vercel.json`，保留原有 headers，再執行 `npx --yes vercel deploy --prod --yes`。Vercel 的 `deploy --project` 要求專案已存在，無法直接建立預設新專案；CLI 的 setup 仍會讀取 `vercel.json` 的 `name` 並在 `--yes` 時建立專案。依據：<https://vercel.com/docs/cli/deploy#yes> 與 <https://github.com/vercel/vercel/blob/main/packages/cli/src/commands/deploy/index.ts>。真實登入、首次建立專案與部署須在整合環境再驗證。

GUI 可在工作執行緒呼叫：

```python
from prank_news import NewsRequest
from prank_news.pipeline import generate_episode, build_and_deploy

request = NewsRequest(["王小明"], 3, "吐司開始唱歌")
episode = generate_episode(request, "output/work", progress=callback)
result = build_and_deploy(episode, "output/app", deploy=False, progress=callback)
```

callback 接收 `(stage, message)`。產生階段依序 `script → tts → done`，建置階段 `build → deploy（選用） → done`；整體流程中會有兩次 `done`，各表示該次函式已完成。函式為同步阻塞介面；`synthesize` 使用 `asyncio.run`，請勿在執行 asyncio 事件迴圈的同一執行緒呼叫。

`result` 包含 `out_dir: Path`、`url: str | None`、`qr_path: Path | None`。`Episode.audio_path` 在建置後更新為輸出音檔。`build_and_deploy` 額外接受 `template_dir`、`project_name`、`cover_path`，供整合與測試使用。

建置先暫存素材再清空輸出，所以來源 MP3／封面可位於原輸出目錄中；拒絕會覆蓋程式、範本或它們的上層目錄的輸出位置。`episode.json` description 使用稿子前 200 字，不含完整稿子。長稿一次合成失敗時，改用最多 1000 字的句子段落合成，串接 MP3 frame bytes；回傳各段實測音長總和，不需要 ffmpeg。

所有 pytest 都使用假 CLI runner、假 TTS 或假範本；不呼叫 Claude、Vercel 或網路。實際語音連線測試需另外透過 `--script-file` 執行。
