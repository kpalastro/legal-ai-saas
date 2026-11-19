# Security policy

LexSim AI handles legal matter data and is built around Australian Privacy
Principle (APP) and legal professional privilege (LPP) constraints. Please do
not open a public issue for a suspected vulnerability.

## Reporting

Email the maintainers privately (address to be added before public release) with:
reproduction steps, affected endpoint/version, and whether matter data is
exposed. We aim to acknowledge within 2 business days and to assess within the
30-day OAIC notifiable-data-breach window.

## Supported versions

Only the current `main` branch and the latest tagged release receive fixes. The
localhost development stack is not a production deployment.

## Security model (v1)

- GoTrue-issued HS256 JWTs; FastAPI verifies signature/exp/sub and is
  fail-closed (no token → no DB session).
- Every request transaction binds `SET LOCAL ROLE lexsim_app` and pins
  `search_path = public, auth`; `/health/db` exposes whether RLS is effective.
- RLS + FORCE RLS on all tenant tables, including organisation sharing.
- Append-only `audit_log`/`audit_content`; verbatim prompt/response retention.
- Uploads: MIME + magic-byte allow-list, 20 MB cap, basename-only storage under
  `STORAGE_DIR` with 0600 permissions; never served by the API.
- SSE credentials are header-only; query tokens were removed.
- Rate limits, body-size caps, request ids, security headers.
- Stripe webhooks are HMAC-verified; no checkout is fabricated when Stripe is
  unconfigured.
- Document versions are content-hashed; a typed-name signature is bound to the
  hash. A signature is an evidentiary record, not legal execution — counsel must
  confirm it meets the relevant court/e-signature rules.
- GoTrue identity deletion is available when the admin API credentials are
  configured; otherwise erasure reports `identity_deleted=false`.

## Known limitations (must be addressed before production)

- Dev auth allows auto-confirmed signup; configure email verification/MFA and a
  managed secret store before real users.
- The browser stores access/refresh tokens in `localStorage`; move to an
  httpOnly BFF/session cookie with refresh-token rotation.
- The dev compose database login role password is a known dev credential; use a
  managed least-privilege role and rotation in production.
- `audit_content` retention policy and LPP/erasure tension are documented but
  not fully automated.
- No third-party pen test, SOC 2/ISO 27001 certification, or formal DLP yet.
- Ollama is local-only in v1. Bedrock Phase 2 requires the account-level
  no-training opt-out in `ap-southeast-2` before any real matter data.

## Do not commit

`.env`, `infra/.env`, Stripe/AWS keys, JWTs, database dumps, or real matter
documents. `storage/`, `infra/.env` and `.env.local` are gitignored.
