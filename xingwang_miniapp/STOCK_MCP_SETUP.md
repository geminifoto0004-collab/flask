# XINGWANG STOCK MCP — isolated development branch

**Branch:** `feature/xingwang-stock-mcp-v1`  
**Base:** `xingwang-telegram-miniapp-v1` (Telegram V23)  
**Production deployment status:** NOT DEPLOYED.  
**Default:** `XW_STOCK_MCP_ENABLED` absent -> no MCP endpoint.

## Implemented on Render branch
- OAuth-protected MCP Python SDK resource server at `/mcp`, when explicitly enabled.
- Exactly one tool: `search_stock(product_code)`, read-only.
- A distinct `stock_mcp` WebSocket operation for the paired local Windows worker.
- The existing Telegram `POST /api/query`, its `init_data` contract and `/bridge` authentication remain unchanged.
- RFC 9728 protected-resource discovery is hosted by the MCP SDK.
- Strict JWT check: RS256 signature against trusted issuer JWKS, exact issuer, audience, expiry/iat, `stock:read` scope, and an explicit subject allowlist.
- Authentication only protects stock data when configured; plugin visibility PRIVATE is not a substitute.
- No secrets committed.

## Auth0 tenant confirmed (2026-10-13)

Public issuer metadata and signing keys were checked using GitHub Actions. No
credentials, login tokens, management API access or user account information
were used in this test.

| Render variable | Value |
| --- | --- |
| `XW_STOCK_OAUTH_ISSUER` | `https://dev-a7e4fupofgtxlva0.us.auth0.com/` |
| `XW_STOCK_OAUTH_JWKS_URI` | `https://dev-a7e4fupofgtxlva0.us.auth0.com/.well-known/jwks.json` |
| `XW_STOCK_OAUTH_AUDIENCE` | `https://xingwang-stock-miniapp.onrender.com/mcp` |
| `XW_STOCK_ALLOWED_SUBJECTS` | **Must be copied from Auth0 User Management → Users → authorized user → User ID**, using exact `auth0|...` format; do not guess |
| `XW_STOCK_MCP_ENABLED` | **Do not set to 1** until OAuth integration, V24 Windows worker installation and end-to-end tests |

The Auth0 role `XINGWANG STOCK ADMIN` should be directly assigned to the
authorized user and must contain only `stock:read`. The Auth0 API Identifier
is the canonical MCP URL above. RBAC and Add Permissions in Access Token must
be enabled. Under tenant Settings → Advanced, Resource Parameter Compatibility
Profile ON, CIMD ON, DCR OFF, pending connection testing.

**Do not paste Access Tokens, Client Secrets, Auth0 Management Tokens,
passwords, or BRIDGE_SHARED_SECRET into chat or git.** The User ID is not a
secret, but is account-specific, and should be stored only in Render environment.

The public Auth0 OIDC/JWKS verification is **not** an OAuth login test.
The full ChatGPT client CIMD registration path may need adjustment if Auth0
rejects the client metadata (some tenants have reported `invalid_client_metadata`);
do not turn on unrestricted DCR merely to skip that error.

## Required OAuth provider setup (not yet done)
Use an established OAuth authorization server supporting MCP and **Authorization Code + PKCE S256**, ChatGPT CIMD or DCR, and RFC 8707 `resource` parameter (e.g. Auth0 Auth for MCP). Do not send login credentials or bearer tokens in a chat.

Create an API Resource Identifier exactly:
`https://xingwang-stock-miniapp.onrender.com/mcp`

Create scope `stock:read`. Configure the identity provider to issue signed JWT access tokens with:
- `iss` = your configured HTTPS issuer
- `aud` = exact `/mcp` resource URL above
- `scope` includes `stock:read`
- stable `sub` for the permitted user, with `exp` and `iat`
- keys discoverable at a trusted same-host JWKS URI

**Auth0 note:** When relying on OAuth resource parameter rather than nonstandard `audience`, enable Auth0's Resource Parameter Compatibility Profile in tenant settings. Enable CIMD or DCR for ChatGPT and allow the exact registered ChatGPT callback; do not guess redirect URIs. Configure authorization only for your identity and verified accounts.

For a test deployment, set these **in Render Dashboard / Environment, not in Git**:
- `XW_STOCK_MCP_ENABLED=1` (ONLY after all other integration prerequisites are ready)
- `XW_STOCK_OAUTH_ISSUER=https://<your-tenant-auth-domain>/`
- `XW_STOCK_OAUTH_JWKS_URI=https://<same-host>/.well-known/jwks.json` (actual tenant JWKS path)
- `XW_STOCK_OAUTH_AUDIENCE=https://xingwang-stock-miniapp.onrender.com/mcp`
- `XW_STOCK_ALLOWED_SUBJECTS=<authorized-subject-from-provider>` (comma-separated, NEVER email guess)

The required `BRIDGE_SHARED_SECRET` stays unchanged and is never an OAuth token. Setting incomplete/wrong OAuth config with MCP enabled blocks service startup rather than exposing stock.

## Windows worker integration required (NOT part of the Render-only source)

**Blocker:** the Windows Worker handling `/bridge` does not appear in `xingwang_miniapp/` and has not been provided for safe modification. Do NOT deploy/enable stock lookup expecting it to work without the worker change. The existing Telegram `stock` branch verifies Telegram initData — it MUST keep doing so.

Add one new worker dispatch branch handling only these bridge messages from the pre-authenticated Render websocket:

```json
{"type":"query","id":"<uuid>","source":"chatgpt_oauth","bot":"STOCK","action":"stock_mcp","q":"1314"}
```

The worker must:
1. Require its existing authenticated Render bridge transport and an explicitly allowed pair (`source=chatgpt_oauth`, `action=stock_mcp`, `bot=STOCK`).
2. Validate `q` as a literal product code (2..40 characters, `[A-Za-z0-9][A-Za-z0-9._/-]+`).
3. Call only the **read-only existing stock query** in local Flask; no customer, pricing, notes or orders; never issue UPDATE or INSERT.
4. Normalize returned data to numeric `stock_rolls`, `stock_meters`, and optional numeric `incoming_rolls`/`incoming_meters`. If the current Flask query does not support incoming units, return `null`, never fabricate zero.
5. Return through the existing response id correlation:

```json
{
  "type":"response",
  "id":"<same uuid>",
  "ok":true,
  "data":{
    "product_code":"1314",
    "stock_rolls":24,
    "stock_meters":2100.5,
    "incoming_rolls":null,
    "incoming_meters":null,
    "as_of":"2026-10-12T23:20:00-03:00"
  }
}
```

**Numbers shown above are schema illustrations only, not actual stock.** `source` is appended by Render from the trusted connected role. On failures, return `ok:false` with a safe `code`, e.g. `LOCAL_API`, not `stock_rolls=0`. The worker must never treat other `source` strings as trusted auth.

### Security note about worker trust
`source=chatgpt_oauth` is only a protocol discriminator, **not a security credential**. It is safe only when paired with the existing bridge shared-secret authenticated channel and Render's validated OAuth request. Never create a public `stock_mcp` REST endpoint, never allow Telegram `/api/query` to send `action=stock_mcp`, and never accept this operation from other unauthenticated callers.

## Pre-deployment verification gate
1. Install pinned supported `mcp`/FastAPI/PyJWT packages in isolated test environment; verify SDK API compatibility and code imports.
2. Confirm feature disabled by default: service imports with no OAuth env and existing Telegram V23 still works.
3. Confirm feature-enabled service refuses to start without issuer/JWKS/audience/owner list.
4. Test invalid/missing/expired/forged/wrong-audience/wrong-scope/wrong-sub JWTs: no data, no bridge request.
5. Test valid JWT `tools/list`: only `search_stock`; inspect `readOnlyHint` and `securitySchemes`, check ChatGPT OAuth linking challenge and PKCE flow.
6. Valid call reaches Windows worker through real `/bridge`; verify product 1314 from the same existing Flask inventory source.
7. Offline/switching/timeout/invalid data: report failure instead of returning fabricated zero.
8. Telegram V23 regression: old Mini App, bot, `/api/query` validation and other actions unchanged.
9. Only after these pass, merge during agreed maintenance window or deploy a separate Render staging service to avoid touching the live bot.
10. Update the **existing** XINGWANG STOCK private plugin with the verified MCP endpoint (do not create a duplicate); then test ordinary ChatGPT and separately Live voice.

## Reference docs
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/build/mcp-server
- https://py.sdk.modelcontextprotocol.io/run/authorization/
- https://py.sdk.modelcontextprotocol.io/run/asgi/
