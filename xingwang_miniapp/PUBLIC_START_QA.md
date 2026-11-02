# Public fixed QR → lazy customer cart (2026-11-02)

Unslop methodology adapted from Damir Sokolovsky under CC BY 4.0.

## What changed

- Staff cart list now has a permanent Start QR share control beside +. It opens the existing share sheet with WhatsApp composer, link copy, QR and SVG download. The URL is **/scanner/start** and has no guest code/cart ID; printing it does not create carts.
- The new public landing state is a section in the **existing scanner.html**, not a separate shopping cart HTML or duplicate catalog. A customer can scan a series QR with Html5Qrcode or type a SKU, see active stock-reference variants, and choose requested rolls.
- Simply loading /scanner/start or browsing SKUs does **not** create a cart. **First positive quantity** triggers one TiDB transaction that creates the cart, first item and audit event, then sets an 8-hour HttpOnly, Secure, SameSite=Lax **cart-scoped guest session**. All subsequent edits, confirmation and stock reference use the existing cart UI/API.
- Each browser/device gets a random signed, 30-minute HttpOnly start cookie; a HMAC hash is stored as the cart's start_hash on first selection. A retry with that ticket returns the existing cart; duplicate retries cannot create multiple carts. Reloading the start page reuses the ticket.
- Public lookup requires the start ticket and same-origin POST; existing query throttling applies. First SKU must be an active known SKU; requested qty can exceed stock, without changing/reserving stock.
- Durable TiDB public cart creation counters: 45 new carts/IP/hour and global 300/hour, plus occasional cleanup. IP is stored only as HMAC hash; creation rate limits are transactional across Render workers.
- Staff list shows guest-created carts and refreshes while the list is visible/idle every 90 seconds or on tab visibility return, not from continuous hot polling. Staff may add a customer name later.
- The previous per-cart share (8-hour code), Home, no-staff-list guest security and guest logout are unchanged.

## Privacy and operational notes

- The fixed QR is publicly shareable; it grants access to an empty SKU selection start state, **not an existing cart**. Never copy a customer-specific /scanner/guest#v= link onto a reusable printed QR.
- Different customer phones have isolated signed cookies and distinct carts. A physically shared browser intentionally resumes its own active guest cart; use private devices or exit the previous guest session before handing over a shared device.
- Rate-limited public search exposes only catalog SKU/stock reference data; customer names, staff notes, existing cart IDs, finance and the staff list are not in the response.
- The anonymous start token is kept only in an HttpOnly cookie; no value is added to the QR URL.
- Existing public QR is stable as long as the xingwang-stock.onrender.com domain is retained.

## Source QA

- JavaScript parse: scanner_cart.js and four HTML inline script blocks.
- DOM ID references: 84 linked JS IDs present once, no duplicates.
- New routes and role restrictions checked by source inspection.
- Added `xingwang_miniapp/tests/test_cart_public_start.py` for no-cart GET, independent tickets, query-only lookup and first positive add. **Automated tests are added but have not been executed in a running environment**.
- No real customer cart has been created or edited during this implementation.

## Real verification still required

1. Staff: open fixed QR share, show/download QR, open WhatsApp with prefilled text.
2. Incognito A: open /scanner/start, browse 12-225 (no new cart in staff list), then select one SKU at qty=10 and confirm new cart appears.
3. Incognito B on a different browser/device: open the same QR; no items from A, own fresh cart on first add.
4. Refresh A after selection: preserve its cart and requested qty. Existing guest-only cart privacy rules must reject B's cart ID.
5. Leave the start page without adding a SKU: no cart should be recorded.
6. Check 390px mobile camera, iPhone safe area, desk widths 1280/1440; no visual QA has been performed.
7. Check invalid ticket, invalid SKU and rate-limit responses without using real customer data.

Rollback: `backup/xw-before-public-qr-cart-20261102`.
