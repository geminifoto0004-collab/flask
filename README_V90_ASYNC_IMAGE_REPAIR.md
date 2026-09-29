# ORDER V90: Sergio image repair after TiDB failover

這次日誌確認 Sergio 有 21 張圖片的 TiDB 索引缺失；`1007874-1` 桌面版的兩張
業務附件沒有出現在客戶頁面。V90 讓 Render 的訂單對齊先回應，再於背景掃 B2
並更新分享快照；桌面版只補缺失及新增的圖片。已在 B2 的圖片只補 TiDB 索引。
更新 Render 和桌面版後，請看日誌的 `targeted TiDB image repair` 是否包含
`1007874`，以及最終 `DONE direct-only ... failed=0`。未拿到正式資料庫連線，
目前無法宣稱這筆線上資料已修復完成。

Observed on 2026-09-29: the desktop had two visible business attachment images for
workflow `1007874-1`, while the public detail still showed the contract image. The
desktop log reported `missing_cached_assets=21` for `SERGIO CONDO COLQUE` and a
separate `customer/reconcile-orders` HTTP 502. The screenshots compare local SQLite
with a public share; they do not identify the missing TiDB by themselves.

Changes:

1. `customer/reconcile-orders` commits and responds before rebuilding the share
   snapshot. It schedules the derived snapshot refresh asynchronously. This removes
   the full B2 list from a 90-second control-plane request.
2. B2 metadata recovery runs on one background worker when a snapshot is built.
   A successful scan is eligible for another scan after five minutes, including when
   AUTO moves to the other TiDB. Newly recovered assets refresh the public snapshot.
3. The desktop image publisher selects only absent TiDB image keys and new local
   images when it finds drift. It logs affected order numbers, and performs B2
   existence probes in batches of five. If B2 already holds an object, it only
   registers the metadata; an empty targeted list never triggers a full scan.
4. The TiDB background mirror performs one startup pass, then avoids full table
   copying every five minutes while versions match. A dirty mirror still retries.

The V89 safety rule remains: standby-only metadata is retained and reported instead
of blindly deleted or resurrected. No production credentials are in this package.
Live confirmation requires the desktop `DONE direct-only ... failed=0` line and a
fresh public view of `1007874-1` after Render and desktop versions are both updated.
