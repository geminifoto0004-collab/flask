# WEB Customer Share Admin (2026-08-18)

## Scope
Desktop WEB/Admin only. Mobile UI, mobile report sheet, mobile guest-link UI and mobile navigation were intentionally not redesigned.

## Desktop UX
- Existing create-share modal remains the creation workflow.
- Selecting a customer warns when active shares already exist; multiple shares per customer remain allowed.
- The modal's `有效分享` tab is now a compact quick view: max 12 recent rows, `详细` expands URL/QR on demand, and `管理全部分享` opens the full management page.
- All desktop share actions use normal button hover/cursor behavior; revoke actions are explicit danger buttons.

## Full management page
Route: `/tracking/admin/customer-shares` (ADMIN only)

Features:
- summary counters: active, permanent, expiring within 24h, LAN active, WEB active
- customer/creator/share-id search
- LAN/WEB, active/expired/revoked, temporary/permanent filters
- sort by newest, expiry, customer, access count
- pagination (30 rows per page)
- detail drawer with QR, URL, one-click copy/open, settings, access count and last access
- revoke from list or detail without deleting history

## APIs
- `GET /tracking/api/admin/customer-shares`
- `GET /tracking/api/admin/customer-shares/<mode>/<share_id>`
- Existing LAN/WEB revoke APIs remain the mutation endpoints.
- Active-link quick lists support `?compact=1` so bulk payloads do not carry QR/base64 or raw URLs.

## Database migration
`ensure_local_guest_link_tables()` safely adds `share_url` / `qr_data_uri` when missing.
`ensure_public_guest_share_registry()` safely creates/upgrades the local Render-share management mirror. It stores management metadata only, not provider credentials.

## Legacy limitation
Old LAN links created before URL retention cannot have their raw token reconstructed from the SHA-256 token hash. They remain revocable and visible as records, but URL/QR detail may require creating a new share.

## LAN URL host
When an admin opens Flask through `127.0.0.1`/`localhost`, newly generated LAN links try to use the machine's LAN IPv4 instead. An explicit `TRACKING_LOCAL_GUEST_BASE_URL` environment/app config value overrides auto-detection.
