ORDER HOME V88 - reuse existing B2 image after TiDB switch

When cloud_assets is missing on the selected TiDB, the authenticated image
presign endpoint now checks the existing B2 object key (scoped and legacy)
on both configured B2 backends. A matching object is registered in TiDB and
reported as reused. Its bytes are not compressed or uploaded again.

Normal images with an existing TiDB row take the original fast path: zero B2
HEAD requests. A missing row incurs B2 HEAD requests; a confirmed 404 proceeds
to the normal upload path. If B2 cannot be checked, publication reports an
error instead of assuming that the image must be uploaded again.

The public share B2 recovery cache is keyed by TiDB target so an AUTO
failover within one server process can recover the same customer on TiDB2.
Permanent links and intentional image visibility still require the V87 TiDB
metadata mirror to be in sync. B2 image bytes alone do not encode either one.

No local ORDER SQLite schema change and no B2 image re-upload is needed.
