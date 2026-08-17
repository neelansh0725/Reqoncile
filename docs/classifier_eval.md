# Classifier evaluation (T036–T038)

Eval set: 20 hand-labelled requirement/resume pairs (`test_data/eval_set.json`)
against `Best_withoutphoto.pdf`.

## Current result

`gemini-3.5-flash-lite`, after T038 tuning and T026a hybrid retrieval:
**17/20 = 85%**, 0 errored, 64s.

| expected | → matched | → weak | → gap |
|---|---:|---:|---:|
| matched (8) | 7 | 1 | 0 |
| weak (5) | 0 | 3 | 2 |
| gap (7) | 0 | 0 | **7** |

Progression: 15/20 baseline → 16/20 (prompt rule) → **17/20** (hybrid
retrieval). Weak recall, the class of concern, went 2/5 → 2/5 → **3/5**.

The three remaining errors are **two hard retrieval failures and one
contestable label**. There is no remaining case where the classifier had the
evidence in front of it and reasoned wrongly.

### The retrieval ceiling

Both remaining retrieval failures share a property that neither retriever can
overcome:

| requirement | evidencing chunk | why both retrievers miss |
|---|---|---|
| Model deployment | "Designed a FastAPI + React application supporting real-time and batch scoring" | contains no form of *deploy* — nothing for BM25; dominated by tool names — nothing for the embedding |
| Statistical analysis | "Built a credit risk model … using LightGBM with class imbalance handling" | contains no form of *statistic* |

The link is **inferential**, not lexical or distributional: a reader knows
that serving a model over an API *is* deployment. Bridging it requires
reasoning about the requirement before retrieving — query expansion via the
LLM — which costs a model call per requirement against a rate-limited free
tier. Not worth it for two cases; recorded as the known ceiling instead.

**gap recall is 7/7.** That is the class the honesty constraints care about
(G5, R2): the system never invented experience the candidate lacks. Weak
recall is 2/5, and that number needs unpacking rather than reporting.

## Every error is a downgrade

All five misclassifications move in the same direction — the model is more
conservative than the label. Zero upgrades.

| requirement | label | model | cause |
|---|---|---|---|
| Model deployment | weak | gap | evidence never retrieved (rank 41/45) |
| Presentation skills | weak | gap | evidence never retrieved (rank 38/45) |
| Statistical analysis | weak | gap | evidence never retrieved (rank 16/45) |
| Docker | matched | weak | **genuine model error** |
| Version control | matched | weak | contestable label — model may be right |

That splits into three different problems, and only one of them is the
classifier reasoning badly.

**Three of five are retrieval starvation, not misjudgement.** The chunk a human
would cite never reached the classifier, so it judged on excerpts that
genuinely did not evidence the requirement. Answering "gap" there is *correct
reasoning on the input it was given*. Fixing these means fixing retrieval.

**One is a real model error.** For Docker, retrieval surfaced
"Orchestrated the pipeline with Apache Airflow … running in a containerized
Docker [environment]" at rank 2 — demonstrated use, not a list mention — and
the model still said weak, reasoning that the resume "under-communicates
hands-on use". It had the evidence and read it too conservatively.

**One is arguably a bad label.** For Version control, retrieval returned only
`Tools: Git, GitHub …` — a bare skills-list entry. Nothing anywhere shows Git
being *used* (branching, reviews, releases). "weak" is a defensible reading;
my "matched" label was generous.

So the classifier's reasoning-error rate on adequately-retrieved evidence is
closer to **1/20 than 5/20**. The 75% figure is as much a measure of retrieval
recall and label quality as of classification.

## Changes made

**1. Embedding model — tried `bge-base-en-v1.5`, then reverted.** An initial
measurement showed bge at 5/7 top-5 recall vs 4/7 for MiniLM and mpnet, and it
was adopted on that basis. **That measurement was wrong.** It accepted any of
several "acceptable" chunks as a hit, including marginal ones. Re-measured
against only the chunk that genuinely evidences each requirement:

| model | dim | strict top-5 recall |
|---|---:|---:|
| `all-MiniLM-L6-v2` | 384 | 4/7 |
| `bge-base-en-v1.5` | 768 | 4/7 |

bge does not win — it **trades** cases, retrieving the evidence for
Statistical analysis (rank 16 → 4) while losing Stakeholder communication
(rank 1 → outside top-5). The end-to-end eval confirmed it: 75% before, 75%
after, with the errors merely rearranged. Reverted to MiniLM, which is half
the dimensions and faster to load. The lesson is about the metric, not the
model: a lenient hit criterion manufactured a result that a stricter one and
the end-to-end eval both refuted.

**2. Explicit matched-vs-weak rule in the prompt.** The boundary was
under-specified, which is what Docker and Version control disagreed on. Now
stated directly: named only in a SKILLS list → weak; shown *being used* in
EXPERIENCE or PROJECTS → matched, even if also listed. A hypothesis worth
re-testing, not a proven fix.

**3. Hybrid retrieval (T026a).** BM25 + Snowball stemming, appended to the
dense results. Strict top-5 recall 4/7 → 5/7; end-to-end 80% → 85%.

Two design decisions were forced by measurement:

- **A hand-rolled stemmer was not good enough.** Single-pass suffix stripping
  collapsed 3 of 9 target pairs — it cannot reconcile `orchestration` with
  `orchestrated`, which needs Porter's multi-step ATION→ATE→'' chain.
  Snowball manages 7/9 and over-stems none of the technical terms that matter
  (java/javascript, react/reactive, docker/dock stay distinct).
- **Reciprocal Rank Fusion was tried and rejected.** RRF re-ranks, so a chunk
  BM25 scores highly can *evict* a correct dense hit. Fusing rescued
  "Presentation skills" but dropped the Docker probe out of top-5; weighting
  the dense ranking more heavily merely reversed which one broke (8/8 probes
  + 4/7 targets, vs 7/8 + 5/7). No weight kept both. Appending lexical hits
  to the dense top-k instead is *strictly additive* — every dense result
  survives by construction, so a rescue can never cost a hit. The price is a
  slightly larger classifier context, which is the better trade.

Lexical-only hits carry `retriever="lexical"` and render as `keyword match`
rather than `similarity 0.000`, which would otherwise read to the model as
"no match at all" on exactly the evidence the embedding failed to surface.

**A rejected change, recorded so it is not retried.** The first diagnosis was
that retrieval queried on the requirement *name* alone and should include
`source_text`. Measured: **no effect** — 4/7 either way, and `source_text`
alone also 4/7. Raising `top_k` does not help either; the missed chunks sit at
ranks 16, 38 and 41 of 45. They are not near-misses.

## What the remaining retrieval failures actually are

Dense retrieval cannot bridge these two:

- "Presentation skills" → *"Hackathons: Smart India Hackathon (SIH) 2025 –
  Built and pitched the SafeEdu disaster safety platform to a panel of
  judges"*
- "Model deployment" → *"Designed a FastAPI + React application supporting
  real-time and batch scoring"*

Both target chunks are dominated by proper nouns (SIH, SafeEdu, CodeClash,
FastAPI, React) that swamp the one verb carrying the meaning — `pitched`,
`supporting … scoring`. A single averaged vector cannot represent both the
named entities and the buried predicate, which is why three different
embedding models all fail identically.

This needs a lexical retrieval component (BM25) unioned with the dense
results — `pitched`/`presented` would match "Presentation" on the token, where
the embedding will not. That is a bigger change than prompt tuning, so it is
filed as **T026a** rather than folded into T038.

## T037 — the R1 paraphrase test

Every requirement restated so it shares no vocabulary with the resume
("Docker" → "packaging an application so it runs identically on any machine").
Retrieval keys off the requirement name, so this changes what the classifier
is *given*, not merely how it reads.

**Paraphrased: 13/20 = 65%**, against 17/20 plain. Re-run after hybrid
retrieval landed: **unchanged at 65%**.

| | plain | paraphrased |
|---|---:|---:|
| matched (8) | 7 | 4 |
| weak (5) | 3 | 2 |
| gap (7) | **7** | **7** |

That hybrid retrieval helps the plain run (+5 points) and the paraphrased run
not at all is the expected result, and worth stating: BM25 needs a shared
term, and a paraphrase is *defined* as sharing no vocabulary. Lexical
retrieval rescues buried terms, never absent ones.

The headline drop is real, but the shape of it is the finding:

- **Zero false matches.** All 7 genuinely-absent requirements were still called
  gap. Stripping the keywords never caused the system to invent experience.
- **9 of 13 genuinely-present requirements were still recognised as present**
  (matched or weak) with no lexical overlap to work from. A keyword matcher
  scores approximately zero here.
- **Only three verdicts changed, and only one was truly lost.** Python and
  React degraded matched → weak: paraphrased retrieval surfaced their skills-
  list entry but not the project bullets showing use, so the new
  skills-list-only rule correctly fired. They were still recognised.
  Apache Airflow was the single collapse to gap — its paraphrase
  ("coordinating multi-step jobs on a recurring timetable with retries")
  retrieved ETL and scheduled-worker chunks but not the Airflow DAG bullet.

So the paraphrase cost is concentrated in **retrieval**, again, not in the
classifier's reading. This is consistent with the T026 finding and points at
the same fix (T026a).

**Caveat worth stating:** the paraphrases were written by the same author as
the eval labels, and 20 items is small. This is evidence against R1, not proof.

## Not yet run

- **A valid full-Flash comparison is not obtainable.** `gemini-3.5-flash`
  allows 20 requests/day, so any run is partial and the model cannot be the
  production choice regardless. The only scored flash run covered 8 of 20
  items and predates the label correction; it is not reported here as a
  comparison.
