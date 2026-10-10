# desktop-gui-2 審查修正（2026-10-10）

變更範圍：`desktop/prank_news/{project,models,pipeline,deploy,script_gen,builder,cli,gui}.py`、`desktop/prank_news.spec`、相關 Python 測試、`pwa_template/{app,sw}.js` 與 Node 測試，以及兩份 README。本檔記錄逐項驗收；未修改 `review/`、`.agents/`、`CLAUDE.md`，未呼叫真實產稿、TTS 或部署，未 commit／push／merge／checkout。

| 項目 | 處理方式 | 回歸測試名稱 |
| --- | --- | --- |
| 1 公開 QR 網址 | 合併 stdout／stderr，優先 `Aliased:`，否則 production alias；無憑證 urllib GET 驗證 200／JSON，最多三次重試，保護失敗顯示指定中文指引；檢查器可注入 | `test_alias_on_stderr_wins_over_generated_url`、`test_deploy_url_and_command`、`test_anonymous_episode_get_validates_json_and_redirect`、`test_public_check_retries_alias_delay_and_reports_protection` |
| 2 每集新專案 | GUI 每次建立 App 重設可編輯的預設名；名稱不同／未知／壞 JSON 時刪除 `.vercel`；先 `link --yes --project` 再 prod deploy | `test_gui_each_build_refreshes_project_and_passes_private_names`、`test_project_link_removed_before_relink`、`test_deploy_url_and_command` |
| 3 中性名稱 | `project.py` 共用 `morning-news-<6碼>`，pipeline／CLI／GUI 使用同一產生器 | `test_default_project_name`、`test_core_default_project_is_neutral`、`test_cli_default_project_uses_core_generator` |
| 4 名稱驗證 | GUI 與 deploy 共用 validator，禁止 `---` | `test_valid_project_names_match_core`、`test_invalid_project_names_match_core` |
| 5 metadata 防穿幫 | prompt 禁止名字／內容梗；Episode 保留私有名單，pipeline 在 build 前檢查 show／anchor／title 的全名與兩字以上名字片段並換中性值 | `test_prompt_names_length_and_constraints`、`test_build_sanitizes_all_public_metadata`、`test_script_file_names_reach_build_guard`、`test_gui_edited_metadata_is_sanitized_at_build`、`test_default_anchor_cannot_leak_matching_passenger` |
| 6 Claude 隔離 | 空 TemporaryDirectory 作 cwd，`--tools ""`、`--strict-mcp-config`、空 setting sources、保留登入的 safe mode；不用 bare | `test_runner_receives_prompt_utf8_and_timeout` |
| 7 產稿驗證／重試 | 嚴格解析兩個非空標頭，正文可見字數至少目標 50%；不合格自動重試一次，仍失敗拋中文錯誤 | `test_invalid_script_retried_once_then_recovers`、`test_invalid_script_after_retry_raises_chinese_error` |
| 8 建置快取版本 | 時間戳＋隨機 build ID 替換 worker 佔位字串；JSON／audio／cover 綁同 ID、独立 cache；先完整寫素材再提交 JSON；更新不完整時拒絕接管舊版 | `test_each_build_versions_worker_and_media_together`；Node `each build gets its own cache and a complete update switches metadata and MP3 together`、`incomplete update preserves old episode and refuses activation`（404／500／網路中斷／200 後 body 中斷／quota／封面失敗）、`old worker refresh keeps committed metadata immutable while a new build installs`、`controllerchange switches title and audio to the committed new build` |
| 9 quota 仍可播放 | worker 區分快取與網路可取得音檔，頁面另有 HEAD fallback；串流時不顯示離線完成 | Node `quota failure on first install allows streaming but never reports offline ready`、`active worker quota failure still enables network streaming without offline badge` |
| 10 慢速網路 | 準備逾時後持續監聽 ready／controllerchange，重新載入已提交 metadata 並查狀態 | Node `worker becoming ready after preparation timeout eventually shows offline badge`、`late ready promise alone refreshes offline status without controllerchange` |
| 11 Combobox focus | 捕捉 native popdown 的 KeyError | `test_topic_hint_handles_combobox_popdown_focus` |
| 12 佇列輪詢 | finally 重新排程 after，意外 callback 例外後可繼續處理完成事件 | `test_event_poll_reschedules_after_unexpected_exception` |
| 13 打包排除 | spec／builder 排除 `.vercel`、`node_modules` | `test_spec_excludes_vercel_and_node_modules`、`test_builder_excludes_deployment_and_node_directories` |
| 14 CLI 輸出連結防護 | CLI 保留原始 out 路徑交給 builder，不提早 resolve | `test_cli_rejects_symlink_output_without_deleting_target`（Windows 無建立連結權限時 skip） |

驗證結果：

- `node --test pwa_template/tests/`：**35 通過，0 失敗**。另補 `metadata waits for matching audio status and late old replies cannot revert a new episode`，確認等待新狀態時不混版、延遲舊回覆不會倒回舊集。
- Python／spec AST 語法檢查：**22 個檔案通過**。
- 標準函式庫 smoke checks：共用名稱／三連字號、隔離空 cwd 的假 Claude runner 與不合格回應重試、真實 PWA 範本建置兩次的唯一 ID／版本素材 URL、建置後 worker 的 `node --check` 通過。`test_spec_excludes_vercel_and_node_modules` 也以標準函式庫直接執行通過，未載入 PyInstaller。**不是完整 pytest 結果**。
- `cd desktop; python -m pytest -q`：**無法執行**，`No module named pytest`。嘗試將 requirements-dev 及單獨 pytest 安裝至工作目錄 `.cache/python`，皆無法取得套件（`No matching distribution found`）；未冒充 pytest 通過。管理者需在依賴齊備時執行完整 Python 測試。
- `claude --help`／`claude --version`：本機 **2.1.296**，確認 tools 空清單、strict MCP、setting sources、safe mode（保留 auth）及 no session persistence 旗標。未執行 `claude -p`。
- 已嘗試 `npx vercel --help` 及 `npx vercel deploy --help`（PowerShell 執行原則阻擋 ps1 後改用 npx.cmd）：npm registry 存取遭沙盒 **EACCES** 拒絕，offline cache 也沒有 CLI。因此無法驗證本機 Vercel CLI 版本；新專案做法改依 [官方 link 文件](https://vercel.com/docs/cli/link)及[官方 link 原始碼](https://github.com/vercel/vercel/blob/main/packages/cli/src/commands/link/index.ts)確認（ensureLink → setupAndLink → createProject），已在程式註解說明。
- `git diff --check`：通過。

尚待具備依賴的完整 pytest、實際首次建專案／部署、PyInstaller 與 iPhone Safari PWA 實機驗證。上述兩項 CLI／依賴限制不影響修正與測試檔案已完成。

本次 npm help 嘗試產生 `.cache/npm` 診斷檔；自動核准審查拒絕清理（`blocked by policy`），逐檔清理同樣未成功。這些是暫存產物，請勿提交。

# 先前驗證（2026-10-04）

環境：Windows、Python 3.13.7。只新增 `desktop/` 下的檔案；未執行 Claude、Vercel、git commit 或 push。

- `python -m compileall -q prank_news tests`：通過。
- `git diff --check`：通過；新增檔案尚未加入 git index。
- 暫存 `.smoke/offline_check.py` 的標準函式庫 unittest：8 個通過，涵蓋 prompt、正常／回退解析、markdown 清理、假 Claude runner、缺少 Claude、非法 JSON、建置素材與快取設定、長度驗證。這是部分離線檢查，**不是完整 pytest 結果**。
- `python -m pytest -q`／venv 的同一指令：無法執行，環境沒有 pytest。嘗試安裝 `requirements-dev.txt`，pip 連線遭沙盒 WinError 10013 阻擋；本機快取沒有完整依賴。
- 已嘗試 `python -m prank_news.cli --script-file .smoke/script.txt --name 測試 --out .smoke/app --template .smoke/template`（使用本地 venv、不部署），在載入依賴時因缺少 qrcode 而停止。edge-tts、mutagen 同樣未安裝；**未產生真實 MP3，也未驗證播放與實際音長**。

待具備依賴與網路的整合環境執行：

```powershell
cd desktop
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m prank_news.cli --script-file <UTF-8稿子.txt> --name 測試 --out <輸出資料夾>
```

PWA 範本尚未存在時，最後一行加 `--template <假範本資料夾>`。完整 pytest、真實 TTS／長文分段 MP3 播放、PyInstaller 打包、登入後首次 Vercel 建專案與部署，仍待整合驗證。測試本身不會使用網路或真的執行 CLI。
