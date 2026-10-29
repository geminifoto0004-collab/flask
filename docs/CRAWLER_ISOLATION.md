# Crawler isolation — deployment checklist (not active until cutover)

The existing Render service `flask-393d` stays unchanged and keeps ORDER,
ORDER web shares, Telegram ORDER, China order-links and B2 metadata.

Deploy a **different** Render web service using this repository/branch,
start command:

```
gunicorn crawler_app:app --workers 1 --threads 2 --timeout 120
```

Required environment variables (do not copy the ORDER database URL):

- `CRAWLER_TIDB_URL`: dedicated *physical* TiDB Cloud Starter instance (e.g. TiDB3),
  MySQL URL including the database name, **never** an ORDER TiDB1/TiDB2 URL.
- `CRAWLER_SECRET_KEY`: new random 32+ character session key, separate from ORDER.
- `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD`: crawler admin login.
- `AUTOMATION_MASTER_KEY`: separate, persistent encryption key for crawler Telegram bots.
- Crawler-specific secrets: `ADUANA_CRON_SECRET`, `ADUANA_OWNER_TELEGRAM_ID`
  and whichever ZOFRI/ITI/container access keys are used.
- `AUTOMATION_PUBLIC_BASE_URL`: new crawler service HTTPS URL.

The entrypoint refuses to start without its dedicated TiDB URL and admin
credentials. It disables ORDER TiDB standby/failover and deliberately does
not mount ORDER /share, /tracking, /api/order-cloud or Telegram ORDER routes.

Before switching traffic:
1. Create the new dedicated TiDB Starter instance (current free quota and account
   constraints must be verified) and decide which crawler tables/history to
   migrate from current DB. Do not erase the original tables.
2. Deploy the dedicated crawler service and verify GET /ping and GET /ready.
3. Verify /api/aduana/health, ITI/container query and crawler ingestion with
   test data. Restore necessary webhook/access keys; register crawler-only bots.
4. Update *crawler-specific* local tools, cron-job.org jobs, Telegram crawler
   webhooks and client configuration to the new service URL. Keep ORDER URLs on
   flask-393d.
5. Confirm all crawler requests reach the new service; only then disable old
   crawler scheduled jobs/ingestion on the legacy flask-393d. Do not cut over
   midway or both services may write inconsistent data.

Caveat: The legacy flask-393d service still contains crawler routes until
a separately validated clean-up. Do not remove them prematurely. A separate
Render process alone is NOT a complete isolation if it uses the same TiDB instance
or shared cron endpoints. Render free services in one workspace share a 750
free instance-hour monthly allowance, so additional active services may need
careful cost/uptime planning.

No live environment variables, cron jobs, webhooks, existing data or customer
share links are changed by merging this preparatory code.
