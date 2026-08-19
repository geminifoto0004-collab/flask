# Guest Report Background Queue (2026-08-17)

Temporary office guest links no longer generate PDF/HTML synchronously from a download link.

## UX
- Guest page asynchronously estimates approximate output MB, render-time range, and PDF-page count.
- "Preparar informe PDF / HTML" creates a background job and immediately returns control to the page.
- The customer can keep scrolling/swiping orders or enter an order detail while the report runs.
- Active job IDs are kept in sessionStorage so the floating queue follows between the guest customer wall and guest order detail.
- Completion is announced in-page (plus short vibration when supported).
- Completed files expose **Open first** (inline) and **Download** as separate actions. No automatic download occurs.

## Security
- Every estimate/create/poll/file request revalidates the temporary guest token and exact report permission.
- Report jobs are bound to `token_hash + customer_name + format` and are never exposed through the authenticated internal report download route.
- File serving revalidates the token before reading the cached report file.
- Expired/revoked links cannot fetch completed cached report bytes.

## Performance
- Guest report work shares the existing bounded customer-report executor, so large PDF attachments do not block the request thread or create unlimited CPU workers.
- Estimates are approximate. PDF-page count is scanned without rendering pages; the expensive conversion happens only in the worker.
