# ORDER SQLite / TiDB dual mode

- Local ORDER remains SQLite and is never modified by the vendor script.
- The copied Render version uses TiDB only when TRACKING_CLOUD_MODE is enabled.
- Cloud mode never falls back to Render-local SQLite.
- Render remains read-only; official business writes stay on local ORDER.
