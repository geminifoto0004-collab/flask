# Aduana Monitor Blueprint

This module is intentionally isolated from the existing ZOFRI/ORDER code. It uses the parent FLASK application's existing database connection and is mounted as a child Blueprint.

## Admin integration

Aduana does not have a second admin login.

- Log in through the existing FLASK `/login` page.
- Open `/admin/automation` from the existing admin sidebar.
- Aduana management is at `/admin/automation/aduana`.
- Access uses the existing parent `logged_in` session and existing admin/super-admin roles.

## Render environment variables

Required for Aduana operation:

- `ADUANA_OWNER_TELEGRAM_ID`
- `ADUANA_CRON_SECRET`
- `AUTOMATION_MASTER_KEY` (required when storing BotFather tokens through Automation Hub)

Recommended Telegram setup:

- Add the Aduana Bot from `/admin/automation` and select plugin `ADUANA`.
- The Hub verifies the BotFather token, encrypts it in TiDB, creates a webhook secret and connects the generic webhook automatically.

Legacy compatibility only:

- `ADUANA_TELEGRAM_BOT_TOKEN`
- `ADUANA_TELEGRAM_WEBHOOK_SECRET`

Optional:

- `ADUANA_PUBLIC_BASE_URL` (otherwise `RENDER_EXTERNAL_URL` is used)
- `ADUANA_CRON_LOOKBACK_DAYS` (default `31`)
- `ADUANA_PERIOD_WORKERS` (default `4`, max `6`)
- `ADUANA_TARGET_WORKERS` (default `4`, max `6`)

## Endpoints

- Health: `/api/aduana/health`
- New Hub Telegram webhook: `/api/automation/telegram/<bot_key>/webhook`
- Legacy Telegram webhook: `/api/aduana/telegram/webhook`
- Daily cron: `/api/aduana/check-all`
- Admin: `/admin/automation/aduana`

The cron endpoint requires `X-Cron-Secret: <ADUANA_CRON_SECRET>` or `?secret=<ADUANA_CRON_SECRET>`.

## First setup

1. Deploy the existing FLASK Render service.
2. Set `AUTOMATION_MASTER_KEY`, `ADUANA_OWNER_TELEGRAM_ID` and `ADUANA_CRON_SECRET`.
3. Use the normal XINGWANG `/login`.
4. Open **自動化中心**, add the BotFather token and choose `ADUANA`.
5. Message that Bot with `/start`. The `ADUANA_OWNER_TELEGRAM_ID` account becomes OWNER automatically.
6. Point the scheduler/Cron Job at `/api/aduana/check-all` once per day.

Tables are created lazily in the same database already configured by the parent app.

## Monitoring rules

- External users only interact with Telegram.
- New users are `PENDING`; OWNER approves them in the admin console.
- USER manual-query limits: current month / 3 calendar months / 12 calendar months according to permission.
- OWNER may query arbitrary RUTs and years from 2011 to the present and may use `TODAS`.
- USER cannot use `TODAS` and can only manually query RUTs already added to their account.
- Daily monitoring is independent of manual-query permission and scans the recent rolling window (31 days by default).
- Duplicate subscriptions for the same `(RUT, Aduana)` share one scan target.
- A first complete successful scan establishes baseline and does not notify old records.
- A partial/request/parser failure never completes baseline and never persists partial records.
- Records and per-user notifications are separate. Telegram failures remain retryable; inactive users/monitors are marked `SKIPPED` rather than retried forever.
