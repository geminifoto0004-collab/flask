# Guest edge-swipe return anchor (2026-08-17)

Temporary office guest viewer only.

- Guest customer wall now stores the exact tapped order key, page scroll position, and card viewport offset before opening order detail.
- iOS/Android browser Back / edge-swipe restores that exact card instead of relying on browser automatic scroll restoration.
- The restored card receives a persistent red focus outline so the visitor can see which order was just opened.
- Restoration runs in several short passes to survive mobile browser BFCache / relayout timing.
- `sessionStorage` is only a fallback for the current browser tab; business/order/media lists are still freshly scanned by the server and are not restored from cache.
- The explicit `Volver a pedidos` link uses real browser history when a saved guest anchor exists, with its normal URL kept as a fallback.
