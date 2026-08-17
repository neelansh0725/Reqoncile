# T068 — end-to-end defect sweep

All 9 sample JDs against `Best_withoutphoto.pdf`, run one at a time. Wall clock **12.3 min**.

Nothing was fixed during the run — this is the defect list as found.

## Runs

| JD | s | score | M | W | G | err | elig | rewrites | 429s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| advantest_ai_engineering_intern | 107 | 61% | 9 | 6 | 6 | 0 | 1 | 1 | 0 |
| amazon_sde1_intern | 226 | 30% | 6 | 9 | 14 | 5 | 8 | 3 | 0 |
| ey_consulting_technology_analyst | 115 | 57% | 3 | 2 | 2 | 2 | 2 | 0 | 0 |
| mathco_ai_analyst | 14 | 50% | 2 | 0 | 2 | 0 | 2 | 0 | 0 |
| nse_technology_infrastructure | 63 | 31% | 4 | 2 | 8 | 0 | 0 | 0 | 0 |
| nse_technology_operations | 79 | 21% | 3 | 3 | 15 | 0 | 0 | 1 | 0 |
| osfin_implementation_engineer | 53 | 50% | 4 | 1 | 4 | 0 | 0 | 0 | 0 |
| zs_business_technology_solutions_associate | 57 | 52% | 3 | 6 | 1 | 0 | 4 | 0 | 0 |
| zs_decision_analytics_associate | 20 | 17% | 0 | 2 | 4 | 0 | 1 | 1 | 0 |

Median run 63s · total 0 rate-limited call(s) · 7 real error(s).

## Defects

**The automated audit found none — and that headline understates the run.**
The audit checks report *invariants* (FR8, FR11, FR12, T015a, score range,
rendering). All of those held on all 9 JDs. It does not check whether calls
failed that should have succeeded, which is where the real findings are.

### D1 — Transient network failures are never retried (high)

**7 of 118 classifications (5.9%) were lost to transient network errors**, all
within two JDs:

| cause | count |
|---|---:|
| `[Errno 54] Connection reset by peer` | 5 |
| `The read operation timed out` | 2 |

None were quota — **zero 429s across the entire sweep**, so the pacing worked
exactly as intended.

The cause is in `llm_client._invoke_paced`:

```python
if not is_rate_limited(exc) or attempt == attempts - 1:
    raise
```

Retries fire **only** for rate limits. A connection reset is raised on the
first attempt and becomes an `ERRORED` requirement. That was the right
conservative choice when the retry loop was written to stop 429 storms, but a
reset peer is precisely the kind of failure a retry fixes, and the pace
limiter already provides natural backoff.

Impact is real: `amazon_sde1_intern` lost 5 of its 24 requirements and
`ey_consulting_technology_analyst` 2 of 9. NFR3 handled it correctly — the
reports generated, the failures were labelled `errored` rather than silently
scored as gaps — so this degrades completeness, not honesty.

**Not fixed.** Recorded for the T069 fix pass.

### D2 — Deprecation warning in the summary path (low)

`LangChainDeprecationWarning: Calling .text() as a method is deprecated` fires
once per summary, attributed to `generate_report.py:129`. An earlier fix
attempted to prefer the property; the guard still calls `.text()` when the
attribute is callable, which it apparently still is on some response types.

An isolated reproduction against the generation tier produced **zero** warnings
from our code, so the trigger is not yet understood. Log noise only — no
functional impact. **Not fixed, not explained.**

### D3 — JD extraction is not reproducible (high)

Found while validating the D1 fix, not by the sweep's audit.

Parsing the *same* JD file, with the same model and `temperature=0.0`
confirmed as reaching the client, three times in one session:

| JD | counts | requirements present in all 3 |
|---|---|---|
| `mathco_ai_analyst` | 6, 6, **12** | 6 of 12 — **50% stable** |
| `ey_consulting_technology_analyst` | 12, 11, 13 | 10 of 15 — 67% stable |
| `amazon_sde1_intern` (across sweep runs) | 42, 25 | — |

The mathco variance is not noise around an average: it is two different
readings of the JD. The six requirements that appear only sometimes are
*machine learning, deep learning, NLP, computer vision, generative AI, neural
networks* — one parse treats the JD's AI-domain list as six requirements, the
other as none. EY's variance is milder and mostly formatting of the same
degree requirement.

**Why this matters more than the score wobble.** The score's denominator is
the requirement count, so a report is only as reproducible as its extraction.
Two runs of the same JD against the same resume can legitimately differ by
tens of points without anything being wrong in classification, retrieval or
scoring.

**It also contaminates the D1 measurement below.** The amazon re-run went
29.8% → 42.8%, but its requirement total went 34 → 23 at the same time, so
that delta is *not* a clean read of the retry fix. EY's extraction was stable
across the two runs, which makes its 57.1% → 41.5% the more trustworthy
signal of what recovering errored requirements actually does.

#### Attempted fix: a domain-list granularity rule

Sampling was rejected (N× quota, and it picks between readings by majority
vote rather than by a stated rule). Instead an explicit rule went into
`JD_EXTRACTION_SYSTEM`: *a comma-delimited list of distinct technical domains
is one requirement per item*, with the exact mathco AI-domain sentence as a
worked example.

Re-measured, 3 parses each, same session:

| JD | before | after | names in all 3 |
|---|---|---|---|
| `mathco_ai_analyst` | 6, 6, 12 | **12, 12, 12** | 11/13 — 85% |
| `ey_consulting_technology_analyst` | 12, 11, 13 | **54, 55, 54** | 43/68 — 63% |
| `amazon_sde1_intern` | 42, 25 | **41, 36, 47** | 23/69 — 33% |

**The rule did what it was written to do, and two other things it was not.**

**It fixed the case it targeted.** mathco is now count-stable at 12/12/12, and
all six AI domains appear every time. That was the whole point, and it holds.

**It over-applies to non-technical lists.** EY went from ~12 requirements to
~54. Inspecting one parse shows why: the single eligibility phrase
*"BE / B.Tech in IT, Computer Science or Circuit branches"* is now extracted
as **five** separate requirements — `BE`, `B.Tech`, `IT`, `Computer Science`,
`Circuit branches`. The rule says "distinct technical domains"; the model
applied it to fields of study inside one degree requirement. The prompt is
too broad as written.

This has a direct cost beyond correctness: 54 requirements is 54 classification
calls, ~3.6 minutes at 15/min for that JD alone, which pushes NFR1 further out.

**And there is a second source of variance underneath, which the rule does not
touch.** amazon is still 41/36/47 with only 33% of names appearing in all
three parses. The instability there is *naming*, not granularity — the same
requirement surfaces as `18 years of age or older` in one parse and `age 18 or
older` in another, `ability to learn and adapt` vs `adaptability`. Within any
single parse there are no near-duplicates (checked: a looser key than
`canonical_key` collapses zero pairs), so this is cross-parse rewording that
dedup cannot see, because dedup only ever runs inside one parse.

#### Narrowed rule — final measurement

The rule was scoped to technologies/tools/domains, with an explicit
counter-example for degree and eligibility phrases and a discriminating test
for ambiguous lists (*all-of* → split; *alternatives satisfying one bar* → do
not split).

| JD | no rule | broad rule | **narrowed** | names-in-all-3 |
|---|---|---|---|---:|
| `mathco_ai_analyst` | 6, 6, 12 | 12, 12, 12 (85%) | 16, 15, 14 | **58%** |
| `ey_consulting_technology_analyst` | 12, 11, 13 | 54, 55, 54 (63%) | 52, 52, 51 | **81%** |
| `amazon_sde1_intern` | 42, 25 | 41, 36, 47 (33%) | 38, 37, 33 | **53%** |

Both worked examples hold. mathco returns all six AI domains on every parse.
EY's degree line is kept whole as one eligibility requirement,
`BE/B.Tech in IT, Computer Science or Circuit branches`, instead of five
fragments.

EY's count stays near 52 rather than returning to ~12, and that is the correct
outcome: the JD really does enumerate roughly fifty technologies (`.Net`,
`Java`, `SharePoint`, `Power Platform`, `Block Chain`, `IoT`, `AR/VR`,
`Drones`, `Cloud`, `DevSecOps`, …). The original 12 was under-extraction.

**mathco regressed** on stability, 85% → 58%. Not iterated on: the brief was
to narrow once and report, not to tune until every number improved.

#### Residual: cross-parse naming variance — measured, not fixed

The remaining instability is **rewording between parses**, not granularity:
the same requirement arrives as `18 years of age or older` in one parse and
`age 18 or older` in another, `ability to learn and adapt` vs `adaptability`.

Dedup (T012) structurally cannot catch this. It runs *inside* one parse, and
within any single parse there are zero near-duplicate pairs — verified with a
key looser than `canonical_key`, which collapsed none. The duplication only
exists across parses that never meet.

**Measured stability (share of requirement names appearing in all 3 parses):**

| JD | names-in-all-3 |
|---|---:|
| `ey_consulting_technology_analyst` | **81%** |
| `mathco_ai_analyst` | **58%** |
| `amazon_sde1_intern` | **53%** |

**Deliberately not fixed.** This is model non-determinism at
`temperature=0.0`, and prompt-tuning against it is unbounded work with no
stopping criterion. It is stated as a limitation instead: **scores are
quotable as rankings, not as absolute values.**

### Not reproduced this run

The transient `string index out of range` seen once during T052 retrieval did
**not** recur across 118 classifications. Traceback capture is in place if it
returns.
## What is deliberately not counted as a defect

- **Rate-limited calls (429).** The free tier refusing a request is quota, not a bug. They are logged to `classify.rate_limited` and prefixed `RATE_LIMITED:` so they can never be mistaken for a real failure.
- **Declined rewrites.** `llama3:8b` declines ~60% of the time (`docs/fabrication_test.md`); refusing to embellish is the intended behaviour.
- **Requirements classified as gaps.** A gap is a finding, not an error.
