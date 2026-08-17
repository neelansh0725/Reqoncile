# T070 — SM2 and SM3, demonstrated

Demo run: **`mathco_ai_analyst`** against `Best_withoutphoto.pdf`.
Run `run_20260817T011139_60db1ef5` — 44.4%, 98s, 7 matched / 2 weak / 9 gap,
1 eligibility item, 1 rewrite, 0 errored.

MathCo is the deliberate choice: a live application, the JD the granularity
rule (D3) was written against and verified on, and its AI-domain sentence
produces the cleanest available contrast between a gap and a weak match.

---

## SM2 — a true Gap distinguished from a Weak Match

> *"Correctly distinguishes at least one true Gap from at least one Weak Match
> in a demo run — proves the classification step is doing real reasoning, not
> just keyword counting."*

**One sentence in the JD produced three different verdicts.** After the
granularity rule splits it into six requirements:

| requirement | verdict |
|---|---|
| Machine Learning, Deep Learning, Neural Networks, NLP | **matched** |
| Computer Vision | **weak** |
| Generative AI | **gap** |

The contrast asked for is Computer Vision (weak) against Generative AI (gap).

### Computer Vision → WEAK

Evidence cited, two chunks:

- `projects-818d02ae` — *"Multimodal AI Content Detection System | CNN, BERT,
  NLP, React, Flask"*
- `projects-d07109b0` — *"Developed a multi-model AI system to detect fake
  image, text, and audio content using CNN…"*

> The resume mentions CNNs and fake image detection in projects, which
> inherently involve computer vision tasks, but it never explicitly names
> computer vision as a skill or methodology.

**The bar it cleared:** the work is genuinely there. Detecting fake *images*
with a CNN **is** computer vision. What is missing is the label, not the
experience — which is exactly the definition of a weak match, and exactly the
thing a rewrite can fix.

### Generative AI → GAP

Evidence cited: **none**.

> The resume mentions various AI and ML topics such as CNN, BERT, and NLP, but
> nowhere evidences building or deploying Generative AI models.

**The bar it failed:** the resume shows *discriminative* models — systems that
classify whether content is fake. Generating content is a different
capability, and nothing in the document evidences it. Adjacent subject matter
is not evidence, so the honest answer is gap, and no rewrite is offered.

### Why this rules out keyword counting

The decisive detail is in the retrieval scores:

| requirement | top retrieved chunk | similarity | verdict |
|---|---|---:|---|
| Generative AI | `projects-818d02ae` (CNN, BERT, NLP) | **0.406** | **gap** |
| Computer Vision | `projects-818d02ae` (same chunk) | **0.220** | **weak** |

**Both requirements retrieved the same top chunk, and the *gap* scored nearly
twice as high as the *weak match*.** Any threshold that admitted Generative AI
at 0.406 would have admitted Computer Vision at 0.220 too — and any threshold
that rejected 0.220 would have rejected the correct weak match while accepting
the incorrect one.

This is the T026 finding (`test_data/retrieval_notes.md`) reproduced live in a
real report: similarity ranks *topical proximity*, not *evidential support*.
Separating them requires reading what the text says, which is the reasoning
step FR9 specifies and the reason there is a model in this loop at all.

---

## SM3 — a rewrite traceably grounded in real resume content

> *"At least one rewrite suggestion is traceably grounded in real resume
> content — the fact to point at if an interviewer asks 'how do you know it's
> not hallucinating gaps or matches?'"*

Requirement: **"Communicate findings, model outputs, and recommendations
clearly"** — classified **weak**, so eligible for rewrite (a gap never is,
FR12).

**1. Source line, from the retrieved evidence — not from the model.**
`projects-7c2bbee7`, resume line 52:

> Documented actionable business insights (e.g., high-revenue categories
> running negative margins in specific regions) to support data-driven
> decision-making.

Verified verbatim against `Best_withoutphoto.expected.txt` line 52.

**2. Suggestion.**

> Communicated actionable business insights to support data-driven
> decision-making

**3. Grounding check, recomputed independently of the stored result** — stored
`none`, recomputed `none`, agree.

**4. What was not added.** Every content word in the suggestion appears in the
original or in the requirement, with exactly one exception: `communicated`,
the tense change of `Documented` that surfaces the JD's own verb.

- **Digits introduced: none.** No invented percentage, duration or scale — the
  single most likely and most damaging fabrication, and the one T044 was built
  to catch.
- No tool, framework, seniority or scale claim appears that the original does
  not support.

**Why this is a structural guarantee, not a lucky sample.** `RewriteDraft` —
the schema the model fills — has **no `source_chunk_id` and no
`original_text` field**. Those are attached by the pipeline from the retrieved
evidence. The model cannot detach a suggestion from its source line even if it
tries; this was tested directly in T042 with a model returning unrelated text,
and the citation still resolved to the correct chunk.

---

## Scope of these claims

- One demo run on one JD/resume pair. SM2 and SM3 ask for existence proofs —
  *at least one* correct distinction, *at least one* traceable rewrite — and
  these are those. They are not accuracy measurements; `docs/classifier_eval.md`
  holds those (17/20 on a 20-pair labelled set).
- **Match scores are quotable as rankings, not absolute values.** Extraction is
  not fully reproducible at `temperature=0.0` (D3), so the 44.4% here is
  specific to this run. What holds across runs is the ordering between JDs.
