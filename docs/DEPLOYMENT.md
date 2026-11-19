# Deployment notes (production)

The localhost compose stack is for development. Production needs managed
services, TLS, secrets, backups and monitoring.

## Minimum checklist

- [ ] Managed Postgres with RLS/FORCE RLS, automated backups, PITR, encryption.
- [ ] Dedicated least-privilege login role (`DB_APP_ROLE` member), not `postgres`.
- [ ] Secret manager for `SUPABASE_JWT_SECRET`, `STRIPE_*`, SMTP, DB credentials;
      rotate the dev JWT secret. Configure `GOTRUE_ADMIN_URL` +
      `GOTRUE_SERVICE_ROLE_KEY` so erasure can delete the auth identity.
- [ ] TLS termination (reverse proxy/load balancer); set `CORS_ORIGINS` to the
      real web origin.
- [ ] `LLM_PROVIDER=bedrock`, `BEDROCK_REGION=ap-southeast-2`, regional model ID,
      account-level AI-services opt-out asserted before real matter data.
- [ ] Durable object storage (S3 Sydney, SSE, least privilege); set `STORAGE_DIR`
      accordingly or replace the storage module.
- [ ] Redis with auth/TLS for arq + rate limits.
- [ ] Observability sink: set `SENTRY_DSN` (PII disabled in code) or add
      OpenTelemetry; scrape `/metrics`; alert on `/health/db` degradation and LLM
      errors.
- [ ] Run `alembic upgrade head` as the owner, then apply app-role grants; never
      run `run_migrations.py` against prod.
- [ ] Backups: `infra/scripts/backup_postgres.sh` (or managed snapshots) and a
      quarterly restore drill.
- [ ] Remove/disable the dev `auth` stub; use hosted Supabase Auth (email
      verification, MFA, refresh rotation).
- [ ] Pen test + SOC 2/ISO 27001 readiness before enterprise sales.
- [ ] Publish the reviewed privacy policy, terms, collection notice and DPA.

## Rollout

1. Deploy API/worker with the migration version pinned.
2. Smoke: `/healthz`, `/health/db` (`rls_enforced: true`), `/health/llm`.
3. Deploy web; verify a real signup → intake → simulation → attest → export.
4. Watch `/metrics`, error rate, and audit-write failures.
5. Run the drift check against the running container.

## Rollback

Migrations 0001–0005 are reversible (`alembic downgrade`). Take a backup before
any schema change; restore from backup rather than attempting a destructive
downgrade in prod.
