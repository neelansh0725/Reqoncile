# T026 — Retrieval sanity evaluation

Resume: `Best_withoutphoto.pdf` → 45 chunks, `all-MiniLM-L6-v2` (384-dim,
L2-normalised), Chroma cosine, top-k = 5.

**Result: 8/8 probes retrieved a correct chunk in top-k** (bar was ≥4/5).

## Probes were paraphrases, not keyword lookups

Each probe was written to describe a capability *without* reusing the resume's
vocabulary. Overlap is measured as the fraction of the probe's content words
(stopwords removed) that also appear in the chunk it matched.

| Probe | Rank | Similarity | Word overlap | Correctly retrieved |
|---|---:|---:|---:|---|
| "packaging software so it runs identically on any machine" | 4 | 0.195 | **0%** | Tools: … Docker … |
| "keeping a history of edits to source code" | 1 | 0.312 | 20% | Tools: Git, GitHub … |
| "understanding why a model reached a particular decision" | 2 | 0.258 | 17% | Explainable AI (XAI) techniques |
| "automatically running steps on a recurring timetable" | 1 | 0.257 | **0%** | Apache Airflow 5-task DAG |
| "making a site display correctly on a phone screen" | 1 | 0.402 | **0%** | responsive web applications |
| "restricting what each user is allowed to see" | 1 | 0.222 | **0%** | JWT auth, role-based access control |
| "able to converse in a foreign tongue" | 1 | 0.383 | **0%** | English (fluent), Japanese |
| "reducing how long a data lookup takes to return" | 1 | 0.329 | 17% | Optimized SQL queries … |

Mean overlap on correct hits: **7%**. Five of eight shared *no* content word
with the chunk they retrieved — "packaging software so it runs identically on
any machine" found Docker, and "keeping a history of edits to source code"
found Git, with no lexical bridge at all.

This is the first direct evidence against **R1** (that the system collapses
into keyword matching with extra steps). Retrieval is doing semantic work.
The R1 case is not closed — the classifier still has to reason correctly over
what retrieval hands it (T037 tests that) — but the retrieval half holds.

## The finding that matters most: a similarity threshold cannot work

Retrieval always returns its best k. It has no notion of "nothing relevant" —
so for a requirement the resume genuinely does not cover, it still returns
five chunks, ranked.

Similarities for requirements **genuinely absent** from this resume:

| Absent requirement | Top similarity | Best-ranked (irrelevant) chunk |
|---|---:|---|
| Salesforce CRM administration | 0.374 | Implemented CRUD operations … |
| Rust systems programming | 0.337 | Tools: Git, GitHub, Docker … |
| Kubernetes cluster administration | 0.278 | TeamPulse \| React, TypeScript … |
| clinical trial protocol design | 0.256 | Implemented data quality validation … |
| mechanical stress analysis | 0.123 | SRM Institute of Science and Technology … |

Absent requirements score **0.123–0.374**.
Correct paraphrase matches score **0.195–0.402**.

**These ranges overlap almost completely.** "Salesforce CRM administration"
(absent, 0.374) outscores six of the eight correct matches. Any threshold that
admits the true Docker match at 0.195 also admits every absent requirement
above it.

Two consequences, both already in the design but now measured rather than
assumed:

1. **FR9 is not implementable as a threshold.** The PRD's insistence that
   Gap-vs-Weak be a reasoning step "not a fixed threshold on similarity score
   alone" is not a stylistic preference — the numbers make thresholding
   impossible on this data. **T030 must encode this in the prompt: the model
   decides from what the retrieved text actually *says*, and the score is
   context only.**
2. **Low absolute similarity is not evidence of a Gap.** A correct match at
   0.195 and a spurious one at 0.374 mean the classifier must never be told
   "high score = present". `RetrievedChunk.similarity` is passed for context;
   the schema docstring says so explicitly.

## Caveats

- Probes and their expected targets were written by the same author as the
  chunker, on one resume. This is a sanity check, not a benchmark.
- Two probes had two acceptable targets ("Explainable AI" *or* "SHAP";
  "Airflow DAG" *or* "scheduled worker") because both genuinely evidence the
  capability. Scored as a hit for either.
- "packaging software…" landed at rank 4 of 5 — correct, but the weakest
  result. If `TOP_K` were lowered to 3 it would be missed. Worth remembering
  before tuning `TOP_K` down for latency.


---

# T026a — hybrid retrieval (added later)

Dense-only retrieval missed 3 of 7 human-identified evidence chunks, at ranks
16, 38 and 41 of 45 — not near-misses. BM25 with Snowball stemming now runs
alongside, with its hits **appended** to the dense top-k.

| | dense only | hybrid |
|---|---:|---:|
| the 8 probes above | 8/8 | **8/8** (no regression) |
| strict evidence-chunk recall | 4/7 | **5/7** |
| end-to-end classifier accuracy | 80% | **85%** |

"Presentation skills" is the case it was built for: the evidencing chunk
("…pitched the SafeEdu platform to a panel of judges") sat at dense rank 38
because proper nouns swamp the one meaningful verb. Stemming collapses
`presentation`/`presented`, and BM25 finds it immediately.

The two chunks still missed contain **no form of the requirement's words at
all** — "supporting real-time and batch scoring" for *Model deployment*,
"credit risk model using LightGBM" for *Statistical analysis*. The link is
inferential, so neither a term matcher nor a bi-encoder can bridge it. That is
the honest ceiling of retrieval here.
