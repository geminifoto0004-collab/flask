# SCANNER — Web SKU request + notes / Unslop QA, 2026-11-01

## Clarified searches
- Left sidebar search: filters carts by customer name / cart code, labeled `客户 / Carritos`.
- Center search: looks up series/SKU and then filters returned SKU rows, labeled `系列编号 / Buscar SKU`.
- Neither QR scanning nor stock lookup has been removed.

## Per-SKU price notes
- Staff-only pencil adjacent to quantity for each SKU; inline input for `USD 1.80 / MT`, `USD 2.10 / YD`, or a short per-SKU instruction. Note preview appears beneath SKU.
- New `xw_cart_item_notes(cart_id,sku,note,version,updated_at)` table, created idempotently alongside existing cart schema. `/scanner/api/cart/item-notes` reads all notes once; `/scanner/api/cart/item-note/save` saves one SKU with a separate optimistic version.
- Existing cart-wide note retained but now described as order-level delivery/conditions. Notes remain internal to staff, never returned from guest cart `_load`.
- Inline editing saves on Enter / check, switching fields or navigating. Failed writes keep the editor open.

## Demand versus stock
- Cart is customer demand, **not inventory reservation**. Existing cap `qty > stock_rolls` removed from both individual item and batch mutation, while integers 0–9999, revision conflict check, cancellation guard and confirmation semantics remain.
- If requested 10 and reference stock is 2: quantity is 10, UI is red, shortage warning is `缺 8 / Faltan 8`.
- Unknown reference stock is shown as unknown (not silently zero).
- Excel copy still pastes SKU and requested qty into exactly two tab-delimited columns.

## UI cleanup
- Desktop SKU list uses continuous flat zebra rows with subtle separators instead of selected pink card collections.
- Removed about 27 old conflicting SKU/quantity CSS declarations; `!important` count 622 -> 590 across scanner stylesheet.
- Desktop only: duplicate title in center header and right-side opening/version/confirmation widgets hidden. Existing back/navigation and confirmation history code preserved.
- General notes and Excel copy remain visible in desktop right pane.
- Existing mobile layout kept as much as possible; actual iPhone QA still required.

## Available checks
- Cart JS and inline HTML JS parse in a JavaScript interpreter.
- All 60 literal `$('<id>')` DOM references resolve to HTML IDs.
- Source-level API permission checks and note version guards inspected.
- Added tests `tests/test_cart_stock_demand_and_sku_notes.py`; corrected obsolete old assertions which assumed stock cap and visible guest code.
- No real customer cart was modified to test shortage/notes.

## Not yet verified
- Authenticated 1280/1440/1920 browser screenshot/click sequence vs CC design-preview.
- Actual TiDB writes, SKU note concurrent edits in two browsers, real camera recognition, 390px iPhone keyboard and row layout, user Excel paste.
- Do not interpret Render's `Live` status as proof of these application operations.

Rollback: `backup/xw-before-sku-notes-stock-ui-20261101`.

Unslop methodology adapted from Damir Sokolovsky under CC BY 4.0.
