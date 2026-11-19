# Data flows and processors (APP 8 register)

> One row per external processor. Update before enabling a new integration.

| Processor | Data | Destination | When | Control |
|---|---|---|---|---|
| Ollama (local) | Prompts, responses, matter text | Operator machine only | v1 default | Loopback; no egress |
| Amazon Bedrock | Prompts, responses | `ap-southeast-2` only | Phase 2 (`LLM_PROVIDER=bedrock`) | Region/model/startup guard; account-level opt-out asserted before real data |
| Stripe | Email, plan, payment metadata | Stripe (US/global) | Checkout / webhook | Test mode in dev; no card data stored; webhook HMAC |
| SMTP (Mailpit dev / provider prod) | Email address, deadline subject/date | Dev local; provider in prod | Reminder cron | No case content in the email body |
| Sentry/OpenTelemetry (optional) | Traces/log metadata | Not configured | Not in v1 | Add a scrubber before enabling |
| AWS S3 (prod storage) | Raw uploads | Sydney bucket | Phase 2 | Server-side encryption, least privilege, presigned URLs only |

## Cross-border assessment

v1 is local-only. Bedrock is pinned to Sydney; cross-region inference profiles
(`global.`, `apac.`, `us.`, `eu.`) are banned and CI-checked. Stripe and any
external observability sink are the remaining cross-border disclosures and must
be covered by the privacy policy/DPA before launch.

## Privilege note

AI analysis may not be privileged. The app stores verbatim prompts/responses in
an append-only audit trail for LPP reconstruction; tenants cannot read
`audit_content`. Erasure de-identifies case content but retains audit rows for
legal/LPP obligations.
