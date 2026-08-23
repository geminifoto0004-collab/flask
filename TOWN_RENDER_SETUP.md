# CUSTOMS AGENT TOWN — Dedicated Render Service

The AI town is intentionally separated from the main Flask Render service.
Both services may use the same GitHub repository, but they start different app
entry points and therefore load different code.

## Create the new Render Web Service

Use the same GitHub repository and configure:

- Build Command: `pip install -r requirements-town.txt`
- Start Command: `gunicorn town_app:app`
- Health Check Path: `/health`

Opening the new service root redirects to `/customs-town`.

`requirements-town.txt` intentionally omits ORDER, Playwright, B2, report/PDF,
pandas and other main-service dependencies so the dedicated town build stays
small and isolated.

## Required environment variables

Set secrets only in Render Environment settings. Do not commit secret values.

- `DEEPSEEK_API_KEY`
- `TOWN_ADMIN_PASSWORD`
- `TOWN_SECRET_KEY` (recommended; stable Flask session secret)

For TiDB, use either a single connection URL:

- `DATABASE_TYPE=tidb`
- `DATABASE_URL=mysql://USER:PASSWORD@HOST:4000/DATABASE?ssl_mode=REQUIRED`

or the split variables already supported by the repository:

- `DATABASE_TYPE=tidb`
- `DB_HOST`
- `DB_PORT` (normally `4000`)
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`

`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and
`MYSQL_DATABASE` are also supported aliases.

## Isolation guarantee

`town_app.py` sets `TOWN_STANDALONE_SERVICE=1` before importing the town
modules. In this mode `blueprints/__init__.py` does not import the main-service
user/B2 blueprints. The dedicated town process therefore does not mount ORDER,
crawler jobs, B2 helpers, container services, or the main authorization app.

The main Render continues using `app.py` and does not import/install/register
any town runtime.

## Current town runtime

The standalone entry uses the last stable town runtime chain: world state,
profiles, shifts, generic entities, relationships, scenes, TiDB world/dialogue,
admin commands, and the existing browser patches.

Experimental universal-action modules remain in the repository but are not
loaded by `town_app.py` yet. They can be re-enabled after isolated testing on
the dedicated Render service without risking the main Flask service.
