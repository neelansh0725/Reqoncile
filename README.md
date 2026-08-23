# Reqoncile

An agentic RAG system that compares a resume against a job description and
produces a structured alignment report: a match score, requirements sorted
into Matched / Weak / Gap, grounded rewrite suggestions for the weak ones, and
an eligibility checklist it deliberately refuses to assess.

The design question it exists to answer is narrow and specific:

> Is a requirement *missing from the resume*, or *present but under-sold*?

Those need different responses — a gap should be stated plainly, an
under-communicated skill should be rewritten — and telling them apart is the
part that cannot be done by counting keywords.

> **Status: v1.2 — all three v1.1 feature modes shipped.** Multi-JD comparison
> (FR17–FR20), interview prep for gaps (FR21–FR23), and resume version diffing
> (FR24–FR27), each validated against its success metric and each with its
> limitations measured: `docs/comparison_eval.md`, `docs/interview_prep.md`,
> `docs/version_diff.md`. Two defects found while validating them are recorded
> rather than quietly fixed — including **D7, that the reasoning model never
> honoured `temperature=0.0` at all**, which corrects an assumption running
> under three earlier findings.
>
> **On the ranking claim (v1.1, unchanged).** Reqoncile reliably separates
> strong-fit JDs from weak-fit ones; it does not resolve fine-grained rank
> among JDs of similar strength. Across a full re-run with the extraction rule
> applied, the weakest-fit JDs held their exact positions — ranks 6, 7 and 8
> were unchanged, as was rank 4 — while the top four reordered among
> themselves within a 10-point score band. Kendall's tau between the two
> rankings is **+0.63**, with **22 of 27** pairwise orderings preserved.

---

## Why not just use cosine similarity?

This is the concrete answer, taken from a real run
(`run_20260817T011139_60db1ef5`, MathCo JD).

One sentence in that JD lists six AI domains. Two of them resolved like this:

| requirement | top retrieved chunk | similarity | verdict |
|---|---|---:|---|
| Generative AI | `projects-818d02ae` — *"Multimodal AI Content Detection System \| CNN, BERT, NLP"* | **0.406** | **gap** |
| Computer Vision | **the same chunk** | **0.220** | **weak** |

**Both requirements retrieved the same top chunk, and the gap scored nearly
twice as high as the weak match.**

- *Computer Vision* is a **weak match** because the resume describes detecting
  fake **images** with a CNN. That genuinely is computer vision work — the
  label is missing, not the experience. A rewrite can fix that.
- *Generative AI* is a **gap** because the resume shows *discriminative*
  models, which classify whether content is fake. Generating content is a
  different capability, and nothing evidences it. Adjacent subject matter is
  not evidence.

Any similarity threshold that admitted Generative AI at 0.406 would also admit
Computer Vision at 0.220; any threshold that rejected 0.220 would reject the
correct weak match while keeping the wrong one. **Similarity ranks topical
proximity, not evidential support.** Separating them requires reading what the
text actually says.

Measured more broadly (`test_data/retrieval_notes.md`): requirements genuinely
absent from the resume score **0.123–0.374**, and correct paraphrase matches
score **0.195–0.402**. The ranges overlap almost completely.

---

## What it does

```
JD ──▶ extract requirements (LLM, structured output)
         └─▶ split off eligibility ──────────────────────┐  never classified
       ▼                                                 │
    classifiable requirements                            │
       │                                                 │
Resume ──▶ normalise ──▶ chunk ──▶ embed ──▶ Chroma      │
                                      │                  │
       └──────────────────────────────┴──▶ hybrid retrieval (dense + BM25)
                                             │
                              per requirement ▼
                                    classify: matched / weak / gap
                                             │
                          weak only ─────────┴──▶ rewrite ──▶ grounding check
                                             │
                                             ▼
                              score · summary · report (JSON + Markdown)
```

**Honesty constraints, enforced in code rather than asked for in a prompt:**

| Constraint | How it is enforced |
|---|---|
| Gaps are never rewritten (FR12) | `suggest_rewrite` raises on any label but `weak` |
| Every rewrite traces to one resume line (FR11) | `RewriteDraft` — the schema the model fills — has no `source_chunk_id` and no `original_text` field. The pipeline attaches them from retrieved evidence, so the model cannot detach a suggestion from its source. |
| A verdict must cite evidence (FR8) | Pydantic validator: `matched`/`weak` without evidence is rejected; `gap` *with* evidence is rejected |
| Cited evidence must be real | Chunk ids the model was never shown are dropped; a verdict left with no valid citation degrades to `gap` |
| Eligibility is never scored | Location, degree and work authorisation are split out before classification and reported as an unassessed checklist |
| A failed requirement is not a gap | It is recorded as `errored` and excluded from the score — claiming a gap we never assessed would be a fabricated finding |

---

## Setup

Requires Python 3.14 and Node 20+.

```sh
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then add GOOGLE_API_KEY
```

**Reasoning tier — Google Gemini (free).** Get a key at
<https://aistudio.google.com/apikey>. This is the only credential the core
pipeline needs.

**Generation tier — Ollama (local, free).** Only rewrites and the summary use
it; the core path runs without it.

```sh
# https://ollama.com/download
ollama pull llama3:8b
```

Verify both:

```sh
./.venv/bin/python scripts/check_providers.py --live
```

### Run it

```sh
# CLI
./.venv/bin/python scripts/run_pipeline.py \
    test_data/sample_jds/mathco_ai_analyst.txt \
    test_data/resumes/Best_withoutphoto.pdf

# API + UI
./scripts/serve.sh                       # http://127.0.0.1:8000
cd frontend && npm install && npm run dev # http://localhost:5173
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Status plus which model backs each tier |
| `POST /analyze` | JD + resume text → full report, as JSON **and** rendered Markdown |
| `POST /compare` | 2–3 JDs + one resume → per-JD reports plus a ranking that reports ties (FR17–FR20) |
| `POST /diff` | One JD + two resume versions → what moved between them (FR24–FR27) |
| `POST /interview-prep/{run_id}` | Questions for a completed run's gaps, and what an honest answer covers (FR21–FR23) |
| `POST /upload-resume` | PDF → extracted text, for the user to check before analysing |
| `GET /trace/{run_id}` | The classifier's reasoning trace: what was retrieved, what was cited, what was rejected (FR16) |
| `GET /docs` | Generated OpenAPI docs |

Worked examples with real payloads: `docs/api_examples.md`.

---

## Live demo, and what it does not cover

**<https://reqoncile.vercel.app>** — frontend on Vercel, API on Render's free
tier (512 MB, one shared CPU).

**All modes are verified working live:** single-JD analysis, multi-JD
comparison, resume version diffing, JD and resume PDF upload, the reasoning
trace, and interview prep for gaps.

**On speed.** Embedding, not the hosted model calls, dominates a run here: a
single analysis spends **94 of its 106 seconds** indexing the resume on this
shared CPU. Measured end to end on the deployed instance:

| request | wall clock |
|---|---:|
| `POST /analyze` | ~106s |
| `POST /compare` (2 JDs) | ~152s |
| `POST /diff` (2 resume versions) | ~257s |

Comparison used to re-index the *same* resume once per JD and never returned
at all; chunks already present in a collection are no longer re-embedded.
Diffing indexes two genuinely different resumes, so it cannot benefit the same
way and stays the slowest mode. Expect roughly 100–260s per request on this
tier. The free instance also sleeps when idle, so the first request after a
pause pays a cold start on top.

## The three v1.2 modes

Each is a thin layer over the single-JD pipeline, per the PRD's own constraint
(FR20, FR25): if one had needed new reasoning capability, that was the signal to
cut scope rather than add complexity.

**Compare up to 3 jobs** — runs the unchanged pipeline per JD, then one ranking
call. **The ranking reports ties.** That is not hedging: v1.1 measured that this
system separates strong fits from weak ones but cannot resolve rank between JDs
of similar strength, so `RankedJD.tied_with` exists and the prompt is told to
use it. The measurement changed the design rather than being written around.

**Prepare for the gaps** — 2–3 interview questions per Gap, each with a note on
what an honest answer must *cover*. FR23's ban on fabricated sample answers lives
in the schema: a validator rejects first-person phrasing in that note. It caught
a real violation immediately — given an explicit instruction not to, `llama3:8b`
appended *"For example, 'In my previous role, I worked with…'"* to every note.
The prompt did not hold; the validator did.

**Compare two resume drafts** — one JD, two versions, showing what moved.
**The JD is parsed once and shared across both runs.** Extraction is not
reproducible, so two parses would produce a diff contaminated by extraction
noise that looks exactly like resume progress. A score delta is withheld
entirely whenever the two versions did not score the same requirement set.

## Design decisions worth defending

**LangChain, deliberately.** Its structured-output binding is what makes
`ClassificationVerdict` a validated object rather than parsed prose, and the
provider abstraction is what let the whole stack move from Anthropic to
Gemini + Ollama by changing config.

**Two tiers, split by task difficulty.** Classification is the reasoning core
and runs on the hosted tier. Rewriting only rephrases text already retrieved
and judged, so it runs on a local 7–8B model — permanently free, and it does
not compete for the hosted quota.

**Hybrid retrieval.** Dense embeddings miss chunks whose meaning sits in one
verb buried under proper nouns: *"Presentation skills"* against *"Hackathons:
Smart India Hackathon (SIH) 2025 — Built and **pitched** the SafeEdu
platform"* sat at **rank 38 of 45** under three different embedding models.
BM25 with Porter2 stemming finds it immediately. Lexical hits are **appended**
to the dense top-k rather than fused: Reciprocal Rank Fusion was tried and
rejected because re-ranking can *evict* a correct dense hit — it rescued
"Presentation skills" but dropped a correct Docker match out of top-5, and no
weighting kept both.

**The grounding check is code, not a prompt instruction.** A safety property
enforced only by asking nicely is not a property. Across 14 rewrite attempts
against deliberately baited cases, there were **zero unflagged fabrications**
(`docs/fabrication_test.md`).

---

## Limitations

Stated plainly, because each one bounds a claim above.

**The grounding check is lexical and structural, not semantic.** It catches
invented entities, figures, seniority and scale claims — the fabrications that
matter most, and the ones most likely to collapse in an interview. It **cannot**
catch inflation phrased entirely in new words. A suggestion that overstates
using vocabulary absent from both the original and the requirement will pass
clean.

**Extraction is not fully reproducible, and `temperature=0.0` is not actually
in force.** The configured reasoning model, `gemini-3.5-flash-lite`, **ignores
the `temperature` parameter** — the provider library says so on every call. It
is selected for its daily quota, which is the only free option large enough to
run this project (`docs/providers.md`), not for its sampling behaviour. So the
variance below is ordinary sampling, not a temperature-0 model misbehaving.
Parsing the same JD three times produces requirement names that agree:

| JD | names present in all 3 parses |
|---|---:|
| `ey_consulting_technology_analyst` | **81%** |
| `mathco_ai_analyst` | **58%** |
| `amazon_sde1_intern` | **53%** |

For mathco and amazon that means **roughly half of requirement names vary
between parses** — the same requirement surfaces as `18 years of age or older`
in one run and `age 18 or older` in the next. This is cross-parse rewording,
which de-duplication structurally cannot catch: dedup runs inside a single
parse, and within any single parse there are zero near-duplicates.

Since the requirement count is the score's denominator, **absolute match
scores are not quotable.** A score is specific to the run that produced it.

**Classification can vary run to run on byte-identical input**, but the
variance is concentrated, not pervasive. The same resume and JD returned
`Python: weak` in one run and `Python: matched` in another, citing overlapping
evidence both times (`docs/defects.md`, D7).

The eval set was then run three times to characterise the spread: **17/20 every
time, with all 20 items receiving the identical verdict in all three runs** —
and the justification *wording* differed on every item, so generation was
sampling and the decisions were stable anyway. That rules out widespread
per-item instability (all 20 appearing stable has probability ≈2×10⁻⁶ if items
flipped at 20%). It does not rule out occasional flips on requirements sitting
on the matched/weak boundary, which is what D7 caught. See
`docs/classifier_eval.md`.

The narrower claim — that the *ordering* of JDs against one resume survives
extraction volume moving — **has since been measured**, and only partly held:
coarse separation survived, fine-grained rank did not (see the status note
above, and `docs/defects.md` D3 addendum). The claim in this README is scoped to
what survived.

**A concrete instance of that:** the MathCo demo run scores **44.4%**, while
the same JD scored **50.0%** in the earlier sweep. Nothing about the resume or
the classifier changed — the granularity rule changed how many requirements
that JD yields, and the denominator moved with it. Do not read the two numbers
as a regression.

**One of the nine sample JDs cannot be scored at all.**
`zs_decision_analytics_associate` extracts bimodally: three parses returned
**0, 0 and then 5** classifiable requirements (1, 1 and 6 extracted, of which
the first two were eligibility-only and therefore never classified). With
nothing classifiable there is no score, so it is excluded from the ranking
above rather than represented by whichever sample happened to look usable.

Its collapse mode is worth naming: it is the most prose-heavy JD in the set,
with a requirements section written as five soft-skill bullets and no
technical list. Extraction either reads those bullets as requirements or reads
the whole section as narrative.

**What the ranking measurement does and does not cover.** It compares two
runs, not many. Rank movement did **not** track extraction volume in the way
one might expect: EY's requirement count grew fivefold (10 → 50) and its rank
did not move, while `zs_bts` grew only 1.3× (10 → 13) and moved three places.
Whatever drives the residual movement, it is not simply the denominator.

**`llama3:8b` declines roughly 60% of rewrites.** The bias runs in the safe
direction, but some rewrites a candidate would benefit from are refused
(`docs/fabrication_test.md`).

**A rewrite cannot move a verdict that depends on *where* the evidence sits.**
Rewrites rephrase the line the evidence already occupies. If that line is in
SKILLS, saying it more explicitly does not change the kind of evidence, and the
classifier correctly holds the verdict at weak. Applying Reqoncile's own
suggestions to the resume moved **nothing** — measured, not assumed
(`docs/version_diff.md`). To move such a requirement, the experience has to
appear in a project or experience bullet.

**The test suite covers the honesty constraints, not the pipeline.** 95 tests
(`pytest`, ~9s, no network and no quota) pin the validators and gates that
carry the claims on this page: the FR23 first-person guard, gap-with-evidence
rejection, the Weak-only and Gap-only gates, chunk-id stability, run-id path
safety, the D6 concurrency fix, and the rule that a score delta is withheld
when denominators differ. One test asserts a documented *limitation* — that the
grounding check misses inflation phrased in new words — so the README cannot
quietly start over-claiming.

**What is not covered:** retrieval quality, classification accuracy, and
anything requiring a model call. Those are measured by the scripts behind
`docs/`, re-run by hand, and are not regression-guarded.

**Interview-prep questions are templated.** A "how do you stay current with…"
question appeared in **6 of 6** gaps, and 15 of 18 answer-notes open with the
same three words. Within a gap the questions differ; across gaps one slot is
predictable, so the real yield is closer to two useful questions per gap than
three. One question in eighteen also *presupposed* experience the classifier had
just called a gap (`docs/defects.md`, D5).

**Two retrieval failures are a known ceiling.** *"Model deployment"* against
*"Designed a FastAPI + React application supporting real-time and batch
scoring"* has no shared term for BM25 and is dominated by tool names for the
embedding. The link is inferential; neither retriever bridges it
(`docs/classifier_eval.md`).

**NFR1's ~30s budget does not hold.** Measured across 23 runs, **2 came in
under 30s** — and three *other* 9-requirement runs took 54–57s, so the budget is
unreliable even at the smallest JD in the set. The free tier allows 15
requests/minute against one call per requirement, which puts a hard floor of
~60s on anything past 15 requirements. Realistic figures: **15–60s for 9–15
requirements, 60–90s to 24, minutes beyond.** Diff mode is two full pipelines by
construction — budget 5–15 minutes. Meeting NFR1 would mean batching
requirements per call, which costs the per-requirement error isolation and the
reasoning trace; that trade has not been made (`docs/latency.md`).

---

## Measured results

| What | Where |
|---|---|
| Classifier accuracy: **17/20 on a labelled set, reproduced 3/3 runs with identical per-item verdicts**; gap recall 7/7 | `docs/classifier_eval.md` |
| Retrieval: 8/8 paraphrase probes, 7% mean lexical overlap | `test_data/retrieval_notes.md` |
| Fabrication: 0 unflagged across 14 baited rewrites | `docs/fabrication_test.md` |
| SM2 / SM3 demonstrated end to end | `docs/success_metrics.md` |
| SM4: ranking vs a manual ranking committed *before* the run | `docs/comparison_eval.md` |
| SM5: interview prep — 2/12 fabrication attempts, 2/2 caught, 0 leaked | `docs/interview_prep.md` |
| SM6: a gap moving to matched between two real resume versions | `docs/version_diff.md` |
| Latency and the NFR1 budget | `docs/latency.md` |
| Defects found, fixed, and deliberately not fixed | `docs/defects.md` |
| Free-tier quotas, measured | `docs/providers.md` |
| Test suite: what it pins, and the mutation check it failed | `docs/testing.md` |
| A 30-minute demo script | `docs/demo.md` |

## Layout

```
parsing/     JD extraction, resume ingestion, chunking, salvage
retrieval/   embeddings, Chroma, BM25 lexical retrieval
agent/       classifier, rewriter, grounding check, prompts
reporting/   scoring, report assembly, Markdown rendering
backend/     FastAPI
frontend/    React + Vite
scripts/     CLI entry points and evaluation harnesses
tests/       offline tests for the honesty constraints (no quota)
docs/        measurements and findings
```
