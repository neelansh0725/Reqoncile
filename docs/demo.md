# Demo narrative

A run order that can be followed start to finish in one sitting, built around
the one question the project exists to answer:

> Is a requirement *missing from the resume*, or *present but under-sold*?

**Budget the day before you start.** The free tier allows 500 hosted requests
per day and one requirement costs one call. The full script below is roughly
**110 calls**. Check what the day has already spent (`docs/providers.md`) — a
demo that is affordable in isolation can still fail if the day is spent.

```sh
./scripts/serve.sh                        # http://127.0.0.1:8000
cd frontend && npm run dev                # http://localhost:5173
ollama serve                              # warm it BEFORE the demo — see step 5
```

---

## 1. Lead with the objection, not the feature (2 min, 0 calls)

Do not open with the UI. Open with the table in the README:

| requirement | top retrieved chunk | similarity | verdict |
|---|---|---:|---|
| Generative AI | `projects-818d02ae` — *"Multimodal AI Content Detection System \| CNN, BERT, NLP"* | **0.406** | **gap** |
| Computer Vision | **the same chunk** | **0.220** | **weak** |

Both requirements retrieved the same chunk. The gap scored nearly twice as high
as the weak match.

**The point to land:** no cosine threshold can separate these. Admitting
Generative AI at 0.406 admits Computer Vision at 0.220; rejecting 0.220 rejects
the correct weak match and keeps the wrong one. Similarity ranks topical
proximity, not evidential support.

That is why there is a model in the loop, and it is the whole justification for
the architecture. Everything after this is consequence.

## 2. The single-JD run (5 min, ~19 calls)

MathCo, in the UI. While it runs, say what it is doing: one model call per
requirement, paced to the free-tier quota.

When it lands, go to **Generative AI (gap)** and **Computer Vision (weak)** and
read the two justifications aloud. This is SM2, live
(`docs/success_metrics.md`).

> Computer Vision is weak because the resume describes detecting fake *images*
> with a CNN — that genuinely is computer vision. The label is missing, not the
> experience.
>
> Generative AI is a gap because the resume shows *discriminative* models.
> Generating content is a different capability. Adjacent subject matter is not
> evidence.

## 3. "How do you know it isn't hallucinating?" (4 min, 0 calls)

This is the question that decides whether the project reads as serious. Answer
it structurally, not reassuringly.

Open `schemas.py` and show `RewriteDraft`. **It has no `source_chunk_id` and no
`original_text` field.** The pipeline attaches those from retrieved evidence,
so the model *cannot* detach a suggestion from its source line. Tested in T042
with a model returning unrelated text — the citation still resolved correctly.

Then the measured claim: **0 unflagged fabrications across 14 deliberately
baited rewrite attempts** (`docs/fabrication_test.md`). And the honest cost
alongside it: `llama3:8b` declines roughly 60% of rewrites, so the bias runs
safe but loses recall.

Then the limitation, unprompted — this is the part that earns trust: **the
grounding check is lexical and structural, not semantic.** It catches invented
figures, entities, scale and seniority claims. It cannot catch inflation
phrased entirely in new words.

## 4. Multi-JD comparison (5 min, ~55 calls)

Three JDs: Advantest, Osfin, NSE Technology Operations.

Expect `60.7% / 44.4% / 20.8%`. Say what this mode does and does not claim:

> It separates strong fits from weak ones. It does **not** resolve fine-grained
> rank between JDs of similar strength — measured across a full re-run,
> Kendall's tau +0.63, 22 of 27 pairwise orderings preserved.

Then point at `RankedJD.tied_with` and the dashed border in the UI: **the
feature was built to report ties because the measurement said fine-grained rank
is not resolvable.** The measurement changed the design.

The strongest thing available here is the pre-registration: the manual ranking
was committed to git (`938cd42`) *before* the comparison ran, and the system
matched it exactly (`docs/comparison_eval.md`).

## 5. Interview prep (4 min, 0 hosted calls)

**Warm Ollama first.** A cold `llama3:8b` took over ten minutes to return one
gap — 4.6 GB loading from disk. Warm, it is ~20s per gap.

Run prep on the gaps. Then show the finding that matters:

> Given an explicit instruction never to write in the first person, *with* a
> worked bad example, `llama3:8b` appended `"For example, 'In my previous role,
> I worked with data visualization tools…'"` to every note.

That is a memorisable line asserting a role the resume does not evidence — the
exact thing FR23 forbids. **The prompt did not stop it. The schema validator
did**, rejecting all three.

Same lesson as step 3, reached independently: a safety property enforced only by
asking nicely is not a property.

Report the rate honestly: 2 of 12 baseline attempts, 2 of 2 caught, 0 leaked.
After one prompt fix, 12/12 clean — *and* say that under the baseline rate,
12 clean runs has an ~11% chance of happening by luck, so the guard is what
holds, not the prompt.

## 6. Version diffing (5 min, ~43 calls, or use the recorded run)

Two resume versions, one JD. Expect:

```
Net improvement: 1 requirement stronger, 20 unchanged. Score 64% → 66% (+2 points).
  ↑ Vector databases                gap → matched
```

Explain the design decision, because it is the most interesting one in this
mode: **the JD is parsed once and shared across both versions.** Extraction is
not reproducible, so two parses would produce a diff contaminated by extraction
noise *that looks exactly like resume progress*.

Then the negative result, which is better material than the positive one:
**applying Reqoncile's own rewrite suggestions moved nothing.** The classifier
held `Software engineering` at weak because a skills-list claim stated more
explicitly is still a skills-list claim. The system does not game its own
score.

## 7. Close on what is not true (3 min, 0 calls)

Open `docs/defects.md` and pick two. The best pair:

**D7 — the model never honoured `temperature=0.0`.** The configured reasoning
model ignores the parameter; the provider says so on every call. This was found
by noticing that the same resume returned `Python: weak` in one run and
`Python: matched` in another on byte-identical input. It corrects an assumption
that ran under three earlier findings, and it means every measurement in the
project is one sample from a distribution.

**The retracted embedding claim.** `bge` was adopted on a 5/7-vs-4/7 result,
then re-measured strictly — counting only chunks that genuinely evidenced the
requirement — and came out **4/7 for both**. The change was reverted and the
claim withdrawn.

**The line to end on:** every number in this repository has a document behind
it saying how it was measured and what it does not cover. Several say the first
answer was wrong.

---

## Total: ~30 minutes, ~117 hosted calls

## If something breaks mid-demo

That is a feature, and say so. NFR3 means one failed requirement does not fail
the report — it is recorded as `errored`, excluded from the score, and shown as
such. **A failure is never silently converted into a gap**, because claiming a
gap that was never assessed is a fabricated finding.

If the daily quota lands, show the error: `quotaId` distinguishes
`...PerMinute...` (slow down) from `...PerDay...` (stop). That distinction cost
a nine-JD run to learn (`docs/providers.md`).
