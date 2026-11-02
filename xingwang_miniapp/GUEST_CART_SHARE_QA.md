# SCANNER guest sharing & Excel copy / Unslop — 2026-11-01

## User workflow
1. Employee opens an existing cart in the staff scanner.
2. Staff: sticky lower center footer beside selected Rollos/SKU counts now contains the SVG **copy Excel** control (SKU + requested quantity in two tab-separated columns). The mobile copy button remains in the mobile detail pane.
3. Staff: right-side cart controls contain **Share with customer**; deliberately confirm generation. Backend `/scanner/api/cart/share` rotates an eight-digit access code (8h, previous link immediately invalid).
4. New link copied: `https://xingwang-stock.onrender.com/scanner/guest#v=<8-digit-code>`. The fragment is sent to the customer as a bearer credential and is removed from the address bar by the guest page before API requests. **Only share with the intended customer.**
5. The dedicated GET `/scanner/guest` clears the *staff* cookie using the same scoped cookie path, sets `Cache-Control: no-store` and Referrer-Policy. When the guest page loads it can only show a guest cart or guest login, never the staff cart list. Opening this route in a staff browser signs the staff user out.
6. Guest cart session uses existing cart-specific HttpOnly signed cookie and backend `_authorize`, which compares the requested `cart_id` to the guest's permitted `cart_id`. Staff list/admin, item notes, order notes, share, delete remain staff-only. Guest may edit quantities and confirm only that cart.
7. Browser history back-forward cache restore reloads the page and checks the current session again; old staff HTML is sent with `no-store`.

## Security tradeoffs
- Anyone possessing the valid 8-hour link can use that one cart for the remaining TTL; do not post it publicly.
- Opening a guest link on the employee's logged-in device logs that employee out; customers should use their own device. We do **not** provide a CSS-only "guest preview" on a staff session.
- Re-sharing rotates the guest credential and revokes the old link. The code is not stored in readable form in TiDB, so existing links cannot be recovered by the employee UI.
- This is customer *cart access*, not a customer-specific permanent account or multi-cart portal.

## Protected
- No change to TiDB schema, stock/confirmation and sample SAVE, camera parameters, cart quantity/role algorithms.
- Original employee cart list and desktop app remain unchanged except for export placement/share button.
- CSS avoided unnecessary `!important` overrides; mobile export access retained.

## Verification
- JS parse (cart JS and four inline blocks), 62 literal DOM IDs present exactly once.
- New backend guest GET clears staff cookie and sets no-store.
- Unit test file `xingwang_miniapp/tests/test_cart_guest_link_and_export.py` added; tests NOT executed here.
- Still must test private/incognito browser guest flow, actual API authorization for a wrong cart ID, responsive widths and screenshot parity with CC design preview; do not claim end-to-end verification from Render Live.

Rollback: `backup/xw-before-guest-link-and-copy-dock-20261101`.
Unslop methodology: adapted from Damir Sokolovsky under CC BY 4.0.
