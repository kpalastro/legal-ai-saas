# Example cases — 4 legal domains, fully simulated

These are **worked demonstration cases** with lengthy simulated paperwork and
real 9-turn LLM debates run through the live LexSim stack. They serve three
purposes: onboarding material for new users, groundedness testing (does the
model hallucinate case names/Acts? — see `scripts/generate_examples.py`),
and a way to demo the product across legal domains without real client data.

**Every file here is simulated data and every output is `not legal advice`.**

## The four cases

| Slug | Domain | Court | Core question |
|---|---|---|---|
| `family_court_separation_property` | Family law — property settlement | Fed Circuit & Family Court (Div 1) | 60/40 vs 55/45 after an 11-year marriage with a discretionary trust interest in a civil-works company |
| `family_court_custody` | Family law — parenting | Fed Circuit & Family Court (Div 1) | Equal shared parental responsibility vs sole on medical decisions, with a 5-night fortnight baseline and a speech-delayed 5-year-old |
| `criminal_assault` | Criminal — s 61 common assault | NSW Local Court | Can the Crown exclude self-defence to the criminal standard when one bystander video is gap-truncated and the physio says "low-energy fall, mechanism inconclusive"? |
| `civil_negligence_compensation` | Civil — personal injury negligence | NSW District Court | Does the promoted ride-share zone + prior assault 90 days earlier extend the hotel's occupier duty under s 5B/5D CLA, and does 11-lux lighting independently satisfy causation? |

## What's in each folder

| File | What it is (generated live through the API) |
|---|---|
| `01_chronology.txt` | Date-ordered chronology of the matter (document-generator template) |
| `02_written_submissions.txt` | Detailed written submissions drafted by the USER_ADVOCATE persona |
| `03_correspondence.txt` | A letter of demand/notice to the other side's solicitors |
| `04_debate_transcript.txt` | The full 9-turn debate run against Ollama `qwen3.5-fast` |
| `05_verdict.json` | The JUDGE's final `{lower, point, upper}` calibrated range + model + note |
| `06_key_questions.txt` | The groundedness questions a user should evaluate the verdict against |
| `MANIFEST.json` | Metadata (slug, parties, model, `not_legal_advice: true`) |

## Regenerating / extending

```bash
cd apps/api && .venv/bin/python ../../scripts/generate_examples.py
# env: EX_MODEL=qwen3.5:latest  (default is qwen3.5-fast for speed)
```
Each run signs up a fresh GoTrue user, creates fresh cases under that user
(RLS-scoped), renders templates via `app/documents/generator.py`, and runs the
9-turn debate via `app/agents/engine.py`. Add a fifth domain by appending a
`CASE_DATA` entry — the script handles the rest.

## Groundedness notes (for reviewers)

- The verdict JSON is the model's own final-turn output, extracted and stored
  verbatim with the model tag; verdicts across runs on the same facts vary
  (sampling temperature 0.15–0.3 as per TECH_STACK.md), so treat them as
  illustrative calibration, not fact.
- Where the model is uncertain about a case or Act citation, the drafting
  prompt tells it to write `[cite authority]` — you'll see that in
  `02_written_submissions.txt` where it had no matching authority loaded. This
  is intentional: it surfaces uncertainty to the human (SC Gen 23 para 17).
- All four transcripts include opposing counsel arguing the same facts — the
  point of the 9-turn protocol is that the JUDGE's belief updates at turns
  3/6/9 are auditable, not that any single verdict is "correct."
- All content carries the AI-assistance disclosure footer and the
  DoNotPay-precedent "does not replace legal advice" note, exactly as the
  production export gate enforces.