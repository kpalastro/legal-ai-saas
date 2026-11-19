# Privacy policy — DRAFT

> **Draft for legal review.** Do not publish until a privacy lawyer has reviewed
> it against the current Privacy Act 1988 (Cth), the APPs, and the jurisdictions
> you serve. This is a product template, not legal advice.

## What we collect

- Account details (email, role).
- Matter content you provide: facts, parties, issues, relief, uploaded documents,
  simulation transcripts, generated drafts, deadlines.
- AI processing records: prompts, responses, model identity/digest, timestamps.
- Document versions, content hashes, typed-name signatures and conflict-register
  entries.
- Billing identifiers from Stripe (we do not store card numbers).

## Why we collect it

To run the simulation, generate and verify documents, calculate deadlines, and
maintain an audit trail of AI assistance (APP 5 collection notice; see the
sign-in acknowledgement).

## Who processes it

- **v1 local:** Ollama on the operator's machine; no inference egress.
- **Phase 2:** Amazon Bedrock in `ap-southeast-2` only, with the account-level
  AI-services opt-out asserted before real matter data.
- **Stripe** for payments; **SMTP/Mailpit** for deadline reminders.
- **No AustLII** programmatic access.

## Storage and retention

- Postgres with RLS; `audit_log`/`audit_content` are append-only.
- Cases past the 7-year retention window are de-identified unless under legal
  hold. Audit records may be retained longer to evidence AI assistance and meet
  legal/LPP obligations.

## Access, correction and erasure (APP 12/13)

- `GET /users/me/export` returns a portable JSON bundle.
- `POST /users/me/erase` de-identifies case content and deletes raw uploads while
  retaining append-only audit rows. The GoTrue identity is deleted separately via
  the auth admin API.
- A legal hold blocks erasure/retention.

## Security

Least-privilege database role, RLS/FORCE RLS, header-only SSE auth, upload
validation, rate limits, signed Stripe webhooks, and an append-only audit trail.
See `SECURITY.md` for the current limitations.

## Contact

Privacy officer contact to be inserted before publication. Complaints may be
made to the Office of the Australian Information Commissioner (OAIC).
