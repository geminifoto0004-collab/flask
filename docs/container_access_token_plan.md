Container Access Token Plan (Render + TiDB)
===========================================

Purpose
-------
Provide access control for the container UI without user accounts.
Token management is handled via a simple admin page backed by TiDB.

Decisions (Final)
-----------------
1. Single Render app only (container_app will be integrated into the existing app).
2. No user registration or login for container access.
3. Access via token URL: `/gate/<access_key>`.
4. After successful verification, redirect to `/container` (no token in URL).
5. Admin password stored in TiDB as plain text (per request).
6. Tokens support note, expiry, active/disabled, and max concurrent sessions.

Routes
------
User entry:
- GET `/gate/<access_key>` -> verify token, create session, set cookie, redirect `/container`
- GET `/container` -> show UI only if session valid
- POST `/container/access/heartbeat` -> update session heartbeat

Admin:
- GET `/container/access-admin` -> login screen
- POST `/container/access-admin/login` -> check admin password
- GET `/container/access-admin/tokens` -> list tokens
- POST `/container/access-admin/tokens` -> create token
- PUT `/container/access-admin/tokens/:id` -> update token
- DELETE `/container/access-admin/tokens/:id` -> delete token
- POST `/container/access-admin/tokens/:id/clear-sessions` -> force release

Tables (TiDB)
-------------
1) container_access_admin
- id (fixed 1)
- password (plain text)
- updated_at

2) container_access_tokens
- id
- token (unique)
- note (nullable)
- status (active/disabled)
- expires_at (nullable = never)
- max_concurrent (nullable = unlimited, 1 = single online)
- created_at
- last_used_at

3) container_access_sessions
- id
- token
- session_id
- last_heartbeat
- ip
- user_agent
- created_at

Token Rules
-----------
- Valid if: exists, status=active, not expired
- Concurrency:
  - max_concurrent is NULL -> unlimited
  - max_concurrent = 1 -> single online
  - max_concurrent = N -> allow up to N active sessions
- Active session is determined by last_heartbeat within timeout window

Admin Features
--------------
- Create token (with optional note, expiry, max_concurrent)
- Disable/enable token
- Delete token
- View current active sessions count
- Force release sessions

Open Config
-----------
- Session timeout minutes (admin-configurable later)
- Optional support for `?token=` as a fallback (not required)

