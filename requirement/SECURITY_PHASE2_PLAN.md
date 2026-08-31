# Security — Phase-2 work order (claiming item ③ now, 31 Aug late)

Taking ownership of the highest-precedence Phase-2 item: **③ header-safe SSE**.

## Why now
`page.tsx:193` still ships `new EventSource(...?token=${token})` — the JWT leaves in a URL on every
debate stream. The TokenScrubFilter (3c38dbe) protects *our* logs, but a proxy, browser history, or
any intermediary in front of `:8000` would see the plaintext token. This is the last line-of-travel
hole in v1.

## Plan (this is a two-file change + one test)
1. `apps/web/app/page.tsx`: replace `EventSource` with `fetch(url, { headers: { Authorization: 'Bearer …' }})`
   + `response.body.getReader()` — parse the `text/event-stream` frames manually (event/data lines split on
   `\n\n`). EventSource cannot set headers; fetch can. Next 16 note: no API change needed, this is plain
   browser fetch.
2. `apps/api/app/db.py`: keep `?token=` accepted for exactly one release window (older clients), mark the
   query-param branch `# LEGACY — scheduled for removal, see PENDING ③`.
3. `main.py` log filter stays permanently — defence-in-depth for proxies/older clients.
4. New test: `test_sse_accepts_header_auth` (Bearer header on `/simulate` returns 200 + first event) and
   `test_sse_query_token_still_accepted` (documented deprecation window), both `compliance`-marked.
5. After the deprecation window: delete the `elif token:` branch in get_db, then re-verify
   `openapi.json` no longer advertises the `token` query param.

Acceptance = the SSE stream works with no credential in any URL, `?token=` gone from OpenAPI, suite green.

## Ordering after ③ (my ownership, in order)
④ log-retention statement → ② JWT rotation runbook → ⑦ lexsim_app REVOKE scope → ① FORCE RLS (biggest
behavioural change; pairs with @coderbot's connection-role wiring) → ⑥ Bedrock opt-out assertion →
⑤ Stripe SDK (least security-sensitive).