# 新聞快報 PWA 範本

純靜態、無框架、無外部 CDN 的最新單集播放器，作為 Apple Podcasts 訂閱的入口與備案；不需要 npm 安裝或編譯。桌面程式會產生節目的 `feed.xml`、1400×1400 `podcast-cover.png`、保留的 `episodes/<id>.mp3`，並覆蓋 `episode.json` 與 512×512 `cover.png`。手動使用舊的 `episode.mp3` 格式仍可播放。

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `index.html` | 單集頁、單一 audio 元素、iOS 主畫面設定 |
| `app.js` | Podcast 訂閱／複製網址、播放、暫停、進度、跳轉、Media Session、快取狀態 |
| `style.css` | 深色 iPhone 直式介面及四邊安全區 |
| `sw.js` | 預快取、離線播放、純函式 `buildRangeResponse` |
| `manifest.json` | 主畫面名稱「新聞快報」、standalone、圖示 |
| `episode.json` | 單集資料，建置時覆蓋 |
| `cover.png` | 512×512 範例封面，建議替換為同尺寸 PNG |
| `icon-192.png` / `icon-512.png` | PWA 圖示 |
| `apple-touch-icon.png` | 180×180 iOS 主畫面圖示 |
| `tests/range.test.mjs` | Node 內建測試：Range 內容與標頭 |
| `tests/sw.test.mjs` | Worker 快取生命週期、離線與缺檔測試 |
| `tests/app.test.mjs` | 模擬 DOM 的播放器、Media Session、缺檔及重新檢查測試 |
| `tests/index.js` | 明確指定 tests 目錄時的 Node 測試入口 |

**不附 `episode.mp3`。** 缺少音檔時，頁面顯示「本集音訊尚未上線，請稍後再試。」並停用播放控制。新增檔案後，按「重新檢查音訊」即可重新快取，不必重新安裝 PWA。`tests/` 不會被 SW 預快取，部署時也可略過。

## episode.json 固定格式

```json
{
  "show": "晨間新聞快報",
  "title": "2026年10月4日 晨間新聞",
  "anchor": "主播 林雅婷",
  "published": "2026-10-04",
  "durationSec": 180,
  "audio": "episode.mp3",
  "cover": "cover.png",
  "description": "今日頭條新聞"
}
```

上述欄位必填。`durationSec` 為非負數字（秒），其餘為非空字串；`published` 可使用 `YYYY-MM-DD` 或含時區 ISO 8601。`audio` 和 `cover` 是相對於範本目錄的同源資源路徑，也可使用同源絕對 URL。桌面建置的音檔路徑是 `episodes/<id>.mp3?v=<buildId>`。不要使用外部網址。音訊 metadata 載入後，以音檔實際長度更新總長與拖曳範圍。文字以 `textContent` 顯示，不解析成 HTML。

可選欄位 `feedUrl` 是 HTTPS 絕對網址，例如 `https://morning-news-example.vercel.app/feed.xml`。存在時，播放器上方顯示主要按鈕「在 Podcast 收聽」，連到 `podcasts://morning-news-example.vercel.app/feed.xml`；小字「複製訂閱網址」使用 Clipboard API，失敗時顯示可選取文字。沒提供或網址無效時，這些控制項隱藏，不影響播放器。頁面使用自訂 alias 時，仍能訂閱固定 Vercel 網址的 feed。下方收合的說明提供手動訂閱步驟：Podcasts App → 資料庫 →「⋯」→「透過 URL 追蹤節目」→ 貼上網址。

Media Session 使用 `title` 作單集標題、`anchor` 作 artist、`show` 作 album；artwork 以同一個封面 URL 提供多個尺寸提示。封面請使用正方形 512×512 以上圖檔。瀏覽器未支援某個 Media Session action 時，頁內控制仍可使用。

## 本機執行與測試

從專案根目錄執行：

```sh
node --test pwa_template/tests/
cd pwa_template
python -m http.server 8000
```

桌面瀏覽器開啟 `http://localhost:8000/`。localhost 允許 Service Worker；一般 LAN IP 的 HTTP 網址不允許，iPhone 測試需要 HTTPS 網址。直接以 `file://` 開啟也無法使用 SW。

手動驗證：

1. 不放 MP3 時，確認頁面友善提示、控制停用，且沒有未捕捉的 JS 錯誤。
2. 放入任意可播放 MP3，命名為 `episode.mp3`，按「重新檢查音訊」，確認播放、暫停、拖曳、倒退及快轉。
3. 等待「已可離線收聽」，切斷連線後重新整理，測試播放與任意位置跳轉。DevTools 開啟 Offline 時，勿勾選「Bypass for network」。
4. 建置節目後，iPhone Safari 開啟 HTTPS 網址，按「在 Podcast 收聽」或手動貼上訂閱網址；確認 Apple Podcasts 可訂閱、更新單集、鎖定螢幕播放及 CarPlay 顯示。PWA 可由分享選單加入主畫面作備案。

## 離線與版本

SW 安裝時快取殼層，再下載封面與完整音檔，兩者寫入成功後才提交 `episode.json`。只有殼層、單集資料、封面、完整音檔都快取成功，才顯示「已可離線收聽」。已有完整舊版時，新版素材下載或寫入失敗會拒絕新版接管，保留舊節目與音檔。首次使用若儲存空間不足但網路可取得音檔，仍允許串流並顯示「目前無法離線儲存，請保持連線收聽」。初次等待逾時後仍監聽 worker 就緒與 controllerchange，完成後會更新狀態。

`buildRangeResponse(fullResponse, rangeHeader)` 只讀取完整 Response 的 clone，不使用網路或快取。支援 `bytes=0-1`、`bytes=100-`、`bytes=-50` 等單一 byte range，回傳 206 與正確的 `Content-Range`、`Content-Length`、`Accept-Ranges: bytes`；不可滿足的範圍回 416 與 `bytes */總長`；無 Range 回完整 200。超出檔尾的 end 截至檔尾，過長的 suffix 回整份 206。未支援的 multipart 或格式錯誤的 Range 會忽略並回完整 200。Worker 不會快取 206 部分回應。

`sw.js` 的 `CACHE_VERSION` 使用 `__BUILD_ID__` 佔位字串；desktop builder 替換為最新單集 ID，JSON 使用相同 `buildId`，音檔／封面 URL 附上 `?v=<id>`。每個版本使用獨立 cache；同網址更新時，新 worker 完整下載後才接管，頁面一併更新標題與音檔。`episodes/` 路徑沿用同源快取與 Range 處理。activate 只清除此 scope 的舊版本。原始範本的佔位字串也可作快取版本直接執行；手動替換單集時須同步更換 worker 版本與素材網址。

離線資料仍受瀏覽器儲存空間限制，系統可能清除快取。Media Session 可提供 CarPlay/鎖定畫面 metadata 與控制，但實際顯示方式與 action 支援取決於 iOS、Safari 及車機；靜態 PWA 無法保證每台車機的介面一致。
