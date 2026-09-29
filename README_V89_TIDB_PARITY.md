# ORDER V89 — TiDB parity and public image refresh

`1007742-1` 的兩張截圖是桌面版 SQLite 和客戶公開頁面的比較，尚不能單憑
畫面判定哪一個 TiDB 缺了圖片索引。在 Render 相同環境執行
`python scripts/tidb_order_parity.py 1007742`，可分別查兩庫的訂單、流程、
分享狀態和圖片索引，輸出不含分享 token 或密碼。

V89 停止背景對齊刪除「只存在備庫」的資料，並在複製 metadata 後清理
公開頁面快照與 HTML 快取。舊資料若原本就有分歧，程式只報告差異，
不會猜測某張圖片是漏同步或刻意刪除。確認來源後，由有原圖的桌面版
重新發布圖片；B2 已有相同物件時，V88 的流程只補 TiDB 索引，不重傳圖片。

The customer card for order `1007742-1` displayed the contract scan while the local
ORDER business attachments showed color sample images. Those screenshots compare a
local SQLite view with a public share; they do not by themselves identify which TiDB
is missing the asset. Run `python scripts/tidb_order_parity.py 1007742` in the Render
environment to compare the actual order, workflow, share and active image rows in
TiDB1 and TiDB2 without exposing tokens or passwords.

V89 changes background reconciliation in two ways:

- It no longer deletes a row present only on the standby. Such a row could be valid
  data written during an outage. It reports counts as `standby_only` for review.
- After metadata is copied, it clears derived customer snapshots and HTML on the
  destination and in the running process, so old public page cache cannot continue
  showing the former image list.

The two TiDB targets still receive normal `cloud_*` writes through the existing dual
writer, and V88's B2 HEAD reuse still avoids uploading an existing image twice.
An already diverged row that exists on only one TiDB is retained for review. Absence
alone cannot distinguish a missing write from an intentional deletion, so V89 never
blindly resurrects it. The local computer which has the original images should
perform an authenticated image refresh after the missing side's order/workflow is
synced; V88 will reuse the B2 object and register only metadata.
