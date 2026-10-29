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


## 2026-10-29: Original 0004 crawler management port

The branch now uses the **original XINGWANG login** template and **original
Automation Hub** page, original styles/sidebar, and registers the original
crawler-related blueprints in production mode (Aduana, Telegram Automation Hub,
containers, container Excel and monitor). It is *not* the standalone minimalist
setup UI. The old `/admin/setup` path redirects to `/admin/automation`.

The isolated server deliberately excludes ORDER share, ORDER tracking,
B2 order sync, Telegram ORDER links and unrelated public account registration.
The separate admin login accepts the same `SUPER_ADMIN_EMAIL` and
`SUPER_ADMIN_PASSWORD`; on the dedicated database it resolves the new
administrator's TiDB `user_id` for monitoring permissions.

Setup-mode `1` shows the original Automation Hub UI **read only** and avoids
all database connections. To use original functional administration on 0005:

1. Verify `CRAWLER_TIDB_URL` points to the **new 0005 TiDB instance** and
   database `xingwang_crawler`, not any 0004 ORDER database.
2. On **Render 0005 only**, set `CRAWLER_SETUP_MODE=0` and Save/Deploy.
   This mounts the real Automation Hub, Aduana, ITI/container and monitor routes.
3. Verify `/ping`, `/ready`, `/login` and `/admin/automation` using the
   existing login credentials, then check Aduana/containers and actual DB schema.
4. The new TiDB3 has fresh tables. It does **not** automatically contain the
   previous Aduana users, permissions, history, container data or Bot records.
   Recover those from the old database or re-register crawler Bot tokens after
   checking the actual source data. Never copy the complete ORDER database.
5. **Do not click Reconnect Webhook for a Bot on 0005 until cutover**.
   Telegram permits one webhook per Bot: switching would steal updates from 0004.
   During cutover, first verify new service and permissions, then reconnect the
   intended *crawler-only* Bot webhook, and redirect its cron-job.org schedules.
6. Do not change customer share links or `@XingwangOrderLinkBot`: those remain
   exclusively under 0004.

GitHub Actions CI installs real requirements and checks both setup mode and
the real crawler Blueprint route map (without contacting a real TiDB). Live TiDB
connection, row migration, original token data and Telegram delivery still need
a real end-to-end validation. The 0005 Render account must be connected separately
before ChatGPT can manage its environment variables directly.
