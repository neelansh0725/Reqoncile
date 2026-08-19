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

> **Amended (D7):** originally titled "not reproducible at
> `temperature=0.0`". The configured model ignores `temperature`
> entirely, so that setting was never in force. The measured rates
> below are unchanged; the cause is ordinary sampling, not a
> temperature-0 model behaving strangely.

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


---

## D3 addendum — the ranking measurement (v1.1)

The nine-JD re-ordering finally ran on a full daily budget: 13.8 minutes, zero
errored requirements, zero 429s.

**The pre-registered falsification test passed.** EY was nominated in advance
as the case most likely to break the ranking claim, because the granularity
rule took its requirement count from 10 to 50. Its rank did not move: 6 before,
6 after.

| | pre-rule | post-rule |
|---|---|---|
| rank | 6 | **6** |
| score | 41.5% | 32.3% |
| requirements | 10 | **50 (5.0x)** |

**But the broader claim is only partly supported.** Of eight rankable JDs,
four held their exact position (ranks 4, 6, 7, 8), the largest move was three
places, Kendall's tau is **+0.63**, and 22 of 27 pairwise orderings survived.
Coarse separation holds; fine-grained rank does not.

**The pre-agreed fallback wording was rejected on the data.** "Stable under
classification and scoring but sensitive to extraction volume" predicts the
opposite of what happened — EY absorbed a 5x volume change without moving,
while `zs_bts` moved three places on a 1.3x change. Volume does not explain
movement, so that phrasing was not published.

### A methodological correction

`zs_decision_analytics_associate` returned one eligibility-only requirement in
two consecutive pipeline runs, and that was called "reproducible, not a fluke"
at the time. **A third parse returned 6 requirements, 5 of them classifiable.**
Two samples were not enough to distinguish a systematic failure from the
bimodal extraction already documented above, and the conclusion drawn from
them was wrong.

The JD is excluded from the ranking rather than re-run until it produced a
usable score — running until the number cooperates is sample selection, not
measurement. The claim was never published; it is recorded here because the
reasoning error is the point.


---

## D4 — Extraction rewording can change a verdict, not only a name (medium)

Found in T077, not in the T068 sweep. Recorded here because D3 as written
understates its own cause.

`osfin_implementation_engineer`, same resume, two runs twenty minutes apart:
**50.0%** then **44.4%**. Both parses produced the **same nine requirements**
and therefore the **same denominator**, so this is not the denominator effect
D3 describes.

Four requirement names were reworded between the parses. Three were inert. One
was not:

| run A | run B | verdict |
|---|---|---|
| `communication skills` | `Strong communication skills` | **weak → gap** |

Both runs retrieved the same top three chunks. The classifier read the same
evidence and applied a different bar, because the requirement it was given
carried a different adjective. Each verdict is defensible on its own input:
"strong communication skills" *is* a higher bar, and run A's justification
reaches for the word *strong* to explain why it stopped short of matched.

**Extraction is a defect here.** (Originally this read "the classifier is
not the defect" — D7 shows that is too strong: the classifier also varies
on byte-identical input.) Whether the JD's adjective
survives into the requirement name is non-deterministic at `temperature=0.0`,
and that adjective can decide a verdict.

**Deliberately not fixed**, for the same reason as D3: this is model
non-determinism at the extraction step, and the mitigations (pin the name to
verbatim JD text, or normalise intensifiers out) each trade a real cost —
verbatim names are worse to read and unusable as retrieval queries; stripping
intensifiers discards a distinction the JD actually made. Neither is obviously
right, and choosing wrongly is worse than documenting accurately.

**What it bounds.** The README already states that absolute match scores are
not quotable. That limitation is correct and now has a second, independent
mechanism behind it. It does **not** undermine the ranking claim: in the same
pair of runs `advantest_ai_engineering_intern` was identical (60.7%, 9/6/6),
osfin moved 5.6 points, and the rank order did not change
(`docs/comparison_eval.md`).


---

## D5 — An interview-prep question can presuppose experience (low)

Found in T083. FR23 is enforced on `GapQuestion.answer_should_cover`, which is
where a fabricated *answer* would appear. The `question` field has no such
guard, and one question in eighteen used it to assert experience:

> "**In your previous role, you worked on a project that required
> collaboration with stakeholders.** Can you walk me through…"

Generated for **Communication**, which the classifier had just labelled a
**gap** — so the question presupposes exactly what was found missing.

**Not fixed, and not with a lexical guard.** Questions must address the
candidate in the second person to be questions at all ("Can you walk me
through your experience with…"), so the first/second-person check that works
for the answer note would reject correct questions here. The defect is the
declarative presupposition, which is not lexically separable from a normal
question.

**Why it is rated low.** A false premise in a question is one the candidate
notices and corrects in the room. A fabricated answer is one they recite. The
FR23 guard covers the higher-harm case.

**If it is fixed later**, the honest route is a prompt rule ("ask, never
assert, that the candidate has done something") plus a re-measurement — not a
regex. One observation in eighteen is too thin to design a guard against.


---

## D6 — The BM25 stemmer was not thread-safe (high, fixed)

Found in T088, when a version diff returned `Python: weak → errored` and the
traceback landed inside `snowballstemmer`:

```
IndexError: string index out of range
  ... in find_among_b: ord(self.current[c - 1 - common])
```

`retrieval/lexical.py` held **one module-level stemmer instance**. Snowball's
stemmer keeps per-word parsing state on the object (`self.current`), and
classification fans out across threads (T034) with every requirement
tokenising its query. Concurrent calls interleave on that shared state.

**Measured.** Hammering one shared instance from 8 threads over this project's
own corpus produced **24 IndexErrors**; the identical token list
single-threaded produced **0**. An earlier attempt with a short uniform word
list also produced 0 — the bug needs enough token variety to interleave
badly, which is why it never surfaced in the T068 sweep.

**Fixed** by giving each thread its own stemmer via `threading.local()`. After
the fix: 0 failures over the same 8-thread hammer, and stemming behaviour is
unchanged (`orchestration`/`orchestrated` still collapse to `orchestr`,
`java`/`javascript` stay distinct).

**Does this invalidate earlier measurements?** No, and the reason is worth
stating rather than assuming: the exception propagates, so a corrupted stem
surfaces as an **errored requirement**, not as a silently wrong retrieval.
Errored counts were tracked throughout and were low. The failure was loud, not
quiet — it was just rare enough to be mistaken for the transport faults D1
addressed.

---

## D7 — The reasoning model never honoured `temperature=0.0` (high)

This one corrects an assumption running under D3, D4, and the classifier eval.

`config.py` sets `REQONCILE_REASONING_TEMPERATURE=0.0`. The configured model
is `gemini-3.5-flash-lite`. On **every** call, the provider library emits:

> `Model 'gemini-3.5-flash-lite' uses fixed sampling defaults; the sampling
> parameter(s) temperature will be ignored.`

Verified directly by capturing warnings around a live call while printing the
configured value: model `gemini-3.5-flash-lite`, temperature `0.0`, warning
present.

**`providers.md` documented this trap for the wrong model.** It flagged
`gemini-3.6-flash` as ignoring `temperature` and advised preferring models
that honour it "for anything the eval measures" — and then the model actually
selected, for its daily quota rather than its sampling behaviour, does not
honour it either.

### What this reframes

**D3 is mis-titled.** "JD extraction is not reproducible **at
`temperature=0.0`**" implies a deterministic setting was in force and the
model was non-deterministic anyway. It was not in force. Extraction variance
is the ordinary behaviour of a model sampling at fixed defaults. The *measured
rates* in D3 (81% / 58% / 53% name stability) stand exactly as recorded — only
the explanation changes, and it becomes less mysterious, not more.

**D4's conclusion was too narrow.** D4 said "the classifier is not the defect.
Extraction is," on the evidence that a reworded requirement drew a different
verdict. That evidence was real, but the stronger claim it implied — that the
classifier is stable given stable input — is false:

| run | resume | requirement | verdict |
|---|---|---|---|
| `run_20260818T121634` | `v1.txt` | `Python` | **weak** |
| `run_20260818T153353` | `v1.txt` (byte-identical) | `Python` | **matched** |

Same file, same JD, same requirement name, overlapping evidence chunks
(`skills-82efe95a`, `projects-db8fb933` cited both times), opposite verdicts:

> weak: "Python is listed under technical skills and mentioned in project
> titles and certifications, but the resume does not describe its active use
> in experience bullets."
>
> matched: "The resume lists Python in the skills section and shows it being
> actively used to build the LendingClub Credit Risk Prediction System."

**The classifier is non-deterministic on byte-identical input.** D4 attributed
run-to-run score movement wholly to extraction; part of it is classification.

### Not fixed, and the options are all bad

- **Switch to a model that honours `temperature`.** `gemini-3.5-flash` does —
  and allows **20 requests/day**, which cannot run a single JD (`providers.md`).
- **Set `top_k`/`top_p` instead.** Same warning covers all sampling parameters.
- **Self-consistency (sample *n*, take the majority).** Multiplies quota by
  *n* against a 500/day cap, and R4 already deferred the related
  self-critique pass to v2.

**What it costs, concretely.** Absolute scores were already non-quotable; that
limitation is unchanged and now has a third mechanism behind it. The coarse
ranking claim (v1.1) survives, having been measured *across* runs and
therefore across this variance rather than in spite of it. The classifier eval
(17/20) was a single-sample measurement when this was written. **It has since
been measured**: three consecutive runs returned 17/20 each, with identical
per-item verdicts on all 20 (`docs/classifier_eval.md`).

That narrows D7's practical impact without contradicting it. Generation is
plainly sampling — justification wording differed on every item across the
three runs — yet the verdicts held. The `Python` flip recorded above was a
different requirement instance, against a different JD, and the two findings
together suggest **variance is concentrated at matched/weak decision
boundaries rather than spread across the set**. A requirement with unambiguous
evidence stays put; one on the line does not.
