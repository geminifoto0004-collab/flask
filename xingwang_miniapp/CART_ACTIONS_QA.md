# XINGWANG SCANNER — cart actions QA (2026-11-01)

## Changes

- Staff cart history row: the pencil/status button edits customer name *inline on that row* using the existing revision-checked `/scanner/api/cart/name` endpoint.
- Desktop: each cart row has a separate SVG trash button.
- Mobile <=949px: swipe the cart row **right** to reveal the trash button on the left. A swipe does not delete; tapping the revealed button does.
- Delete: `POST /scanner/api/cart/delete` (staff-only) changes state to `cancelled` with optimistic revision check, revokes old guest token, and leaves items, events, confirmation versions and quantity history intact. Active carts are filtered from `/scanner/api/cart/list`.
- Undo: `POST /scanner/api/cart/undo-delete` (staff-only), uses the new row revision and server-enforced 8-second expiry. Restores original `open`/`ready` status. After 8 seconds returns HTTP 410; no hard delete ever runs.
- Idempotent TiDB `_CART_COLUMNS` migration for `deleted_prev_state` and `deleted_until` (per usual existing automatic column migration).
- Sidebar: removed duplicate customer editor and manual refresh button; existing revision-conflict reload code remains for recovery.
- Copy: only selected items in **two tab-separated columns**, `SKU<TAB>qty` and one SKU per line, with no cart ID, title or customer name mixed in. Toast includes number of SKU rows.

## Manual QA (do not use live customer data as a deletion test)

1. On a disposable test cart, click the pencil next to the status. Change the customer name; Enter or ✓ must persist. Switching carts must display the saved name.
2. At 1920/1440/1280px: check trash buttons on all rows, including empty carts and confirmed carts.
3. At 390/428px: swipe a row **right**; delete icon appears. Swipe left to close. Scrolling vertically and tapping the row must not delete.
4. Delete disposable cart; verify row disappears, undo toast stays visible for eight seconds. Undo within eight seconds restores the cart and its original state, items and confirmation versions. Verify undo after nine seconds fails server-side.
5. On two sessions, make one edit, then try to delete the stale revision: HTTP 409, no lost data.
6. Copy a cart with multiple selected SKUs; paste into Excel. It must create exactly two columns, with one row per selected SKU; selected count in toast should match row count.
7. Confirm SAMPLE scanning, camera open/close, stock queries, guest restrictions and existing cart SAVE still work.

## Verification completed

- JavaScript parses (cart controller and all four inline scripts).
- Every literal cart JS DOM id is found exactly once; no orphan elements from removed sidebar controls.
- New transaction endpoints are staff-only; data deletion is a tombstone without `DELETE FROM xw_carts`.
- Added no-TiDB tests under `xingwang_miniapp/tests/test_cart_delete_undo.py`.

**Not yet claimed:** authenticated end-to-end browser run, mobile gesture on real phone, actual TiDB transaction test or complete CC design screenshot parity. These must be checked before treating the feature as fully accepted.

Rollback branch: `backup/xw-before-cart-actions-20261101`.
