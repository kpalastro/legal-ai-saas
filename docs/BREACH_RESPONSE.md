# Data breach response runbook

The OAIC Notifiable Data Breaches scheme requires an assessment within **30
days** of becoming aware of a suspected eligible data breach.

## Roles

- **Incident lead:** security chair (rotates; name in the ops roster).
- **Privacy officer:** decides notification and drafts OAIC/user notices.
- **Engineering:** contains, preserves evidence, and produces the timeline.
- **Legal:** advises on LPP, privilege and litigation hold.

## Steps

1. **Contain** — revoke credentials, disable the affected route/user, isolate the
   host. Do not destroy logs or audit rows.
2. **Preserve** — snapshot `audit_log`/`audit_content`, container logs, database
   backups, and access logs. Record the chain of custody.
3. **Assess** — what data, whose, how many, whether serious harm is likely, and
   whether encryption/access controls mitigated it.
4. **Notify** — if eligible: OAIC statement and affected individuals without
   unreasonable delay; include the incident, data, and recommended steps.
5. **Remediate** — fix, rotate secrets, add a regression test/monitor, update this
   runbook.
6. **Review** — post-incident review within 10 business days; record actions.

## Contacts

- OAIC: https://www.oaic.gov.au/
- AWS Security / Stripe support as applicable.
- Add the on-call phone/email before launch.

## Evidence to collect

`audit_log` rows (event type/model/timestamps), `audit_content` verbatim prompts
(backend-only), request ids from access logs, DB/role changes, and deployment
drift (`infra/scripts/drift_check.sh`).
