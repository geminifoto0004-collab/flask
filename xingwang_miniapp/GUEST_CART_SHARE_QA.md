# XINGWANG SCANNER — Guest sharing and employee Home (2026-11-02)

Unslop methodology adapted from Damir Sokolovsky, CC BY 4.0.

## Current employee workflow
- In the employee **cart list**, each cart row has a Share SVG next to pencil/delete. Click it to open a small share sheet.
- Choose **WhatsApp**: backend creates an 8-hour cart-specific guest link and opens WhatsApp with the link and message already filled. Employee selects recipient and sends personally; no WhatsApp Business API needed.
- Choose **Copy**: link copied, with fallback copy dialog if clipboard is unavailable.
- Choose **QR**: the Scanner's own server creates the QR SVG using qrcode; no third-party QR service receives the secret. Render's actual build uses `xingwang_miniapp/requirements.txt`, so qrcode was added there.
- Generating a new link rotates the guest credential. Existing previously shared links become invalid; actions within the same share sheet reuse the generated link while it remains live in memory.
- The cart list's Home control uses an accessible house SVG to return to sample/stock main. Bottom Excel copy remains beside selected quantities.

## Security improvement
- On GET `/scanner/guest` **with an existing employee session**, the server renders a separate minimal information screen with a Home/Inicio SVG, without processing the guest token or deleting the employee's staff cookie. Staff can return to the sample/stock main without logging in again.
- On **a customer device** (no employee session), the guest page processes the 8-digit code, scrubs the fragment from browser history, and uses a cart-specific HttpOnly guest cookie. The staff list, staff notes, deletion and share APIs remain staff-only.
- Direct guest-login API still revokes an employee cookie if deliberately called; the safe staff-only GET interstitial prevents this happening as a side-effect of clicking the customer URL in an employee browser.
- Never hand an employee-authenticated browser to a customer. A bearer link allows its holder to use that one cart for its valid 8-hour window.

## Regression checks
- Static syntax, DOM IDs, local QR output, per-row share UI, and Home SVG are checked.
- Existing unit tests updated where old behavior required clearing staff credentials; new isolated tests added under `tests/test_cart_share_direct.py`.
- No real customer carts have been modified for testing. End-to-end browser, two-device access isolation, WhatsApp dispatch, and QR recognition still need real QA before claiming fully verified.

## Rollback
`backup/xw-share-list-home-20261102`.
