# T014 — JD parser validation

Run across all 9 sample JDs. Model: `gemini-3.5-flash` (reasoning tier),
`temperature=0.0`. One extraction call per JD.

**Result: 9/9 parsed, 140 requirements, 0 failures, 0 warnings.**

| JD | secs | reqs | technical | soft | eligibility | required | preferred |
|---|---:|---:|---:|---:|---:|---:|---:|
| advantest_ai_engineering_intern | 11.93 | 22 | 20 | 1 | 1 | 15 | 7 |
| amazon_sde1_intern | 11.41 | 19 | 11 | 3 | 5 | 8 | 11 |
| ey_consulting_technology_analyst | 11.14 | 11 | 9 | 0 | 2 | 10 | 1 |
| mathco_ai_analyst | 10.46 | 17 | 11 | 4 | 2 | 15 | 2 |
| nse_technology_infrastructure | 13.36 | 17 | 12 | 4 | 1 | 10 | 7 |
| nse_technology_operations | 9.57 | 22 | 21 | 0 | 1 | 22 | 0 |
| osfin_implementation_engineer | 8.63 | 9 | 3 | 6 | 0 | 9 | 0 |
| zs_business_technology_solutions_associate | 11.89 | 15 | 6 | 4 | 5 | 8 | 7 |
| zs_decision_analytics_associate | 8.34 | 8 | 0 | 6 | 2 | 8 | 0 |

Median 11.14s, max 13.36s. Requirement count ranges 8–22 (mean 15.6).

FR3 (varied structure) holds: the corpus spans 9–31 bullets per JD and mixes
bulleted requirement lists with prose-heavy consulting postings, and every one
parsed.

## Hand-checked anomalies — all three are correct

Three outputs looked wrong on the numbers and were checked against source.

**`zs_decision_analytics_associate` — 0 technical requirements.** Correct. The
JD's "What you'll bring" section is entirely soft skills; every technical term
("advanced data analytics", "AI") appears only in company boilerplate or in
"What you'll do" responsibilities. The parser correctly skipped both per the
extraction prompt. This is a genuine property of the posting, and makes it a
useful adversarial case for the classifier later.

**`nse_technology_operations` — 22 requirements, all `required`, 0 soft.**
Correct. `grep` for hedging language (`prefer|plus|nice to have|bonus|
desirable`) returns nothing — the JD genuinely states everything flatly.
Soft-skill vocabulary appears only under a "Stakeholder Communication:"
*responsibility* heading and in a benefits blurb ("Collaborative and inclusive
work culture"), both correctly skipped.

**`osfin_implementation_engineer` — 6 soft vs 3 technical.** Correct; it is a
client-facing implementation role whose requirements really are mostly
behavioural.

## Real defects found

**1. Location extracted as an eligibility requirement.** `nse_technology_
operations` yielded `Chennai` (eligibility, required). This is per the current
prompt, which lists "location" under eligibility — but it is a scoring bug
waiting to happen: no resume bullet will ever semantically match a city name,
so it is guaranteed to classify as a Gap and drag the match score down for
reasons unrelated to fit. Either exclude location at extraction, or exclude
eligibility-of-type-location from scoring at T045. **Decide before T045.**

**2. Slash-compounds not split.** `Java/C`, `SQL/PLSQL`, `Linux/Windows` were
each kept as one requirement, while comma-compounds ("Python, SQL, and cloud
platforms") were correctly split into three. Inconsistent. Under-counts
distinct skills and produces requirement names no resume chunk will match
cleanly. Prompt fix at T038.

**3. Some requirement names are too vague to retrieve against.** `Maintenance
and Operations`, `Software development cycle`, `Code release methodologies`.
These will retrieve poorly in Phase 2 because they carry little semantic
signal. Worth watching at T026 before treating it as a prompt problem.

## Dedupe (T012) fired zero times in production

extracted=140, after_dedupe=140. The unit tests pass, but the rule has now
never merged anything on real data. Two readings: the model already emits
canonical names so there is nothing to merge (plausible — names came back
short and clean), or `canonical_key` is too strict against real-world variation.
Not a defect yet, but do not treat T012 as validated by this run. Re-check
after the T038 prompt changes, which will increase requirement counts.

## Latency — the NFR1 problem is now concrete

**JD extraction alone costs a median 11.1s.** That is one call. The full
pipeline (NFR1: under ~30s) also needs embedding, retrieval, one classification
call per requirement, and report generation.

At a mean 15.6 requirements per JD and `LLM_MAX_CONCURRENCY=4`, classification
is ~4 sequential waves. Even at a generous 5s per classification call that is
~20s, landing the end-to-end run at 35–45s+ — over budget before retrieval or
reporting is counted.

Earlier measurement on a small synthetic fixture showed 5.4s; real 2–4KB JDs
take roughly twice that. Do not plan against the synthetic number.

Levers, in order of preference (detail in `docs/providers.md`):

1. Raise concurrency — but free-tier RPM is the reason it is 4, so this trades
   latency for 429s. Needs measurement, not assumption.
2. Cache JD extraction. The same JD is re-parsed on every run today; in the
   multi-JD (FR17) and version-diff (FR24) modes the *same* JD is parsed
   repeatedly. Caching by JD hash removes ~11s from every repeat run and is
   the cheapest real win.
3. Shrink the classification prompt — it will be much smaller than a full JD,
   so per-call latency should be well under 11s. Measure at T034 before
   redesigning anything.

This is the T052 decision arriving early. **Do not tune it now** — the honest
number for classification latency does not exist until T034. But NFR1 should
be treated as at-risk from here, not as a formality.
