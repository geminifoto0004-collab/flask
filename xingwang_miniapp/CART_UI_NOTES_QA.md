# CART UI & NOTES — 2026-11-01

## Requirements implemented
- Staff and mobile both start on the cart list. No desktop auto-opening last cart, no staff ?cart= history state. Guest login remains independently scoped to the guest cart.
- Narrow desktop sidebar: customer name first in larger text, cart code and timestamp below; quantity, independent small status text, icon-only pencil and trash. Name editing is inline in the card. No customer edit/create modal.
- Wide cart list: use the same data hierarchy with side-by-side layout. Mobile retains swipe-right reveal of deletion button and eight-second undo.
- Staff may enter optional free-form cart notes (such as manual quoted unit prices, USD/MT, USD/YD, delivery terms) in the right column, capped at 1200 characters. Explicit save and unsaved-change protection on navigation.
- Notes use new isolated `xw_cart_notes` table and staff-only get/save APIs. No changes to stock, sample SAVE, cart confirmation, Excel 2-column copy, or guest payloads. Notes are not automatically interpreted as prices or totals.

## CSS cleanup
- Deleted 36 conflicting legacy cart-history rules; one canonical responsive component style remains, with no new !important in the cart-row rules.
- Previous 638 !important declarations reduced to 622 (some global legacy scanner rules remain, unrelated to this scope).
- Desktop right-side metadata panel scrolls within available viewport to keep longer notes reachable.

## Verification
- All JS (cart controller plus 4 inline blocks) parses.
- 60 literal cart DOM ID references exist once.
- No desktop auto-opening identifier, create prompt modal, or ?cart= writes remain in cart controller.
- No new database operations have been performed on live customer carts.
- Added no-TiDB tests in `tests/test_cart_note_and_layout.py`; **they have not been executed** in this connector session.

## Real-browser acceptance still required
- 390/428px mobile gestures and iPhone keyboard, desktop widths 1280/1440/1920; compare with CC design preview.
- Open list -> select -> inline edit -> switch back -> select again, confirm original name saved.
- Enter a note with several lines (including prices in USD/MT), save, change carts, return and verify. Try competing edits on two sessions; a stale revision must return HTTP 409.
- Edit/undo deletion on disposable test cart only.
- Verify camera, SKU search, selected quantities, Excel paste, stocktaking SAVE remain working.

Rollback: `backup/xw-before-cart-layout-notes-20261101`.

Unslop process adapted from Damir Sokolovsky, CC BY 4.0.
