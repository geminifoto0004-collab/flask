# V87 - TiDB1/TiDB2 dual mirror + failover

## Goal
TiDB1 and TiDB2 may be switched without losing ORDER text, customer share links, or B2 image metadata.
B2 image bytes are not duplicated; both TiDB targets keep the same object metadata.

## Changes
- `DB_TARGET=TIDB1|TIDB2|AUTO` (AUTO prefers TiDB1 and falls back to TiDB2).
- ORDER `cloud_*` writes are mirrored to the other TiDB in the same transaction when reachable.
- Unrelated Flask tables are NOT dual-written; this avoids auto-increment/id divergence.
- A mirror marker records which TiDB has the newest successful ORDER cloud writes.
- Background repair reconciles the known ORDER cloud tables, including missing rows, schema columns, and deletes.
- Existing TiDB1/TiDB2 drift is repaired on startup; after a standby outage, repair retries automatically.
- The dedicated `order_tracking` full SQLite mirror dual-writes its full-mirror mutations to both TiDBs.
- If the dedicated ORDER mirror hashes differ while both TiDBs are reachable, the existing desktop full-mirror uploader is forced to resend the current snapshot, healing both sides.
- Existing B2 -> `cloud_assets` recovery remains unchanged as an additional safety layer.

## Important behavior
If the standby is down, the selected TiDB continues working. When the standby comes back, the newer mirror marker decides repair direction, so an old TiDB does not overwrite the newer failover data.
