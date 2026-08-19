# Cloud resource security / deployment gates

The shared `order_tracking` source code must never be treated as a secret. A copied source tree must **not** be enough to use company TiDB, Render publication, or Backblaze B2.

## Layer 1 — deployment feature gates (`config.py`)

- `TRACKING_DEPLOYMENT_PROFILE=CHINA|OVERSEAS`
- `TRACKING_LOCAL_GUEST_SHARING_ENABLED=0|1`
- `TRACKING_LOCAL_GUEST_PERMANENT_ENABLED=0|1`
- `TRACKING_CLOUD_RESOURCE_ACCESS_ENABLED=0|1` — master cloud gate, default OFF
- `TRACKING_TIDB_PROVIDER_ENABLED=0|1`
- `TRACKING_B2_PROVIDER_ENABLED=0|1`
- `TRACKING_RENDER_PUBLIC_GUEST_ENABLED=0|1`
- `TRACKING_PERMANENT_PUBLIC_GUEST_ENABLED=0|1`
- `TRACKING_PUBLIC_SHARE_PROVIDER_READY=0|1`
- `TRACKING_PUBLIC_SHARE_BACKGROUND_SYNC_ENABLED=0|1`

China deployments should keep the cloud master gate OFF. UI hiding is not authoritative; server routes and provider registration apply the same policy.

## Layer 2 — credentials stay outside this repository

Never put TiDB password/DSN, B2 Key ID/Application Key, Render secrets, or signing secrets in `config.py`, ZIP files, SQLite, JS, or templates. They belong in the controlled deployment environment/secret store only.

## Layer 3 — external hard kill

If a copy of the code or a machine is no longer trusted, revoke/rotate the external credentials:

1. Revoke/rotate the dedicated TiDB user/password (least privilege, separate from production admin credentials).
2. Revoke the dedicated B2 Application Key; scope it only to the customer-share bucket/prefix and required operations.
3. Rotate/remove Render environment secrets and redeploy the official service.
4. Leave `TRACKING_CLOUD_RESOURCE_ACCESS_ENABLED=0` until the official deployment is ready again.

This is the real kill switch. Someone who can edit Python can change a local `False` to `True`, but they cannot restore credentials that were revoked at TiDB/B2/Render.

## Public share provider boundary

The common package contains only a provider interface (`public_share_provider.py`). It contains no B2/TiDB client or credentials. An authorized overseas parent Flask deployment registers the provider. Permanent-share background refresh is a single low-priority daemon trigger and runs only when the provider-ready + background-sync gates are enabled.

## Permanent link freshness contract

A public provider implementing `sync_due_permanent_shares()` must treat the share row as a rule, not a frozen list of order IDs. For each permanent share it re-evaluates the customer's currently visible orders from `history_scope` + `include_cancelled`:

- unfinished orders remain visible;
- cancelled orders disappear when `include_cancelled=false`;
- `current` completed orders automatically leave after the current-window rule (currently 3 months);
- new orders and changed media are added incrementally;
- unchanged B2 objects are reused;
- the permanent customer URL/token does not change;
- obsolete B2 objects may be garbage-collected later instead of blocking the sync.

The shared background trigger uses one daemon thread only. The provider should itself remain incremental and low priority.
