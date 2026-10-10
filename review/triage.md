# review-triage：既有審查發現核對

| 編號 | 標題 | 狀態 | 嚴重度 |
| --- | --- | --- | --- |
| 1 | 部署保護與乘客網址；RSS 使用未驗證的固定 domain | 部分修正：仍存在（新路徑，環境條件待確認） | 高 |
| 2 | CLI resolve 繞過 junction／symlink 防護 | 已修正 | 高 |
| 3 | 乘客名字進入節目／主播公開 metadata | 已修正 | 高 |
| 4 | 修改專案名稱後沿用舊 Vercel link | 已修正 | 高 |
| 5 | 同址更新後 PWA 持續播放舊單集 | 已修正 | 中 |
| 6 | 更新失敗造成新 metadata／舊 MP3 混版 | 已修正 | 中 |
| 7 | Cache API 寫入失敗也禁止線上串流 | 已修正 | 中 |
| 8 | Claude 繼承工作目錄、工具與專案設定 | 已修正（實際 CLI 隔離待確認） | 中 |
| 9 | 核心／CLI 預設網址包含 prank | 已修正 | 中 |
| 10 | 專案名稱接受三連字號 | 已修正 | 低 |
| 11 | 建置失敗前已提交新集並刪除舊集 | 新發現 | 高 |
| 12 | 多個製作程序交錯新增，單集從節目索引消失 | 新發現 | 高 |

核對日期：2026-10-10。基準：`agent/review-triage` 的 `62f0a0b6153137391ee134e416510c4fd68718e1`；原始 10 項全文以 `git show agent/review-codex:review/codex-review.md` 讀取。嚴重度沿用原報告；新項依資料遺失／無法取得單集的影響評定。9 項已修正、1 項部分修正，另有 2 項新發現。以下位置均為目前程式碼。

## 1. 部署保護與乘客網址

**狀態：部分修正；RSS 新路徑仍有網址不一致問題，實際服務條件待確認。嚴重度：高。**

已修部分：`desktop/prank_news/deploy.py:23–31,152` 合併部署輸出後優先使用 `Aliased:`，不再直接交付 generated deployment URL。`deploy.py:34–67` 以匿名 GET 檢查 RSS、JSON 與最新 MP3 Range，拒絕登入轉址／非預期 HTTP status；`deploy.py:152–164` 檢查通過才回傳，失敗會重試並提示部署保護設定。因此原本「直接把可能受保護的 generated URL 做成 QR」已有防護。

未修部分：`desktop/prank_news/pipeline.py:140–144,154` 在部署前固定使用 `https://<show.project>.vercel.app` 建站並回傳 feed URL；`desktop/prank_news/gui.py:469–478` 也把這個固定地址顯示為訂閱網址。`desktop/prank_news/builder.py:196–197,209–224` 把固定地址寫入 PWA 的 `feedUrl`、RSS link、封面與每集 enclosure。然而 `deploy.py:152–156` 只驗證 CLI 選出的 alias，`deploy.py:57–64` 測試的 MP3 是該 alias 下的 JSON 相對路徑，沒有追蹤 RSS 內真正的 enclosure，也沒有核對訂閱控制項使用的地址。

**具體失敗情境：** CLI 回傳 `https://public.example.com`，該 alias 的 RSS／JSON／MP3 均公開可讀；固定的 `<project>.vercel.app` 卻未指向此專案、已移除或無法匿名存取。GUI 仍宣告成功，QR 可開啟頁面，但按「在 Podcast 收聽」或複製訂閱網址後使用的是另一個地址。Apple Podcasts 可能無法訂閱、拿到其他 feed，或取不到 RSS 指定的 MP3。即使實際訂閱 custom alias，RSS enclosure 仍指向固定 domain。

**證據：** 離線假 CLI 回傳 `Aliased: https://public.example.test`，搭配實際 builder 產出的 RSS／JSON 與假 HTTP 回應，`deploy()` 成功回傳 custom alias。所有匿名請求只打 custom alias；產物的 feed URL／RSS enclosure 仍為 `morning-news-review.vercel.app`。這證實檢查與交付地址分離；未主張每個預設部署都失敗。

**建議修法：** 為每個節目保存並驗證實際固定 production domain，建置、RSS、GUI 與訂閱按鈕共用它。部署後檢查交付的 feed URL、RSS 封面及實際 enclosure，並核對最新 GUID／build ID 與本次本機產物；支援 alias 延遲的重試。避免僅以「某個可讀 RSS」判定本次訂閱路徑已可用。

**待確認：** 未連線 Vercel，故無法確認帳號上 default alias、custom domain、名稱碰撞與保護設定的實際關係。由使用者在測試專案核對 production domains，再以無憑證客戶端檢查實際訂閱網址和 enclosure；確認 Apple Podcasts 使用該地址訂閱、下載並取得下一集。

## 2. CLI resolve 繞過 junction／symlink 防護

**狀態：已修正。嚴重度：高。**

`desktop/prank_news/cli.py:57–64` 保留 `--out` 的原始 Path，沒有先 `.resolve()`。`desktop/prank_news/builder.py:28–33` 先對未解析的 absolute path 檢查 `is_symlink()`／`is_junction()`，再 resolve；RSS builder 在 `builder.py:161` 共用此檢查。因此 CLI 不再消除辨識連結所需的資訊。

**驗證：** 在本工作樹的暫存目錄建立 Windows junction 指向含 `keep.txt` 的目標，以實際 CLI 流程、假 TTS、隔離節目庫執行 `--script-file --out <junction>`。CLI 回傳 1，junction 與目標檔案均完整保留。暫存 junction 與檔案已移除。此驗證只證明輸出目標防護；失敗前節目庫仍會變動，另見第 11 項。

## 3. 乘客名字進入公開 metadata

**狀態：已修正。嚴重度：高。**

`desktop/prank_news/models.py:35–37` 對 request 的節目／主播使用中性 fallback；`desktop/prank_news/script_gen.py:98–99` 不再採用模型回傳的節目／主播。`desktop/prank_news/pipeline.py:91–109` 對 Claude 與 `--script-file` 都只取稿子，公開名稱取自 request／節目設定。

新的 RSS 路徑也有防護：`desktop/prank_news/show.py:25–42,69–75` 檢查完整名字及去姓後的相鄰兩字片段，包含專案名、節目名、主播及說明；`show.py:110–114` 在使用既有節目前檢查節目與歷史單集 metadata。`show.py:149–163` 產生中性單集標題、檢查隨機 ID／MP3 路徑；`pipeline.py:139–145` 在加入及建站前檢查節目。RSS 的 `<title>`、`<itunes:author>` 與 item title 在 `desktop/prank_news/builder.py:209–224` 使用這些節目庫資料，沒有序列化稿子或乘客名單。

GUI 的節目／主播欄位為唯讀（`desktop/prank_news/gui.py:168–173`），新增節目檢查目前乘客名單（`gui.py:262–263`），手動貼稿的建置路徑仍傳入乘客名單（`gui.py:427–446`）。因此原本 parser 接受乘客名標頭的能力已不會讓這些標頭進入受支援的 GUI／CLI 公開 metadata。

**驗證：** 以真實 show／builder、假 MP3 產生 RSS／JSON，確認 `王小明`、`小明` 均未進入產物；RSS GUID、獨立 MP3 檔名及 worker 版本一致。靜態核對了既有節目、GUI 編稿及 script-file 的資料流。實際 iPhone／鎖定畫面／CarPlay 顯示仍待裝置驗證；未發現原項在新的 metadata 路徑重新出現。

## 4. 改名後部署到舊 Vercel 專案

**狀態：已修正。嚴重度：高。**

GUI 專案現在隨選定節目設定（`desktop/prank_news/gui.py:232–243`），不再提供原本建置後直接改專案名的流程。核心也不再只寫 deprecated `vercel.json.name`：`desktop/prank_news/deploy.py:70–89,138–151` 清除不相符／無法辨識的 `.vercel` link，接著明確執行 `link --yes --project <名稱>`，成功後才執行 production deploy。即使原 link 名稱相符，仍會執行明確 link。

**驗證：** 以含 `projectName=morning-news-old` 的實際 `.vercel/project.json` 與假 runner 部署 `morning-news-new`；確認 runner 首次呼叫前舊 link 已移除，第一個命令明確 link 新專案，第二個才 deploy。沒有呼叫真的 npx／Vercel。服務端新專案建立、登入與 team scope 仍待測試帳號整合驗證。

## 5. 同址更新後持續播放舊集

**狀態：已修正。嚴重度：中。**

`desktop/prank_news/builder.py:82–93` 為 PWA 建置產生新 ID、替換 `sw.js` 版本並給素材加版本；RSS 建置在 `builder.py:193–197` 改用最新單集 ID 作為 worker／素材版本。`pwa_template/sw.js:52–55` 的 Cache 名稱含版本；`pwa_template/app.js:282–302` 安裝新版 worker 並在接管後重讀已提交的一整集。

Podcast 路徑使用 `desktop/prank_news/show.py:154–169` 的唯一 ID／MP3 檔案與新集優先索引；`builder.py:217–225` 寫入不同 GUID／enclosure，`builder.py:231–233` 對 feed 設定 `no-cache`。因此 RSS 更新沒有沿用固定 `episode.mp3` 或 PWA cache-first 的舊路徑。訂閱 domain 的缺口另見第 1 項。

**驗證：** Node 測試通過同址不同 build 的完整切換、`episodes/` MP3 離線 Range、controllerchange 後 metadata／audio 一起更新，以及延遲舊回覆不覆蓋新集。實際 Apple Podcasts 輪詢時間、背景更新與手動重新整理仍待 iPhone 確認；無離線證據支持把原快取缺陷判為仍存在。

## 6. 新 metadata／舊 MP3 混版

**狀態：已修正。嚴重度：中。**

`pwa_template/sw.js:79–102` 維持每個 build 的 immutable metadata，先寫該版本 MP3／封面、最後才提交 JSON；`sw.js:138–161` 在有完整舊版時拒絕不完整新版接管，只有新版完整才清舊 cache。`pwa_template/app.js:172–184,288–294` 依 worker 提交的 metadata 與 audio 狀態切換同一集。RSS 也使用各集不同實體 MP3 路徑（`desktop/prank_news/show.py:154–167`），沒有覆蓋同一 enclosure 的混版方式。

**驗證：** Node 測試對 MP3 500、404、下載失敗、body 中斷、quota 失敗與封面 500，均確認舊集保留、新版不接管；完整更新才一起切換。沒有發現原混版情境仍存在。

## 7. 無法快取時也不能線上播放

**狀態：已修正。嚴重度：中。**

`pwa_template/sw.js:112–125` 在首次安裝未完整快取時，以網路 HEAD 判斷可播放，但回報 `offlineReady=false`。即使已存在 active worker，`pwa_template/app.js:219–230` 仍在 worker 無可用音檔時做 HEAD fallback；`app.js:175–185` 允許線上播放並顯示保持連線的提示。Podcast MP3 下載也不依賴瀏覽器 Cache API。

**驗證：** Node 的首次 quota 失敗與 active worker quota 失敗案例均通過，確認仍可串流且不顯示離線完成。各 iPhone 的實際 quota 觸發及串流行為未做裝置驗證。

## 8. Claude 工作目錄／工具／設定繼承

**狀態：程式碼層面已修正；實際 CLI 隔離待確認。嚴重度：中。**

`desktop/prank_news/script_gen.py:92–100` 在專用空暫存目錄執行，拒絕缺標頭或字數不足目標 50% 的結果，重試一次仍不符就報錯；`script_gen.py:105–109` 明確傳入 cwd，以及 `--tools ""`、`--strict-mcp-config`、`--setting-sources ""`、`--safe-mode`、`--no-session-persistence`。這處理了原本無隔離參數及任意非空回答都可被接受的兩個缺口。

**驗證：** 使用真實 generate_script 與假 runner，檢查啟動參數、空工作目錄、兩次嘗試共用該目錄及結束清理；「請先確認任務。」連續兩次都被拒絕。沒有呼叫真實 `claude -p`。

**待確認：** 程式註解聲稱以 Claude Code 2.1.296 help 核對，但本次未驗證使用者實際版本是否支援這些旗標，以及 safe-mode 是否確實排除所在機器的 CLAUDE.md／hooks／MCP。在隔離整合環境加入可辨識的專案規則與工具／hook 哨兵，使用支援版本檢查其未執行且稿子未帶入規則。字數及標頭檢查仍非新聞語意的完整驗證，不據此宣稱所有不合內容都會被拒絕。

## 9. 預設網址包含 prank

**狀態：已修正。嚴重度：中。**

`desktop/prank_news/project.py:8–10` 統一產生 `morning-news-<6碼>`。節目建立使用此產生器（`desktop/prank_news/show.py:69`）；CLI 未指定節目時經 `desktop/prank_news/cli.py:49–53` 使用最近節目或建立中性預設節目，核心同樣經 `desktop/prank_news/pipeline.py:130–138,157–167`，GUI 新節目則在 `gui.py:254` 使用共用產生器。

**驗證：** 實際呼叫產生器取得中性前綴；實際 builder 產出的 feed URL／enclosure 為中性專案名。使用者明確指定或沿用含 prank 的既有節目仍可能自行暴露目的，但原項的「核心預設自動產生 prank 專案」已移除。

## 10. 名稱接受三連字號

**狀態：已修正。嚴重度：低。**

`desktop/prank_news/project.py:13–18` 在 regex 前拒絕 `---`，並給出具體中文原因。GUI 部署在 `desktop/prank_news/gui.py:458`、核心部署在 `desktop/prank_news/deploy.py:125`、新節目建立在 `desktop/prank_news/show.py:69` 使用共用 validator。

**驗證：** 離線實際呼叫 `validate_project_name("news---test")` 被 ValueError 拒絕。沒有呼叫 Vercel 建立專案。

## 11. 新發現：建置失敗前已提交新集並刪除舊集

**狀態：新發現。嚴重度：高。**

**位置：** `desktop/prank_news/pipeline.py:141–144`；`desktop/prank_news/show.py:164–175`；`desktop/prank_news/builder.py:161–168`；GUI 呼叫點 `desktop/prank_news/gui.py:443–446`。

**具體失敗情境：** 節目庫已存滿 20 集。使用 CLI／核心 API 指定會被 builder 拒絕的輸出位置，例如節目庫自身，或 GUI 建置在素材複製／封面輸出期間失敗。pipeline 先 `add_episode()`：複製新 MP3、寫入截斷成 20 集的索引、刪除最舊 MP3。之後 builder 才驗證輸出位置及完成建站，失敗時沒有 rollback。使用者收到「工作失敗，可修正後重試」，但既有一集的索引與本機音檔已被刪除；再次建置還會新增另一集並再淘汰一集。GUI 第二步本來就是 `deploy=False`，這些變動不必等到部署即可發生。

**證據：** 離線以真實 show／builder／pipeline 建立 20 集，再用 `out_dir=show.directory` 呼叫建置。builder 如預期拋 ValueError 拒絕輸出重疊，但原最舊 MP3 已不存在、原 GUID 已離開索引、新集已提交，索引仍為 20 集。驗證使用假音檔，未合成、未部署。20 集上限是文件約定；缺陷在失敗路徑提前提交及淘汰。

**建議修法：** 在修改節目庫前先完成輸出／範本等可預先執行的驗證。新增單集及新的索引先暫存，以候選索引建站，成功後才提交索引並淘汰超額音檔；後續失敗清理暫存並保留原庫。將建置與部署失敗的恢復策略分別定義，讓重新部署可重用已存在的集數。補「20 集時輸出拒絕／封面或複製失敗，原索引與 20 個 MP3 全保留」測試。

## 12. 新發現：交錯新增造成單集從節目索引消失

**狀態：新發現。嚴重度：高。**

**位置：** `desktop/prank_news/show.py:45–48,137–175`，尤其 `show.py:146,168–169`；GUI 工作者的 busy guard `desktop/prank_news/gui.py:339–354` 僅限單一視窗。

**具體失敗情境：** 同時開兩個 GUI，或 GUI 與 CLI 同時製作同一節目。A／B 都先讀到同一份 `episodes.json`。B 複製 MP3 並寫入新索引後，A 用先前讀到的舊清單加上自己的集數覆寫索引。兩個新增都可成功，但 B 的單集不再列在節目庫及下一次 RSS 中，Apple Podcasts 收不到它；MP3 留為無索引檔案。固定的 `episodes.tmp` 名稱也讓真正重疊的寫入可能互相取代或造成 replace 失敗。JSON 原子 replace 僅保護單次檔案替換，沒有保護整個讀取、追加及淘汰程序。

**證據：** 離線在實際 `add_episode()` 的 copy 階段插入第二次 `add_episode()`，重現兩者都讀過原索引、內層先提交、外層後提交的交錯順序。兩次呼叫都成功，結果有兩個 MP3，但索引僅一集；內層 GUID 消失。這是確定性時序模擬，未聲稱已做多個 GUI 的壓力測試。

**建議修法：** 每節目使用跨程序互斥鎖，涵蓋重讀索引、配發單集、複製／提交、淘汰與建立一致部署快照；或使用具交易功能的儲存方式。各次暫存檔也使用獨立名稱。新增雙程序同節目測試，確認成功的兩集均在索引／RSS、GUID 不重複、保留政策一致。單一 GUI 的 busy 狀態不足以保護共享節目庫。

## 驗證結果與限制

- `node --test pwa_template/tests/`：**46 通過，0 失敗**。範圍為 Node VM／假 DOM、worker cache 與 Range 模擬，非 iPhone／CarPlay 實機測試。
- 指定的 `desktop/.venv/Scripts/python.exe` **不存在**。改嘗試 `python -B -m pytest -q -p no:cacheprovider desktop/tests`，在系統 Python 3.13.7 得到 **No module named pytest**；完整 Python 測試未能執行。系統有 Pillow，但缺 edge-tts、mutagen、qrcode；未安裝依賴。
- 以 `python -B` 從 stdin 執行離線驗證：25 個 Python／spec 檔案 AST 解析通過；真實 CLI junction 拒絕／目標保留、中性 RSS／JSON、單集 ID 與 SW 版本、名稱 validator、假 Claude 啟動隔離與拒絕結果、假 Vercel 改 link，以及第 1、11、12 項重現均通過各自斷言。
- 因缺少依賴，離線驗證在記憶體載入原始 AST 時只省略 deploy 的 qrcode import，以及 pipeline 的 deploy／tts import，注入假服務或禁止呼叫的函式；builder／show／CLI 及受測核心函式使用目前原始碼。這些針對性驗證不等同完整 pytest、真實 MP3 解碼、GUI 視覺或部署驗證。
- 所有探測檔案與 junction 都建立在本工作樹暫存目錄並已清理；使用 `-B`，未留下 bytecode／測試快取。沒有呼叫真實 `claude -p`、edge-tts、npx／Vercel、HTTP 或部署，也沒有 push／merge／checkout／commit。
- 未確認的外部項目：Vercel 實際 domain／保護／team scope、Claude CLI 版本及隔離效果、Apple Podcasts 的訂閱／更新／下載、iPhone 與 CarPlay 行為、打包 exe。確認方式已於相關項目說明，不把這些尚未執行的檢查當成通過。
- 最終唯一新增檔案為 `review/triage.md`，未修改程式、測試或其他文件。

## 建議要修的項目（依優先順序）

1. **第 11 項：建置與節目庫提交／淘汰形成可恢復交易。** 先阻止失敗建置刪除原集數及 MP3。
2. **第 1 項未修部分：固定訂閱 domain 與實際匿名檢查一致。** 驗證交付的 feed URL、最新 GUID 及 RSS enclosure；部署成功時確保 Apple Podcasts 使用的地址正確。
3. **第 12 項：共享節目庫跨程序鎖與一致快照。** 避免兩個製作程序都成功卻少了一集。
4. **驗收前補足確認：** 在具依賴的環境執行完整 pytest，驗證實際 Claude 隔離旗標，並以測試節目完成 Vercel 匿名訂閱／新集下載及 Apple Podcasts 實機驗收。已修正的原項不需依舊報告重做同一修正。
