# Aduana Monitor Blueprint

This module is intentionally isolated from the existing ZOFRI/ORDER code. It uses the parent FLASK application's existing database connection and is mounted as a child Blueprint.

## Render environment variables

Required:

- `ADUANA_TELEGRAM_BOT_TOKEN`
- `ADUANA_TELEGRAM_WEBHOOK_SECRET`
- `ADUANA_OWNER_TELEGRAM_ID`
- `ADUANA_CRON_SECRET`
- `ADUANA_ADMIN_PASSWORD`

Optional:

- `ADUANA_ADMIN_PREFIX` (default `/aduana-admin-x7k9`)
- `ADUANA_PUBLIC_BASE_URL` (otherwise `RENDER_EXTERNAL_URL` is used)
- `ADUANA_CRON_LOOKBACK_DAYS` (default `31`)
- `ADUANA_PERIOD_WORKERS` (default `4`, max `6`)
- `ADUANA_TARGET_WORKERS` (default `4`, max `6`)

## Endpoints

- Health: `/api/aduana/health`
- Telegram webhook: `/api/aduana/telegram/webhook`
- Daily cron: `/api/aduana/check-all`
- Private admin: value of `ADUANA_ADMIN_PREFIX`

The Telegram webhook rejects requests unless Telegram supplies the configured secret token. The cron endpoint requires `X-Cron-Secret: <ADUANA_CRON_SECRET>` or `?secret=<ADUANA_CRON_SECRET>`.

## First setup

1. Deploy the existing FLASK Render service with the environment variables above.
2. Open the private admin path and log in with `ADUANA_ADMIN_PASSWORD`.
3. Use **Conectar webhook** once (requires a public base URL).
4. Message the Bot with `/start`. The `ADUANA_OWNER_TELEGRAM_ID` account becomes OWNER automatically.
5. Point the existing scheduler/Cron Job at `/api/aduana/check-all` once per day.

Tables are created lazily on the first Aduana request in the same database already configured by the parent app.

## Monitoring rules

- External users only interact with Telegram.
- New users are `PENDING`; OWNER approves them in the private panel.
- USER manual-query limits: current month / 3 calendar months / 12 calendar months according to permission.
- OWNER may query arbitrary RUTs and years from 2011 to the present and may use `TODAS`.
- USER cannot use `TODAS` and can only manually query RUTs already added to their account.
- Daily monitoring is independent of manual-query permission and scans the recent rolling window (31 days by default).
- Duplicate subscriptions for the same `(RUT, Aduana)` share one scan target.
- A first complete successful scan establishes baseline and does not notify old records.
- A partial/request/parser failure never completes baseline and never persists partial records.
- Records and per-user notifications are separate. Telegram failures remain retryable; inactive users/monitors are marked `SKIPPED` rather than retried forever.
