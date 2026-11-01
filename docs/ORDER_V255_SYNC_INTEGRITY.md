# ORDER V255 sync integrity

Windows/Access and a real RU-exhaustion failover have not been tested. Do not present unit tests as that acceptance. The client packages document the two pre-existing robot UI ratchet failures.

## Changes

- A signed, read-only, host-bound desktop link grant is issued only after the existing authenticated cloud-admin CSRF confirmation. It expires after one year and is saved outside the release directory under the local user's app-data directory. No TiDB credentials are sent to the desktop. Subsequent registry refreshes retrieve links automatically, coalesced for five minutes. Header grants never appear in request URLs.
- A paired desktop can request bounded background replica verification. GET polls read memory. Verification includes customer-safe cloud tables, composite per-order share permissions, actual full ORDER table contents and schema, and the locally generated per-table content manifest when supplied. Numeric, NULL and binary values are canonicalized across SQLite/TiDB.
- Failed/absent/different/changed-during-check results do not certify a complete snapshot. Incoming local changes invalidate old desktop receipts. Successful uploads alone are not verification.
- Standby promotion requires fresh verified evidence. Connection SQL preflight catches quota failures before transactions; known quota failures have a 60-second circuit breaker. A failed or ambiguous transaction is never replayed on another database. No consensus/RPO-zero guarantee is asserted: real failure acceptance remains required.
- Every primary cloud write invalidates verification. ORDER mirror writes invalidate it too. The last successful writer remains preferred in-process. Following a process restart, evidence is unverified until a fresh check; an unconfirmed standby fails closed.
- Replica repair now upserts only differing rows. It includes cloud_share_order_visibility with a composite key. Repair is invalidated before copying and refuses a source version change; the stream marker is copied last. Standby-only rows are retained and reported, never silently deleted or certified as identical.
- Continuous dirty writes are coalesced with a minimum five-minute repair interval. Idle checks use stream markers to renew existing evidence when no write was observed. Derived caches are not treated as business data.
- One-click progress shows actual customer/image counts. Image wait and operation checkpoint deadlines request cooperative cancellation and retain resource locks until cleanup; no process safety rule is weakened. A caught pipeline failure now produces a failed worker history entry.
- The final one-click stage checks public share manifests, the authenticated ORDER mirror and both TiDB targets. Missing customer names remain explicit local-data warnings. It does not fabricate customer identities. The ordinary image pass verifies TiDB registrations; physical B2 deep checks retain their separate existing action.

## Configuration

The deployed active database was observed to be TiDB2 before this change. Preserve that explicit preference while enabling the existing mirror/failover switches. Both credential sets must already be configured; this change neither invents credentials nor changes spending limits. The health endpoint exposes only safe target names/configured flags and cached verification state.

## Validation

Targeted local suite: 19 passed. Cloud-only suite: 12 passed. Includes fail-closed promotion, late verification invalidation, no ambiguous write replay, composite permission rows, changed-only writes, grant validation and scoped API access, canonical numeric/binary/NULL comparison, skipped-order results and failed task history.

Official quota behavior: https://docs.pingcap.com/tidbcloud/serverless-limitations/ — new connections can be denied at quota while established connections are throttled. Application preflight is not proof that a real exhaustion failover has been exercised.
