# Automation Hub

Reusable Telegram Bot gateway for crawler/monitor plugins.

## Isolation rule

This package does not modify ZOFRI, ORDER, Container, TOWN or their Telegram logic. Existing services keep working independently. Aduana can use the Hub when a Hub bot is configured, and falls back to the legacy `ADUANA_TELEGRAM_BOT_TOKEN` path otherwise.

## Render settings

Required before adding a bot from the Hub UI:

- `AUTOMATION_MASTER_KEY`: one long random secret used to encrypt all Bot Tokens stored in TiDB. Do not change it after bots have been saved unless you plan to re-enter every token.
- `AUTOMATION_ADMIN_PASSWORD`: private Hub admin password. If absent, `ADUANA_ADMIN_PASSWORD` is used as a compatibility fallback.

Optional:

- `AUTOMATION_ADMIN_PREFIX` (default `/automation-hub-x7k9`)
- `AUTOMATION_PUBLIC_BASE_URL` (normally `RENDER_EXTERNAL_URL` already supplies this)

## Add a new Bot

1. Create the bot in BotFather.
2. Open the private Automation Hub admin page.
3. Enter a short Bot key, display name, select a registered plugin and paste the token.
4. Save. The Hub calls Telegram `getMe`, encrypts the token before TiDB storage, generates a webhook secret, and connects the webhook automatically.

## Add a future crawler plugin

The crawler keeps its own business tables and scan logic. To use the shared Bot Hub, register one Telegram update handler with `registry.register_lazy(...)`. Telegram token storage, webhook verification and BotFather token onboarding remain shared.

A single plugin can have more than one bot. Incoming replies are sent through the same bot that received the update; background notifications use the plugin's active default bot.
