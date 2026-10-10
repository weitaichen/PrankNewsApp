# prank_news Python 核心

## 桌面介面（Windows）

首次使用請先完成以下準備；exe 不會替使用者登入或儲存 token／密碼：

1. 安裝並登入 Claude Code。在 PowerShell 執行 `claude`，完成互動登入，確認 `claude` 在 PATH 上且訂閱可用。
2. 安裝 Node.js（含 `npx`），在 PowerShell 執行 `npx vercel login` 完成 Vercel 登入。
3. 安裝工具後重新開啟 GUI，讓程式取得更新的 PATH。產稿、語音合成、首次下載 Vercel CLI 和部署都需要網路。

從 repo 的 `desktop/` 執行 GUI（Python 3.13，需包含 tkinter；Windows 官方 Python 安裝程式可安裝 Tcl/Tk）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_gui.py
# 也可使用：.\.venv\Scripts\python.exe -m prank_news.gui
```

填入乘客名字（逗號或頓號分隔）、長度、內容梗與聲音，按「一、產生新聞稿」。完成後可編修節目名、主播名與稿子；字數含標點、不計空白，預估每分鐘 250 字。也可直接貼上稿子並填寫節目名、主播名，跳過 Claude。

按「二、產生語音並建立 App」會使用目前編修內容，預設輸出到 `%USERPROFILE%\Documents\PrankNews\<時間戳>`；「選資料夾」可改父資料夾，每次建置都另建時間戳子資料夾。完成後可「試聽」MP3 或「開啟資料夾」。修改稿子、節目／主播名或聲音後，請重新建置再部署。

確認 Vercel 專案名稱後按「三、部署到手機」。名稱預設為 `morning-news-<6 位小寫英數>`，可改成 1–100 個小寫英文字母／數字／中間連字號。完成後顯示可複製的網址與 QR code：用 iPhone 相機掃描 → Safari 開啟 → 分享 → 加入主畫面；打開 App 等到顯示「已可離線收聽」。部署會將建好的 App 上傳到 Vercel，請先試聽確認內容。

工作期間會停用操作並顯示進度，請等工作完成後關閉視窗。錯誤會以中文對話框顯示，完整例外紀錄在 `%LOCALAPPDATA%\PrankNews\app.log`（最多約 2 MB／檔，保留 3 份輪替）。

## 打包單一 exe

從 `desktop/` 在 Windows PowerShell 執行：

```powershell
.\build_exe.ps1
# 若 PowerShell 的執行原則擋下腳本，可僅針對這次執行：
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
# 指定 Python：.\build_exe.ps1 -Python C:\Python313\python.exe
```

腳本建立／使用 `desktop/.venv`，安裝執行依賴、pytest 與 PyInstaller 6，先執行測試，再依 `prank_news.spec` 建置 `desktop/dist/PrankNews.exe`。首次安裝需要可連線的套件來源。若依賴已安裝，也可自行執行：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build prank_news.spec
```

spec 使用 onefile、windowed 模式，將 repo 的 `pwa_template/` 放到 `_MEIPASS/pwa_template`，排除 `tests/` 與 `README.md`；包含 edge-tts 資料、certifi TLS 憑證、qrcode、Pillow ImageTk／PNG 與 mutagen。打包不會改動原始範本。Claude 與 npx 使用核心既有的 `CREATE_NO_WINDOW`，不另開主控台；exe 使用者仍需自行安裝、登入這兩個外部 CLI。

離線驗證（不呼叫 Claude、語音服務或部署）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -c "import prank_news.gui"
```

GUI 目視操作、真實語音連線、外部 CLI 無黑色視窗、Vercel 登入／部署與 iPhone 離線收聽需在使用環境另驗證。

## 命令列與核心 API

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

GUI 的分步流程先用 `script_gen.generate_script(request)` 取得節目名／主播名／稿子，再呼叫 `pipeline.synthesize_episode(show, anchor, script, voice, work_dir, progress=callback)`。此新增 API 不呼叫 Claude、不重新解析或清理文字，會原樣合成使用者編修的稿子，回傳 `Episode`；進度為 `tts → done`，之後可接 `build_and_deploy(..., deploy=False)`。GUI 的第三步只部署已建好的資料夾並產生 QR code，不會重新合成或建置。

callback 接收 `(stage, message)`。產生階段依序 `script → tts → done`，建置階段 `build → deploy（選用） → done`；整體流程中會有兩次 `done`，各表示該次函式已完成。函式為同步阻塞介面；`synthesize` 使用 `asyncio.run`，請勿在執行 asyncio 事件迴圈的同一執行緒呼叫。

`result` 包含 `out_dir: Path`、`url: str | None`、`qr_path: Path | None`。`Episode.audio_path` 在建置後更新為輸出音檔。`build_and_deploy` 額外接受 `template_dir`、`project_name`、`cover_path`，供整合與測試使用。

建置先暫存素材再清空輸出，所以來源 MP3／封面可位於原輸出目錄中；拒絕會覆蓋程式、範本或它們的上層目錄的輸出位置。`episode.json` description 使用固定的「今日頭條新聞」，不含完整稿子。長稿一次合成失敗時，改用最多 1000 字的句子段落合成，串接 MP3 frame bytes；回傳各段實測音長總和，不需要 ffmpeg。

所有 pytest 都使用假 CLI runner、假 TTS 或假範本；不呼叫 Claude、Vercel 或網路。實際語音連線測試需另外透過 `--script-file` 執行。
