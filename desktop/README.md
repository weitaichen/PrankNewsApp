# prank_news 桌面程式與核心 API

每個節目使用固定的 Vercel 專案與私人 podcast RSS feed。iPhone 在 Apple Podcasts 訂閱一次，之後產生的新聞會成為同一節目的新一集；PWA 播放器保留作為備案。QR code 開啟播放器頁面，由頁面的「在 Podcast 收聽」按鈕引導訂閱。

## 安裝與啟動（Windows）

1. 安裝並登入 Claude Code：PowerShell 執行 `claude`，完成登入，確認 PATH 與訂閱可用。
2. 安裝 Node.js（含 npx），執行 `npx vercel login`。
3. 安裝工具後重新開啟 GUI，使更新的 PATH 生效。產稿、edge-tts 語音與部署需要網路；exe 不管理或儲存登入憑證。

Python 3.13 需包含 tkinter。從 `desktop/` 執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe run_gui.py
# 或：.\.venv\Scripts\python.exe -m prank_news.gui
```

## 桌面操作

1. 頂部「節目」下拉選單可選既有節目。首次啟動會引導建立；「新增節目…」可填節目名、主播名，專案名自動產生，也可修改。專案名使用 1–100 個小寫英文字母、數字或中間連字號，禁止 `---`。節目與主播名不可含乘客名字或去姓後的兩字以上片段；新增及產稿／建置前都會檢查。
2. 填乘客名字（逗號或頓號分隔）、分鐘、內容梗與主播聲音。按「一、產生新聞稿」後可編輯稿子，也可直接貼上稿子跳過 Claude。節目與主播名取自節目設定；開場要求「歡迎收聽〈節目名〉，我是〈主播名〉」。字數包含標點、不計空白，預估每分鐘 250 字。
3. 按「二、產生語音並建立 App」，加入節目庫的新一集並重建完整 feed 與播放器。每次建置會新增單集；「試聽」「開啟資料夾」照常可用。輸出預設在 `%USERPROFILE%\Documents\PrankNews\<時間戳>`，可選其他父資料夾。修改稿子、乘客名、聲音或切換節目後須重新建置。
4. 確認試聽後按「三、部署到手機」。每次部署到所選節目的固定專案。匿名檢查 `feed.xml`（200、有效 RSS XML）、`episode.json`（200 JSON）與最新 MP3 的 `Range: bytes=0-1`（206）；重試後仍失敗會提示至 Settings → Deployment Protection 關閉 Vercel Authentication，再確認網路與 alias 生效後重試。成功才顯示播放器網址、QR 與可複製的訂閱網址。

第一次：iPhone 掃 QR → 按「在 Podcast 收聽」訂閱。之後新的一集會自動出現在 Podcasts App（可在節目頁下拉重新整理）。車上：接上 CarPlay → Podcasts → 本節目。

若按鈕沒有反應：打開 Podcasts App → 資料庫 → 右上角「⋯」→「透過 URL 追蹤節目」→ 貼上訂閱網址。PWA 的「複製訂閱網址」使用 Clipboard API；失敗時顯示可選取的網址文字。播放器提供最新一集與離線快取。

工作期間操作會停用，請等完成後關閉視窗。錯誤使用中文對話框；完整例外紀錄在 `%LOCALAPPDATA%\PrankNews\app.log`（約 2 MB／檔，保留 3 份輪替）。

## 節目庫與部署內容

節目庫位於 `%USERPROFILE%\Documents\PrankNews\shows\<project>\`，與每次建置輸出分開。`show.json` 只存專案、節目名、主播名、中性說明與建立時間；`episodes.json` 只存單集 ID、中性標題、含時區發布時間、秒數、MP3 相對路徑與位元組數。乘客名單與稿子不寫入這些資料或公開 JSON／RSS，也不作為檔名。MP3 本身是包含乘客名字的播報內容。

單集使用「10月10日 晨間新聞」等中性標題，同日第二集為「10月10日 晨間新聞（二）」，依序增加。新的在前，最多保留 20 集；超出的舊單集及本機 MP3 一起刪除，下次部署也不再包含舊檔。`.last-show` 只保存最近使用的專案名稱。

部署網址為 `https://<project>.vercel.app`，訂閱網址為 `/feed.xml`。RSS 2.0 包含 iTunes／content namespace、絕對 HTTPS enclosure、位元組長度、唯一 GUID 與 RFC 2822 日期。`itunes:block=Yes` 避免被收錄至 Apple 目錄；feed 與音檔仍可由持有網址的人匿名存取。

封面為 1400×1400 RGB PNG，依序嘗試系統 `msjhbd.ttc`、`msjh.ttc`、`mingliu.ttc`，以深色背景畫節目名。沒有可用字型時放大範本封面；另產出 PWA 的 512×512 `cover.png`。系統字型不打包。部署包含保留的所有 `episodes/<id>.mp3`；PWA `episode.json` 指向最新一集並帶 `feedUrl`。SW 版本與素材 URL 同用單集 ID，新版本完整快取後才接管，支援 `episodes/` 路徑的離線 Range。

每次建置重建部署資料夾，保留範本既有 Vercel headers，新增 RSS MIME／no-cache 及 MP3 Accept-Ranges。部署沿用 `npx --yes vercel link --yes --project <名稱>` 與 `npx --yes vercel deploy --prod --yes`；不相符或無法辨識的 `.vercel` 連結會先清除。QR 編碼播放器網址。

## CLI

從 `desktop/` 執行：

```powershell
# 建立節目並產生第一集；--project 可省略以自動產生
python -m prank_news.cli --name 王小明 --new-show "晨間新聞快報" --anchor "主播 林雅婷" --project morning-news-example --minutes 3 --topic "吐司開始唱歌" --deploy
# 既有節目的下一集
python -m prank_news.cli --name 王小明 --show morning-news-example --minutes 3 --topic "吐司開始唱歌" --deploy
# 未指定節目：用最近使用的節目，空節目庫自動建立預設節目
python -m prank_news.cli --name 王小明 --script-file script.txt --out output/test
```

`--show` 與 `--new-show` 互斥。`--anchor` 是新節目的主播名，`--project` 只用於建立節目。未加 `--deploy` 只建置本機資料，但仍加入節目庫。`--script-file` 讀 UTF-8（可含 BOM）並跳過 Claude；若有 `節目：`／`主播：` 標頭，只取稿子，公開資料一律使用節目設定。`--template` 可指定其他 PWA 範本。

Claude 使用使用者的訂閱，於專用空暫存目錄執行 `claude -p`；停用工具、MCP 與自訂設定，沿用保留登入的 `--safe-mode`。回應仍要求前兩行標頭，缺標頭或字數不足目標 50% 重試一次。edge-tts 合成後由 mutagen 量 MP3 秒數；長稿失敗時改用最多 1000 字的句子段落合成、串接 MP3 frames，無需 ffmpeg。

## 核心 API 與測試

```python
from prank_news import NewsRequest
from prank_news.show import create_show, load_show, list_shows
from prank_news.pipeline import generate_and_deploy

show = create_show("晨間新聞快報", "主播 林雅婷", root_dir="output/local-shows")
request = NewsRequest(["王小明"], 3, "吐司開始唱歌")
result = generate_and_deploy(request, show, "output/work", "output/app",
                             deploy=False, progress=callback)
```

`root_dir` 可注入 `create_show`／`load_show`／`list_shows` 作為節目庫根目錄。`add_episode(show, mp3_path, duration_sec)` 加單集；可注入含時區的 `when` 與私人 `passenger_names`，後者只用於檢查、不儲存。`builder.build_show_site(show_dir, template_dir, out_dir, base_url)` 產生部署內容。

GUI 分步呼叫 `generate_script(request)`、`synthesize_episode(...)`、`build_and_deploy(..., show=show, deploy=False)`，第三步只部署已建內容。`generate_and_deploy` 串接完整流程。回傳包含 `out_dir: Path`、`url: str | None`、`feed_url: str`、`qr_path: Path | None`；未部署時 `url`／`qr_path` 是 `None`。進度 callback 接收 `(stage, message)`：產生為 `script → tts → done`，建置為 `build → deploy（選用） → done`。

這些 API 同步阻塞，適合 GUI 工作執行緒；不要在已有 asyncio 事件迴圈的同一執行緒呼叫語音合成。建置拒絕會覆蓋程式、範本或節目庫的輸出目錄。

```powershell
# 從 desktop/
python -m pytest -q
python -c "import prank_news.gui"
# 從 repo 根目錄
node --test pwa_template/tests/
```

pytest 使用假 Claude runner、假 TTS、假公開 checker 與隔離節目庫，不呼叫真實服務或部署。Apple Podcasts 訂閱、更新頻率、CarPlay、鎖定螢幕、導航插話及 Vercel 首次登入／部署仍需在使用環境驗證。

## 打包單一 exe

從 `desktop/` 在 Windows PowerShell 執行：

```powershell
.\build_exe.ps1
# 若執行原則阻擋，只對這次執行設定：
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
# 指定 Python：.\build_exe.ps1 -Python C:\Python313\python.exe
```

腳本建立／使用 `desktop/.venv`、安裝依賴、執行測試，然後依 `prank_news.spec` 建置 `desktop/dist/PrankNews.exe`。也可直接執行：

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build prank_news.spec
```

spec 使用 onefile／windowed，將 `pwa_template/` 放到 `_MEIPASS/pwa_template`（不含 tests／README），包含 edge-tts、certifi、qrcode、Pillow 與 mutagen。Pillow 使用系統中文字型，無需額外打包字型。Claude／npx 沿用 `CREATE_NO_WINDOW`。GUI 目視操作、打包後外部 CLI 與真實連線請另行驗證。
