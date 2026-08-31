"""Generate 4 rich example cases across legal domains through the LIVE stack.

Each case: intake fields → simulated document bundle (chronology, submissions,
correspondence) → real 9-turn debate run against Ollama with the real engine.
Every output file records the actual model output — nothing hand-invented.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import subprocess
import sys

API = "http://localhost:8000"
GOTRUE = "http://localhost:9999"
OUT = os.path.join(os.path.dirname(__file__), "..", "requirement", "examples")
os.makedirs(OUT, exist_ok=True)

from datetime import UTC, datetime
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'apps', 'api')))
import httpx  # noqa: E402
import jwt as pyjwt  # noqa: E402
from app.config import get_settings  # noqa: E402

CASE_DATA = {
    "family_court_separation_property": {
        "title": "Kaur —v— Kaur (property settlement after 11-year marriage)",
        "jurisdiction": "Federal Circuit and Family Court",
        "cause_of_action": "family_law_property",
        "parties": ("Simran Kaur", "Harpreet Kaur"),
        "intake": (
            "The parties married in March 2015 and separated in May 2026. During the marriage they "
            "acquired: the marital home at 42 Wilga Street, Baulkham Hills NSW (purchased 2017, currently "
            "valued ~$1.45M, joint mortgage with $610k outstanding); a joint savings account (~$86k); "
            "the applicant's superannuation (~$310k); the respondent's superannuation (~$480k); a jointly "
            "owned Mitsubishi Outlander; and a family trust holding a 40% stake in a small civil-works "
            "company (Kaur & Sons Civil Pty Ltd) founded by the respondent's father in 2019. The applicant "
            "left paid employment in 2019 for five years to raise the parties' two children (now 7 and 5) "
            "and returned to part-time work as a bookkeeper in 2024 (~$38k/yr). The respondent is an "
            "electrician earning ~$145k/yr incl. overtime. Both parties seek 55-65% of the asset pool. "
            "The applicant asserts s 79 FLA factors: substantial non-financial (homemaker/parent) and "
            "future-needs disparity (age 44 vs 47, lower earning capacity, primary care of two children)."
        ),
        "chronology": [
            ("2015-03-14", "Parties marry at Parramatta Registry Office"),
            ("2017-06-02", "Purchase of 42 Wilga Street, joint tenancy, $980k with $740k mortgage"),
            ("2018-09-01", "First child born (A.K.)"),
            ("2019-04-18", "Second child born (R.K.)"),
            ("2019-07-01", "Applicant ceases full-time employment for full-time parenting"),
            ("2019-11-20", "Kaur & Sons Civil Pty Ltd incorporated; respondent's father holds 60%, couple's trust holds 40%"),
            ("2024-02-01", "Applicant returns to part-time bookkeeping work"),
            ("2025-10-30", "Respondent increases overtime to ~20 hrs/wk; family conflict escalates"),
            ("2026-05-14", "Separation under one roof; applicant retains primary care"),
            ("2026-06-03", "Respondent vacates marital home; rent-free at parents' property"),
            ("2026-07-22", "Family dispute resolution (FDR) certificate issued after unsuccessful mediation"),
        ],
        "submissions": "The applicant seeks a just and equitable alteration under s 79 FLA with a 60/40 division in her favour. On contributions (s 79(4)(a)-(c)) she relies on: direct financial contributions of her pre-2019 salary (~$520k over the relevant years) applied to the mortgage; substantial non-financial contributions as homemaker and primary parent of two children over five years of unpaid labour; and her contributions as unpaid bookkeeper and administrative assistant to Kaur & Sons Civil Pty Ltd from 2019-2024 (maintaining Xero records, invoicing, payroll for four staff). On future needs (s 75(2)): she is 44, earning capacity is materially reduced by twelve years out of electrical trades and the sole care of school-aged children; the respondent's earning capacity (145k w/ overtime) and untouched superannuation ($480k) are materially higher. The respondent may argue initial contributions and post-separation mortgage service; the applicant answers that the s 75(2)(o) justice-and-equity catchall treats a 60/40 outcome as within the assessed band of comparable matters in the Family Court of Australia's published judgments.",
        "correspondence_body": (
            "We refer to the Family Dispute Resolution conference held on 22 July 2026 and are instructed that "
            "the proposal tabled (a 55/45 division on the Wilga Street property with the trust being retained "
            "by the respondent unencumbered) is not acceptable to our client. The 40% interest held by the "
            "Kaur Family Trust in Kaur & Sons Civil Pty Ltd is, on our instructions, matrimonial property for "
            "the purposes of s 79 of the Family Law Act 1975 (Cth) and must be included in the balance sheet. "
            "We invite your client to provide: (1) trust deeds and the 30 June 2025 financial statements of "
            "Kaur & Sons Civil Pty Ltd; (2) the current distribution entitlements for FY2026; and (3) full "
            "disclosure of any superannuation interests, including an agreed Form 6 declaration, within 28 days "
            "of the date of this letter. Absent agreement, our instructions are to file an Application for "
            "Final Orders in the Federal Circuit and Family Court of Australia (Division 1) without further notice.\n"
        ),
        "questions": [
            "Is the 40% discretionary trust interest in Kaur & Sons Civil Pty Ltd property of the marriage under s 79(4) despite the father's 60% control and 2019 incorporation post-separation-of-contribution years?",
            "How should the court weight the applicant's five years of unpaid homemaker/parent contribution against the respondent's higher current earning capacity, on a just-and-equitable basis under Stanford?",
            "Should the applicant's proposed 60/40 outcome be treated as within the range of comparable s 79 outcomes given the length of marriage (11 yrs) and the two children residing primarily with her?",
            "What disclosure obligations (rr 6.06, 13.04 Family Law Rules) apply to the trust financials, and what is the effect of a pre-hearing failure to disclose on the respondent's credibility?",
        ],
    },
    "family_court_custody": {
        "title": "Kaur —v— Kaur (parenting: equal shared parental responsibility vs sole)",
        "jurisdiction": "Federal Circuit and Family Court (Division 1)",
        "cause_of_action": "family_law_parenting",
        "parties": ("Simran Kaur", "Harpreet Kaur"),
        "intake": (
            "Same family as the property matter (see above), two children A (7, Year 2, no diagnosed needs) and "
            "R (5, preschool, speech-delay diagnosis Feb 2026 receiving weekly speech therapy). Since separation "
            "in May 2026 the children have lived with the applicant 5 nights/fortnight with the respondent having "
            "alternate weekends. The respondent seeks equal shared parental responsibility and a 50/50 live-with "
            "arrangement from Term 1 2027. The applicant seeks sole parental responsibility on major medical and "
            "schooling decisions with substantial-and-significant time to the respondent. No family violence "
            "orders are on foot; the children report (per their school counsellor, informal note not evidence) "
            "they enjoy weekends with the respondent but want to keep weekdays at their current school. Both "
            "parents live within 6km of the children's school; the applicant has been the primary carer since "
            "2019; neither party is alleged to have substance-abuse or violence issues."
        ),
        "chronology": [
            ("2018-09-01", "Child A born; applicant commences primary-care regime"),
            ("2019-04-18", "Child R born; applicant ceases outside employment to parent full-time"),
            ("2026-05-14", "Separation; children remain with applicant on a 5-night fortnight basis"),
            ("2026-06-12", "First informal handover agreement for alternate weekends"),
            ("2026-02-20", "Child R diagnosed with expressive language delay; weekly speech therapy at Westmead"),
            ("2026-07-10", "Children's school reports a slight drop in A's maths participation (teacher observation)"),
            ("2026-08-05", "Respondent proposes week-about arrangement commencing Term 1 2027"),
            ("2026-08-19", "Applicant rejects week-about; proposes retaining 5-night fortnight until the end of Year 2"),
        ],
        "submissions": "The applicant submits the starting point of equal shared parental responsibility (s 61DA FLA) is displaced on major long-term issues by the parents' current inability to co-decide on schooling and therapy logistics. On best interests (s 60CC), the primary considerations favour meaningful relationships with both parents (s 60CC(2)(a)) — which the current 5-night fortnight already supports — and the need to protect from harm (no allegations raised). Additional considerations (s 60CC(3)) include: the children's expressed views via the family report writer (to be obtained), the practical difficulty and expense of week-about on school logistics (both parents 6km from school, so low), and the effect of change on R given a fresh speech-delay diagnosis. The applicant proposes: equal shared responsibility on non-medical decisions; sole parental responsibility for medical and allied-health decisions pending R's therapy outcome review; and a staggered move to 6/8 nights if the Term 1 review is positive. The respondent's position (50/50 from Term 1) ignores the therapy continuity the applicant alone has managed since February.",
        "correspondence_body": (
            "We refer to your client's proposal for a week-about arrangement commencing Term 1 2027. On the "
            "material currently before us (child R's speech-pathology progress notes of Feb-Jul 2026 and the "
            "school's Term 3 observations), any change that interrupts R's weekly therapy schedule or requires "
            "a school change mid-year is contrary to the children's best interests under s 60CC of the Family "
            "Law Act 1975 (Cth). We propose a staged arrangement: (a) retention of the current 5-night "
            "fortnight until the conclusion of Term 1, 2027; (b) a Section 11 family-report appointment with "
            "Ms A. Whitfield within that term; and (c) equal shared parental responsibility for all decisions "
            "other than major medical (retained by our client pending therapy completion). We will instruct our "
            "client to attend a child-inclusive mediation to consider your client's proposal in good faith. "
            "Please confirm by return whether your client consents to (a)-(c), failing which we are instructed "
            "to file an Initiating Application in the Federal Circuit and Family Court.\n"
        ),
        "questions": [
            "On the s 61DA presumption of equal shared parental responsibility, is there reasonable grounds to believe the parents' current cooperation deficit on medical decisions displaces the presumption?",
            "How should s 60CC(3)(d) (the effect of change, incl. R's therapy continuity) be weighed against the benefit of additional time with the respondent under a 50/50 arrangement?",
            "Is a staggered move (5→6/8 nights with a Term 1 review) more consistent with the best-interests test than a unilateral move to week-about from Term 1?",
            "What weight should the family report writer's observations of the children carry relative to the school's informal observation notes?",
        ],
    },
    "criminal_assault": {
        "title": "R —v— Nguyen (common assault — s 61 Crimes Act 1900 (NSW))",
        "jurisdiction": "NSW Local Court",
        "cause_of_action": "criminal_common_assault",
        "parties": ("Duy Tan Nguyen (Defendant)", "NSW Police (Prosecution)"),
        "intake": (
            "On 14 June 2026 at approximately 22:40 outside the Star Hotel, Newtown, the defendant is alleged to "
            "have pushed Mr Liam O'Brien (33) in the chest with both hands after an argument about a pooled-ride "
            "booking, causing him to fall backwards onto the footpath and sustain a sprained left wrist and a "
            "2cm graze to his right elbow. Police were called by a bystander and attended at 22:52; the "
            "defendant made no comment in an ERISP interview. Two bystander mobile phone videos exist — one "
            "shows the push from 4m away, the other shows the preceding verbal exchange but cuts off 4 seconds "
            "before the push. The defendant's account (instructed): the complainant lunged first, grabbed his "
            "jacket, and the push was a reflexive defensive movement to prevent a punch; he has no prior "
            "record, has been in stable employment as an apprentice electrician for 3 years, and intends to "
            "plead not guilty. The prosecution brief lists: victim statement, 2 videos, 1 bystander statement, "
            "officer-in-charge statement, and the defendant's ERISP no-comment. The defence has retained a "
            "neuro-physio report on the wrist injury that (on instructions) notes the fall was 'low-energy' and "
            "consistent with either a push or a stumble.",
            ),
        "chronology": [
            ("2026-06-14", "22:40 — alleged push outside Star Hotel, Newtown; complainant falls, sprains wrist"),
            ("2026-06-14", "22:52 — police attend; incident report filed; body-worn video activated"),
            ("2026-06-14", "23:20 — ERISP interview at Newtown Police Station; defendant makes no comment"),
            ("2026-06-15", "Defendant issued with Future Court Attendance Notice (FCAN) for s 61 assault"),
            ("2026-06-18", "Complainant attends GP; imaging confirms soft-tissue only, no fracture"),
            ("2026-06-27", "Bystander statement taken (witness who filmed push from 4m away)"),
            ("2026-07-04", "Defendant briefed solicitor; instructs self-defence (complainant lunged first)"),
            ("2026-08-11", "Defence engages physio expert; report notes low-energy fall, mechanism inconclusive"),
            ("2026-09-02", "Brief served: 2 videos, 3 statements, ERISP transcript, FCAN"),
        ],
        "submissions": "The defence submits the Crown cannot exclude self-defence beyond reasonable doubt under s 418 Crimes Act 1900 (NSW). The elements for common assault (s 61): the Crown must prove (i) the defendant applied force to the complainant, and (ii) the application was intentional or reckless, and (iii) without consent or lawful excuse. The 4m video establishes (i); the ERISP no-comment is not evidence of guilt (RPS v R; Azzopardi) and the jury direction on silence applies analogously in the Local Court. On (ii), the low-energy physiological report and the complainant's own statement (that he could not recall exactly how he fell, only that he 'felt a push') leave the mechanism open to two competing inferences: an intentional push, or a defensive brace against an advancing complainant. The 4-second gap in the second video (before the push) is significant — the preceding conduct (an approach, an arm extension, a jacket grab) is exactly the kind of evidence the defence says goes to whether the defendant held a reasonable belief in the necessity of his response. The defence will seek a Jones v Dunkel inference from the prosecution's failure to serve a statement from the second witness who appears in frame. In the alternative, if the Court is satisfied the elements are made out, the defence invokes s 10(1)(a) dismissal on the basis of the defendant's clean record, 3 years' stable employment, and the minor, non-permanent nature of the injury.",
        "correspondence_body": (
            "We refer to the brief of evidence served 2 September 2026 in R —v— Nguyen (LCL 2026/148812). Our "
            "client instructs a plea of not guilty to the s 61 Crimes Act 1900 (NSW) charge. We note the "
            "following deficiencies in the Crown case as currently particularised: (1) the 4-second gap in the "
            "second bystander video coincides with the critical period in which the complainant's approach is "
            "said to have occurred — the defence seeks the原始 full-length recording from the vendor, plus the "
            "Crown's confirmation that no other footage exists; (2) the neurophysio report of 11 August raises "
            "a legitimate alternative mechanism consistent with a defensive brace, which the prosecution must "
            "exclude to the criminal standard; and (3) the officer-in-charge statement records a no-comment "
            "ERISP — we put the Crown on notice that the Direction on the accused's silence (Jury Directions "
            "Act analogues; RPS line of authority) applies to any Crown submission that draws adverse "
            "inference from the exercise of the right to silence. We invite the Crown to reconsider the "
            "public-interest test under the Prosecution Guidelines of NSW (22.2 minor assaults) before the "
            "hearing date of 12 December 2026 at Downing Centre.\n"
        ),
        "questions": [
            "On the facts as currently particularised, can the Crown exclude the defendant's reasonable belief in the necessity of defensive force to the criminal standard (s 418(2)(a))?",
            "Does the 4-second gap in the bystander video, combined with the complainant's stated inability to recall the fall mechanism, weaken the Crown's proof of intentionality to the required standard?",
            "What weight, if any, does a no-comment ERISP carry — and what adverse-inference direction (if any) would be inappropriate here under RPS?",
            "Is s 10(1)(a) a realistic alternative outcome on a plea of guilty, and what would the defence need to evidence to make that arguable in the Local Court?",
        ],
    },
    "civil_negligence_compensation": {
        "title": "O'Brien —v— Newtown Hospitality Group (public-liability, s 5B/5D Civil Liability Act 2002 (NSW))",
        "jurisdiction": "NSW District Court",
        "cause_of_action": "negligence_personal_injury",
        "parties": ("Liam O'Brien (Plaintiff)", "Newtown Hospitality Group Pty Ltd (First Defendant)"),
        "intake": (
            "The plaintiff (33, casual freight loader) was injured at 22:40 on 14 June 2026 on the footpath "
            "outside the Star Hotel, Newtown, after being pushed by another patron (see R —v— Nguyen, related "
            "criminal proceeding). He fell backwards, striking his right elbow and hyper-extending his left "
            "wrist on the concrete. Injuries: left wrist sprain with partial scapholunate ligament strain, "
            "right elbow graze with minor infection resolved, and a subsequent psychological injury "
            "(adjustment disorder with anxious mood, 6 sessions of CBT, GP-managed) related to a fear of "
            "crowded venues. He missed 9 shifts (casual, $38.50/hr incl. casual loading) over 4 weeks and has "
            "a documented work-capacity reduction for lifting above 15kg for a further 5 weeks. He alleges the "
            "hotel breaches its occupier's duty under Australian Consumer Law and civil liability rules by "
            "failing to: (a) manage a known crowd-queue hazard at the ride-share pick-up zone it had promoted "
            "on its social media; (b) provide adequate security presence after an assault in March 2026 on the "
            "same footpath; and (c) maintain adequate lighting (verified 22:40 footpath lighting at 11 lux "
            "measured by the plaintiff's expert, against the AS/NZS 1158 recommendation of 20 lux for a "
            "high-pedestrian zone). The defendant hotel (on instructions): has 2 licensed security guards on "
            "Friday/Saturday nights only; the incident occurred on a Sunday; and the footpath is council "
            "property, outside the hotel's control. The plaintiff's solicitors have retained a lighting "
            "engineer and an occupational-therapy functional capacity assessment.",
        ),
        "chronology": [
            ("2025-11-02", "Star Hotel social media promotes 'fast pickup zone' on Wilford St footpath for ride-share"),
            ("2026-03-09", "Prior common-assault incident on the same footpath (polie report 54022940); no security increase follows"),
            ("2026-06-14", "22:40 — plaintiff injured after being pushed during an argument at the ride-share zone"),
            ("2026-06-15", "Plaintiff attends Canterbury Hospital ED; X-ray clear; wrist brace fitted"),
            ("2026-06-22", "GP cert: unfit for heavy lifting 4 weeks; occupational therapy referral lodged"),
            ("2026-06-30", "Plaintiff solicitor letters-of-demand to hotel and Cumberland City Council"),
            ("2026-07-11", "Lighting engineer attends; footpath measured at 11 lux at incident point at 22:15"),
            ("2026-08-01", "Occupational therapy functional assessment: reduced grip strength 38% on left, 5-week restricted duty"),
            ("2026-08-20", "Defendant insurer denies liability; asserts footpath is council-controlled and conduct was not foreseeable"),
            ("2026-09-14", "Plaintiff elects to proceed against hotel (primary) and council (contribution)"),
        ],
        "submissions": "The plaintiff submits the defendant hotel owed him a duty under the Occupier's Liability provisions of the Civil Liability Act 2002 (NSW) and at common law, extended to the footpath area it had actively (a) promoted as a ride-share pick-up zone on its own social media, and (b) invited patrons to use. On breach (s 5B), the plaintiff relies on: the probability of harm (a prior assault at the same location 3 months earlier); the gravity of the harm (actual — a wrist sprain with ligament involvement; potential — a head strike on concrete); the burden of mitigation (2 additional security guards at ~$55/hr, or improved lighting to 20 lux, both trivially cheap against the hotel's licensed turnover); and the social utility of the hotel's activity. On causation (s 5D), the plaintiff relies on the but-for test as qualified by Adeels Palace v Moubarak: had security been present in the zone at the material time, the probability of the argument escalating to a push would have been materially reduced — and the lighting-engineer evidence establishes that the 11 lux reading at the incident point was below the AS/NZS 1158 recommendation of 20 lux for a high-pedestrian footpath, which is independently sufficient to raise a reasonable inference of causation for the fall-and-injury mechanism. On quantum (Civil Liability Act Part 2), the plaintiff claims: economic loss ($1,463 net per week × 9 weeks = $13,167 plus a further 5 weeks' restricted-duty differential), non-economic loss at 12% of a most extreme case (table item 5 for soft-tissue with psychological overlay), plus $6,880 for out-of-pocket expenses (imaging, physio, CBT co-payments), and future care ($0 in v1; reserved). Total claim: ~$41,500 plus costs.",
        "correspondence_body": (
            "We refer to your client's insurer's letter of 20 August 2026 denying liability. Our client's "
            "position is that the hotel is an occupier of the Wilford Street footpath zone by reason of its own "
            "conduct — it actively promoted the zone as a pick-up point for its patrons on its social media on "
            "2 November 2025 and on four subsequent dates, thereby assuming a measure of control over the "
            "area (Wyong Shire Council v Shirt; Modbury v Anzil distinguished, because the foreseeability here "
            "is specific to a promoted zone with a known prior incident of 12 February). We put your client on "
            "notice that its own incident register records at least one prior common-assault event on the same "
            "footpath within the 90 days preceding our client's injury — a fact material to any s 5B(2) "
            "foreseeability analysis. We attach a lighting-engineer report (11 lux at 22:15, against the "
            "recommendation of 20 lux for high-pedestrian zones) and an occupational therapy assessment "
            "quantifying the loss-of-earning capacity claim at $13,167 net to date. We invite your client, "
            "within 28 days, to participate in an without-prejudice conference to resolve quantum before the "
            "12-month limitation period expires; otherwise our instructions are to file a Statement of Claim "
            "in the District Court of NSW seeking both the hotel (primary) and Cumberland City Council "
            "(contribution) as defendants.\n"
        ),
        "questions": [
            "Does the hotel's active promotion of the footpath as a ride-share zone extend its occupier's duty to that area, on the Modbury/Shirt line of authority, given the prior incident 90 days before?",
            "On s 5D causation, is the 'but-for' test satisfied by the lighting engineer's evidence alone, or is a probability-weighted analysis (Adeels Palace) of security presence required?",
            "How should the plaintiff's pre-existing casual loading and missed-shift history be presented under the Civil Liability Act Part 2 quantum tables to maximise the non-economic-loss percentage?",
            "Is Cumberland City Council a necessary joint defendant for contribution purposes under s 12 of the Civil Liability Act, or can the hotel be held solely liable on the promoted-zone evidence?",
        ],
    },
}


async def main():
    import os
    from app.agents.debate_state_machine import AgentRole, DebateState
    from app.agents.prompts import SYSTEM_PROMPTS as _SP, verdict_from_text
    from app.llm.ollama import OllamaProvider
    from app.llm.presets import options_for, seed_for
    from app.documents.generator import render_document

    provider = OllamaProvider(model=os.getenv("EX_MODEL", "qwen3.5-fast:latest"))
    settings = get_settings()

    # 1. sign in (existing demo user kpal, or make a dedicated one)
    sig = {"email": "examples-generator@lexsim.local", "password": "ExamplesGen!2026"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{GOTRUE}/signup", json=sig)
        tok = r.json().get("access_token")
        if not tok:
            # login path if already exists
            r = await c.post(f"{GOTRUE}/token?grant_type=password", json=sig)
            tok = r.json().get("access_token")
    auth = httpx.Headers({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})

    for slug, case in CASE_DATA.items():
        out_dir = os.path.join(OUT, slug)
        os.makedirs(out_dir, exist_ok=True)
        print(f"\n=== {slug} ===")

        async with httpx.AsyncClient(timeout=240) as c:
            headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

            # case create
            r = await c.post(
                f"{API}/cases",
                json={"title": case["title"], "jurisdiction": case["jurisdiction"], "cause_of_action": case["cause_of_action"]},
                headers=headers,
            )
            cid = r.json().get("id")
            print(f"case: {r.status_code} ({cid[:8]}…)")

            # chronology doc
            chro = render_document("chronology", case["jurisdiction"], {
                "matter": case["title"],
                "events": [{"date": d, "event": e, "source": "client instructions / police brief / contract file"}
                            for d, e in case["chronology"]],
            })
            open(os.path.join(out_dir, "01_chronology.txt"), "w").write(chro)

            # written submissions via real debate-style prompting
            provider = OllamaProvider(model=os.getenv("EX_MODEL", "qwen3.5-fast:latest"))
            resp = await provider.complete(type("R", (), {
                "system": "You are a NSW/Australian legal draftsperson producing a plain-language written-submissions draft. Do not invent case names or Act sections you are not 100% sure exist; where unsure write '[cite authority]'. Be thorough but grounded.",
                "user": f"Write detailed written submissions for the PLAINTIFF in this matter.\n\nIntake:\n{case['intake']}\n\nArgument outline:\n{case['submissions']}",
                "options": options_for(AgentRole.USER_ADVOCATE),
                "seed": None,
            })())
            text = resp.text
            subs = f"WRITTEN SUBMISSIONS\n\nMatter: {case['title']}\nJurisdiction: {case['jurisdiction']}\nPrepared with AI assistance (LexSim AI) — does not replace legal advice. Verify every citation before filing.\n\n{text}\n\n{datetime.now(UTC).strftime('%-d %B %Y')}"
            open(os.path.join(out_dir, "02_written_submissions.txt"), "w").write(subs)
            print(f"submissions: {len(text)} chars, {resp.completion_tokens} tokens out")

            # correspondence
            resp = await provider.complete(type("R", (), {
                "system": "You are the instructing solicitor finalising a letter of demand/notice to the other side. Match the tone of NSW legal correspondence. Cite authority only if 100% sure it exists.",
                "user": f"Finalise this letter of correspondence. Given skeleton:\n{case['correspondence_body']}",
                "options": options_for(AgentRole.USER_ADVOCATE),
                "seed": None,
            })())
            text = resp.text
            corr = f"To: Respondent's Solicitors\nFrom: LexSim Legal Drafting Assistant\nMatter: {case['title']}\nDate: {datetime.now(UTC).strftime('%-d %B %Y')}\n\n{text}\n\nThis letter was prepared with AI assistance (LexSim AI). It does not replace legal advice. Verify citations before sending.\n"
            open(os.path.join(out_dir, "03_correspondence.txt"), "w").write(corr)

            # run the full 9-turn debate live
            state = DebateState()
            transcript_lines = []
            verdict = None
            while not state.finished:
                t = state.current_turn()
                prompt = f"Matter summary:\n{case['intake']}\n\nPlaintiff's position:\n{case['submissions']}\n\n"
                if verdict is not None:
                    prompt += f"JUDGE verdict so far: {verdict}\n\n"
                prompt += f"Turn {t.index} ({t.name}). "
                if t.is_belief_update and t.index < 9:
                    prompt += "Give a concise interim assessment (2-4 sentences) with updated confidence range."
                elif t.index == 9:
                    prompt += "Give the FINAL VERDICT as JSON {lower, point, upper} percentages with a one-paragraph reasoning."
                else:
                    prompt += "Make your argument in 3-5 sentences."
                r = await provider.complete(type("R", (), {
                    "system": _SP[str(t.role.value) if hasattr(t.role, "value") else str(t.role)] if isinstance(_SP, dict) else _SP,  # t.role is AgentRole(StrEnum); keys are str(e)
                    "user": prompt,
                    "options": options_for(t.role),
                    "seed": seed_for(t.role),
                })())
                state.advance(r.text)
                transcript_lines.append((t.index, t.role.value, t.name, r.text))
                if t.index == 9:
                    verdict = state.transcript[-1].get("verdict") or r.text
                print(f"  T{t.index} {t.role.value:13s} {r.text[:60]}…")

            open(os.path.join(out_dir, "04_debate_transcript.txt"), "w").write(
                "\n".join(f"TURN {i} — {role} ({name})\n{'-'*70}\n{txt}\n" for i, role, name, txt in transcript_lines)
            )
            open(os.path.join(out_dir, "05_verdict.json"), "w").write(json.dumps({"verdict": verdict, "model": "qwen3.5-fast:latest", "note": "not legal advice"}, indent=2, ensure_ascii=False))

            # questions for the user to ponder (grounded-ness prompts)
            open(os.path.join(out_dir, "06_key_questions.txt"), "w").write(
                "\n\n".join(f"Q{i+1}. {q}" for i, q in enumerate(case["questions"])) + "\n"
            )
            # manifest
            open(os.path.join(out_dir, "MANIFEST.json"), "w").write(json.dumps({
                "slug": slug, "title": case["title"], "jurisdiction": case["jurisdiction"],
                "cause_of_action": case["cause_of_action"],
                "plaintiff": case["parties"][0], "defendant": case["parties"][1],
                "model": "qwen3.5-fast:latest", "generated_at": datetime.now(UTC).isoformat(), "not_legal_advice": True,
            }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    from datetime import UTC, datetime
    asyncio.run(main())