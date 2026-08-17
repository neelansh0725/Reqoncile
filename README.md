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
| `POST /upload-resume` | PDF → extracted text, for the user to check before analysing |
| `GET /trace/{run_id}` | The classifier's reasoning trace: what was retrieved, what was cited, what was rejected (FR16) |
| `GET /docs` | Generated OpenAPI docs |

Worked examples with real payloads: `docs/api_examples.md`.

---

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

**Extraction is not fully reproducible at `temperature=0.0`.** Parsing the same
JD three times produces requirement names that agree:

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

The intended narrower claim — that the *ordering* of JDs against one resume is
stable even when extraction volume moves — is **not yet measured under the
current extraction rule.** The nine-JD re-ordering run that would establish it
exhausted the provider's daily quota after three JDs, so six returned no
result. Treat the ranking as plausible and unverified rather than
demonstrated. See `docs/defects.md` (D3).

**A concrete instance of that:** the MathCo demo run scores **44.4%**, while
the same JD scored **50.0%** in the earlier sweep. Nothing about the resume or
the classifier changed — the granularity rule changed how many requirements
that JD yields, and the denominator moved with it. Do not read the two numbers
as a regression.

**`llama3:8b` declines roughly 60% of rewrites.** The bias runs in the safe
direction, but some rewrites a candidate would benefit from are refused
(`docs/fabrication_test.md`).

**Two retrieval failures are a known ceiling.** *"Model deployment"* against
*"Designed a FastAPI + React application supporting real-time and batch
scoring"* has no shared term for BM25 and is dominated by tool names for the
embedding. The link is inferential; neither retriever bridges it
(`docs/classifier_eval.md`).

**NFR1's ~30s budget holds only for a demo-length JD on a warm process.** The
free tier allows 15 requests/minute and classification is one call per
requirement, so a 50-requirement JD takes minutes by arithmetic
(`docs/latency.md`).

---

## Measured results

| What | Where |
|---|---|
| Classifier accuracy: 17/20 on a labelled set; gap recall 7/7 | `docs/classifier_eval.md` |
| Retrieval: 8/8 paraphrase probes, 7% mean lexical overlap | `test_data/retrieval_notes.md` |
| Fabrication: 0 unflagged across 14 baited rewrites | `docs/fabrication_test.md` |
| SM2 / SM3 demonstrated end to end | `docs/success_metrics.md` |
| Latency and the NFR1 budget | `docs/latency.md` |
| Defects found, fixed, and deliberately not fixed | `docs/defects.md` |
| Free-tier quotas, measured | `docs/providers.md` |

## Layout

```
parsing/     JD extraction, resume ingestion, chunking, salvage
retrieval/   embeddings, Chroma, BM25 lexical retrieval
agent/       classifier, rewriter, grounding check, prompts
reporting/   scoring, report assembly, Markdown rendering
backend/     FastAPI
frontend/    React + Vite
scripts/     CLI entry points and evaluation harnesses
docs/        measurements and findings
```
