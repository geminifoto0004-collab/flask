# SCANNER — Unslop camera / cart cleanup (2026-11-01)

## Scope

Only `xingwang_miniapp/scanner.html` and `scanner_cart.js` were modified. The server, TiDB schema, cart API, authentication API, and sample SAVE semantics were not changed.

## Removed instead of overlaid

- 57 empty CSS rules plus one now-empty media block.
- Old cart-camera fullscreen layout, duplicate camera search row styling, obsolete 145px video overrides, inactive reader placeholder art, and legacy cart-camera selector in the generic QR video rules.
- Staff-facing eight-hour visitor-code panel (including its extra swap/guest controls), obsolete staff-side share/handoff JS event handlers and associated CSS. The backend guest/authentication routes were deliberately retained to avoid invalidating existing access and data.
- Generic customer-name prompt modal for cart editing.

## Implemented

- Compact centered cart camera popup (bounded width and height). No duplicate QR/SKU search bar while the cart camera is open; the existing cart SKU search remains available when the camera closes.
- Camera close releases the running camera; successful cart lookup also closes the cart camera resource.
- Inline customer name editor in the cart's right column, using the existing `/scanner/api/cart/name` endpoint with original revision/concurrency handling.
- Camera decode remains `fps:10, qrbox:{width:220,height:220}`. The sample scanning and SAVE endpoints are unchanged.

## Static checks

- Both JS source files (main inline scripts and cart controller) compile; all 56 literal `$('<id>')` references in cart JS have matching HTML IDs.
- CSS empty rules: 0.
- Before: ~94,747 embedded CSS characters; after: ~91,658 (about 3.1K removed), while `!important` occurrences went from 636 to 634.
- Cart JS: 28,580 -> 27,526 characters.
- Prior local baseline Python camera/cart tests 18/18 pass but **were run against an earlier checkout**, so do not count as verification of this commit.

## Still requires actual application / browser QA

- Real `scanner.html` and `scanner_cart.js` with API responses intercepted at the network layer, no DOM injection.
- Desktop camera at 1280, 1440, 1920 widths; mobile at 390 and 768.
- Camera permission, QR recognition and continuous sample scanning on actual hardware.
- Right-column name save and concurrency behavior with real authenticated session, without production test writes.
- Screenshots and design-preview comparison per CC `XW_REAL_QA.md`. Do not assert pixel parity based on static checks alone.

## Rollback

Branch: `backup/xw-before-camera-cleanup-20261101`.
