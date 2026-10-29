# Crawler isolation — safe Render 0005 deployment

The existing ORDER site `flask-393d` stays on Render 0004. This separate
service on Render 0005 uses `crawler_app:app` from branch
`isolation/crawler-service-20261029`.

## Phase 1 — create Render 0005 before TiDB3 exists

Use:
- Repository: `geminifoto0004-collab/flask`
- Branch: `isolation/crawler-service-20261029`
- Build: `pip install -r requirements.txt`
- Start: `gunicorn crawler_app:app --workers 1 --threads 2 --timeout 120`
- Plan: Free

**`CRAWLER_SETUP_MODE` defaults to `1`**: only a secure login and
authenticated setup page run; no crawler bot, ORDER sharing or TiDB access.

Copy the following *variable names and existing values* from 0004 into
Render 0005 via Render's Environment dashboard:
- `SUPER_ADMIN_EMAIL` — existing admin email
- `SUPER_ADMIN_PASSWORD` — existing admin password
- `SECRET_KEY` — a stable secret of at least 32 characters

The independent crawler accepts the old `SECRET_KEY` name, so there is no need
to invent a new `CRAWLER_SECRET_KEY`. You may use a different 32+ character
value for stronger isolation; the **login password can remain the same**.
For safety, neither the program nor this document logs credentials.

If the above three are not set, `GET /ping` still returns 200 but login
is disabled (no hardcoded or default accounts).
`GET /ready` deliberately returns 503 until TiDB is configured.

Open `https://<new-render-service>/login`; after login, `/admin/setup`
displays status. Telegram and crawler endpoints are blocked in setup mode.

Render/GitHub tools do **not** reveal existing secret values. Do not copy
ORDER's `DATABASE_URL`, `TIDB1_URL`, `TIDB2_*`, Bot tokens or secret
group identifiers into an insecure place or chat.

The `AUTOMATION_MASTER_KEY` is only needed when later registering or
migrating crawler Bot token records. If copying *already encrypted* Bot
records, reuse the original matching key, otherwise an independent key may
be generated and retained in Render 0005.

## Phase 2 — configure independent crawler TiDB3

Create a **new physical TiDB Starter instance** that is not ORDER TiDB1/2.
Set `CRAWLER_TIDB_URL` using that instance's MySQL connection URL.
The service does not fall back to ORDER DB and disables TiDB failover/mirroring.
Do not yet change `CRAWLER_SETUP_MODE`.

Next migrate the relevant crawler tables and data (without the ORDER tables),
Telegram crawler Bot registrations, authorizations and worker settings.
Ensure the crawler-only Bot has no ORDER_SHARES plugin.

After validating schema migration and credentials, change
`CRAWLER_SETUP_MODE` to `0` and deploy. Verify:
- `GET /ping` — process available
- `GET /ready` — database reachable
- `GET /api/aduana/health` — crawler app health
- Telegram crawler webhook and ITI/container crawler queries
- /share/* and /tracking remain unavailable on crawler

Finally, and only after real tests, move the relevant cron-job.org URLs,
Bot webhooks and the local crawler connections to Render 0005. Keep
Telegram ORDER and customer share URLs on Render 0004.

## Limits / caveats

Sharing the GitHub account or repository does not share runtime memory or
database RU. Sharing the **same physical TiDB** would defeat RU isolation.

Render free instance-hour allocation is workspace-wide. Render 0005 needs
its own connected account/workspace to change service variables programmatically.
For now, the user can set them via their Render dashboard.

Nothing in this branch changes Render 0004, TiDB data, webhook URLs or cron jobs
until an explicit production cutover is performed.
