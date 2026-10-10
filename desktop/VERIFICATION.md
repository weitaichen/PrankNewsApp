# 本次驗證（2026-10-04）

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
