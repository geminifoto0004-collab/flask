# Automation Hub

Reusable Telegram Bot gateway for crawler/monitor plugins inside the existing XINGWANG FLASK admin console.

## Isolation rule

This package does not replace or modify the business logic of ZOFRI, ORDER, Container, TOWN or their existing Telegram flows. Existing services keep working independently. Aduana can use the Hub when a Hub bot is configured, and keeps the legacy `ADUANA_TELEGRAM_BOT_TOKEN` path only as a compatibility fallback.

## Authentication

There is no second Automation Hub login and no second admin password.

- Use the existing FLASK `/login` page.
- Only the existing `admin` / super-admin roles may open the Hub.
- Hub page: `/admin/automation`
- Aduana management: `/admin/automation/aduana`

The existing parent session (`logged_in`, `role`) is the single source of admin authentication.

## Render setting

Required before saving BotFather tokens from the UI:

- `AUTOMATION_MASTER_KEY`: one long random secret used to encrypt all Bot Tokens stored in TiDB. Do not change it after bots have been saved unless you plan to re-enter every token.

Optional:

- `AUTOMATION_PUBLIC_BASE_URL` (normally `RENDER_EXTERNAL_URL` already supplies this)

No `AUTOMATION_ADMIN_PASSWORD` is required.

## Add a new Bot

1. Create the bot in BotFather.
2. Log in through the normal XINGWANG `/login` page.
3. Open **自動化中心** from the existing admin sidebar.
4. Enter a short Bot key, display name, select a registered plugin and paste the token.
5. Save. The Hub calls Telegram `getMe`, encrypts the token before TiDB storage, generates a webhook secret, and connects the webhook automatically.

## Add a future crawler plugin

The crawler keeps its own business tables and scan/change logic. To use the shared Bot Hub, register one Telegram update handler with `registry.register_lazy(...)`, optionally with an `admin_path` under `/admin/automation/...`.

Telegram token storage, webhook verification and BotFather token onboarding remain shared. A single plugin can have more than one bot. Incoming replies are sent through the same bot that received the update; background notifications use the plugin's active default bot.
