# 媒體預覽快取：資料永遠重新掃描 + 有上限的預覽 Cache

更新日期：2026-08-17

## 目標

- 新增 / 刪除 / 替換圖片或 PDF 後，再次進頁面一定以目前 SQLite 與目前實際檔案為準。
- 不快取「客戶有哪些訂單」或「訂單有哪些附件」這類業務清單。
- 只快取可重新產生的圖片縮圖與 PDF 頁 JPEG。
- PDF 第一次遇到時，先準備每份檔案第 1 頁，再由背景 worker 繼續準備第 2 頁直到最後一頁。
- Guest 客戶牆列出目前所有圖片 / PDF 頁，但瀏覽器只先下載第一張與使用者滑到附近的頁。

## Freshness 規則

每次重新進入客戶頁 / 訂單頁：

1. 重新查 SQLite 附件列表。
2. 重新 resolve 實際來源檔案。
3. 以 source file 的 `mtime_ns + ctime_ns + size` 產生版本碼。
4. 預覽 URL 帶 `v=<version>`，同一 DB row 若來源檔案被替換，瀏覽器 URL 也會不同。
5. 前端 media list Map 只做「正在請求中的 dedupe」，請求完成後立即移除，不保留舊附件清單。

所以 Cache 不能讓新附件進不來，也不能把已刪除附件重新顯示。

## Disk Cache

位置：`DATA_DIR/cache/media_previews`

預設：

- 上限 3 GB
- 14 天未使用自動淘汰
- 超過 3 GB 時依最後使用時間 LRU 刪最舊項目，回收到約 90% 上限
- 只刪可重新生成的 `.jpg` / page-count cache，不碰原始 JPG、PDF、tracking.db

可用環境變數調整：

- `TRACKING_MEDIA_CACHE_MAX_BYTES`
- `TRACKING_MEDIA_CACHE_RETENTION_DAYS`
- `TRACKING_MEDIA_CACHE_CLEANUP_INTERVAL_SECONDS`
- `TRACKING_MEDIA_PREVIEW_WORKERS`

## Guest Browser Cache

Guest HTML / 訂單與附件清單仍是 `no-store`。

圖片 / PDF 頁因 URL 已帶 source version，可由客戶瀏覽器 private cache 到該臨時 Token 的到期時間，以減少同一個時效內重複傳輸。
