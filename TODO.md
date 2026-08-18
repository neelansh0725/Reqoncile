# Reqoncile — Build Task List

Sequential build order. Each task is atomic: one concern, one deliverable, no
task depends on a later one. Work top to bottom. Phases 1–8 are v1 and must be
solidly done before Phase 9 starts (PRD §9).

Legend: `Refs:` maps to PRD functional requirements / NFRs / risks / success metrics.

---

## Phase 0 — Foundations

- [x] **T001 — Initialize repository and directory skeleton**
  Create `git init` repo and the folder structure from TechStack §6 (`parsing/`,
  `retrieval/`, `agent/`, `reporting/`, `backend/`, `frontend/`, `test_data/sample_jds/`,
  `logs/`), each with an `__init__.py` where it is a Python package.
  *Done when:* `python -c "import parsing, retrieval, agent, reporting"` succeeds.

- [x] **T002 — Create virtualenv and pin dependencies**
  Write `requirements.txt` from TechStack §7, install, freeze exact versions.
  *Done when:* fresh venv install completes and every listed package imports.

- [x] **T003 — Write config module**
  `config.py`: load `.env`, expose LLM provider/model name, embedding model name,
  `TOP_K`, Chroma persist path, log path. Add `.env.example`; gitignore `.env`.
  *Done when:* config imports with no env vars set except the API key, using defaults.

- [x] **T004 — Write LLM client wrapper**
  Single thin module `llm_client.py` wrapping the hosted API: one `complete()` and
  one `complete_structured(schema)` entry point, with timeout and retry-on-transient.
  Every later LLM feature calls this, nothing else.
  *Done when:* a hello-world structured call returns a validated Pydantic object.
  *Status:* reasoning tier (Gemini) verified live. Generation tier (Ollama) still
  unverified — Ollama not installed; blocks nothing before Phase 4.
  *Refs:* TechStack §3

- [x] **T005 — Write JSONL run logger**
  `logging_utils.py`: append-only writer to `logs/runs.jsonl`, one JSON object per
  event with `run_id`, `timestamp`, `stage`, `payload`.
  *Done when:* two writes from separate processes both land, one object per line.
  *Refs:* FR16

- [x] **T006 — Assemble JD test data**
  Save 4–6 real placement-season JDs as plain `.txt` in `test_data/sample_jds/`,
  deliberately mixing formats (bulleted, prose, mixed).
  *Done when:* files exist and at least one is prose-only, one is heavily bulleted.
  *Refs:* FR3, SM1

- [x] **T007 — Assemble resume test data**
  Put the real resume PDF in `test_data/resumes/` plus a hand-checked
  `.txt` of its expected extracted text, to use as a parsing ground truth.
  *Done when:* both files exist and the `.txt` is verified correct by eye.

---

## Phase 1 — JD Parsing (FR1–FR3)

- [x] **T008 — Define JD schemas**
  In `schemas.py`: `Requirement` (name, category ∈ {technical, soft, eligibility},
  necessity ∈ {required, preferred}, source_text) and `ParsedJD` (list of requirements).
  *Done when:* invalid category/necessity values raise a Pydantic validation error.
  *Refs:* FR2

- [x] **T009 — Implement JD text loader**
  `parsing/jd_parser.py`: accept a file path or a raw string; normalize whitespace,
  strip page furniture, return clean text. No LLM yet.
  *Done when:* all sample JDs load and round-trip to non-empty normalized text.
  *Refs:* FR1

- [x] **T010 — Write the JD extraction prompt**
  Prompt template only, kept in `parsing/prompts.py`: instructs the model to emit one
  entry per distinct requirement, assign category and necessity, and quote the source
  line. Explicitly says not to invent requirements not present in the text.
  *Done when:* prompt file exists and renders with a JD injected.
  *Refs:* FR2

- [x] **T011 — Wire the LangChain structured-extraction chain**
  Connect loader → prompt → `llm_client.complete_structured(ParsedJD)` via LangChain's
  output parser.
  *Done when:* one sample JD returns a validated `ParsedJD` with >5 requirements.
  *Refs:* FR2, TechStack §2

- [x] **T012 — Add requirement normalization and dedupe**
  Post-process the parsed list: trim, case-normalize names, merge near-duplicates
  (e.g. "Python" and "Python programming") by simple string rules.
  *Done when:* a JD that repeats a skill in two bullets yields one requirement.

- [x] **T013 — Add JD parsing CLI**
  `scripts/parse_jd.py <path>` prints the parsed requirement list as JSON.
  *Done when:* command runs end to end on a sample JD.

- [x] **T014 — Validate the parser across all sample JDs**
  Run the CLI on every file from T006; hand-check output; write findings to
  `test_data/parser_notes.md`.
  *Done when:* every sample JD parses and known misses are written down.
  *Refs:* FR3

- [x] **T015 — Make parsing fail gracefully**
  On malformed/partial model output, return whatever requirements validated plus a
  structured warning, instead of raising.
  *Done when:* a deliberately truncated model response still yields a usable `ParsedJD`.
  *Refs:* NFR3

- [x] **T015a — Split eligibility out of the classification path**
  Added after T014 found location (`Chennai`) extracted as a required
  eligibility item. Nothing in a resume semantically matches a city name, so
  the classifier would emit a confident Gap for every such item and drag the
  match score down for reasons unrelated to fit.
  `ParsedJD.split()` partitions into `classifiable` (technical + soft) and
  `eligibility`. Eligibility items are **never classified and never scored** —
  they are reported as an unassessed checklist for the candidate to verify,
  which is the same honesty constraint as FR12/G5.
  *Done when:* partition is total and category-exact across all 9 sample JDs.
  *Measured:* removes 19/140 requirements (14%) from the classification
  fan-out; mean classifiable per JD 15.6 → 13.4.
  *Refs:* FR2, G5, NFR1

---

## Phase 2 — Resume Ingestion & Retrieval (FR4–FR6)

- [x] **T016 — Implement PDF text extraction**
  `parsing/resume_parser.py`: extract text with `pypdf`, preserving line breaks.
  *Done when:* output matches the T007 ground-truth text on the real resume.
  *Refs:* FR4

- [x] **T017 — Add plain-text resume input path**
  Same module, same return shape, for pasted text.
  *Done when:* both PDF and text inputs return the identical internal structure.
  *Refs:* FR4

- [x] **T018 — Implement section detection**
  Tag lines with the resume section they fall under (Experience, Projects, Skills,
  Education) using heading heuristics.
  *Done when:* every line in the real resume carries a section label, spot-checked.

- [x] **T019 — Implement chunking with stable IDs**
  Chunk by bullet/section into `ResumeChunk` (chunk_id, text, section, source_line_no).
  IDs must be stable across runs — later traceability depends on this.
  *Done when:* re-running chunking on the same resume produces identical chunk IDs.
  *Refs:* FR5, FR11

- [x] **T020 — Set up the embedding model loader**
  `retrieval/embed.py`: load the `sentence-transformers` model once, cached at module
  level, config-driven model name.
  *Done when:* two calls in one process load the model only once.

- [x] **T021 — Implement batch chunk embedding**
  Embed a list of chunks in one batched call; return vectors aligned to chunk IDs.
  *Done when:* embedding the real resume's chunks completes and vector count matches
  chunk count.

- [x] **T022 — Set up Chroma**
  `retrieval/vector_store.py`: persistent client at the configured path, one collection
  per resume version (named by resume hash) so version diffing later stays isolated.
  *Done when:* a collection is created and survives a process restart.

- [x] **T023 — Implement chunk upsert**
  Write chunks + vectors + metadata (section, source_line_no) into the collection,
  idempotently by chunk ID.
  *Done when:* upserting twice leaves the collection size unchanged.

- [x] **T024 — Implement top-k retrieval**
  `query(requirement_text, k)` returns the top-k chunks with similarity scores and
  full metadata.
  *Done when:* querying "Python" returns the resume's Python-bearing bullets first.
  *Refs:* FR6

- [x] **T025 — Add retrieval smoke-test CLI**
  `scripts/index_resume.py` (ingest → chunk → embed → store) and a `--query` flag to
  run one retrieval.
  *Done when:* one command takes the real resume PDF to a printed top-k result.

- [x] **T026a — Add lexical (BM25) retrieval alongside dense**
  Filed from T038. Three eval failures are retrieval starvation, not
  misjudgement: the evidencing chunk sits at rank 16/38/41 of 45 and never
  reaches the classifier. Cause is structural — chunks dominated by proper
  nouns ("Smart India Hackathon … pitched … to a panel of judges") bury the
  one verb carrying the meaning, and a single averaged vector cannot hold
  both. Three embedding models fail identically, and neither `source_text`
  enrichment nor a larger `top_k` helps.
  Union BM25 hits with dense hits before ranking, so `pitched`/`presented`
  can match "Presentation" lexically.
  *Done when:* "Presentation skills" and "Model deployment" retrieve their
  human-identified evidence chunk in top-k, with no regression on the 8
  probes in `test_data/retrieval_notes.md`.
  *Refs:* FR6, R1

- [x] **T026 — Run a retrieval sanity evaluation**
  Write 5 probe queries phrased *unlike* the resume's own wording; confirm the right
  chunks still surface. Record results in `test_data/retrieval_notes.md`.
  *Done when:* at least 4 of 5 probes retrieve the correct chunk in top-k.
  *Refs:* FR6, R1

---

## Phase 3 — Agent Classification (FR7–FR9) — *the core; budget the most time here*

- [x] **T027 — Define the classification schema**
  `Classification`: requirement, label ∈ {matched, weak, gap}, justification,
  `evidence_chunk_ids: list[str]`, retrieved_scores.
  *Done when:* a `gap` label with a non-empty evidence list is rejected by a validator.
  *Refs:* FR7, FR8

- [x] **T028 — Build the per-requirement context payload**
  `agent/classifier.py`: given one requirement, call retrieval and assemble a prompt
  payload containing the requirement, its necessity, and the top-k chunks each
  labeled with its chunk ID.
  *Amended by T015a:* iterate `ParsedJD.split().classifiable` only — eligibility
  items must never reach retrieval or the classifier.
  *Done when:* the payload for one requirement prints correctly with IDs attached.

- [x] **T029 — Write the classification prompt**
  Explicit written definitions of Matched / Weak Match / Gap, a required short
  justification quoting actual resume text, and a requirement to cite chunk IDs.
  *Done when:* prompt renders and one live call returns a valid `Classification`.
  *Refs:* FR7, FR8

- [x] **T030 — Encode the Gap-vs-Weak distinction explicitly**
  Add to the prompt (and 2–3 few-shot examples) the rule: *nothing relevant retrieved
  → Gap; relevant content retrieved but vaguely worded → Weak Match.* Similarity score
  is context, never the decision rule.
  *Done when:* a hand-built vague-but-real case returns `weak`, and a genuinely absent
  skill returns `gap`.
  *Refs:* FR9

- [x] **T031 — Validate model output against retrieved evidence**
  Reject/repair classifications citing chunk IDs that were not in the retrieved set.
  *Done when:* a forged chunk ID in a mocked response is caught.
  *Refs:* FR8

- [x] **T032 — Isolate per-requirement failures**
  Wrap each requirement's classification so an exception marks that one requirement
  as `errored` and the run continues.
  *Done when:* forcing an exception on requirement 3 of 12 still yields 11 results.
  *Refs:* NFR3

- [x] **T033 — Emit the reasoning trace**
  Log per requirement: retrieved chunks + scores, prompt, raw model output, final
  label — to `logs/runs.jsonl` under the run ID.
  *Done when:* one full run's trace is reconstructable from the log file alone.
  *Refs:* FR16

- [x] **T034 — Parallelize classification across requirements**
  Run requirements concurrently with a configurable concurrency cap.
  *Done when:* a 15-requirement JD classifies in well under the 30s budget.
  *Refs:* NFR1

- [x] **T035 — Build the labeled evaluation set**
  Hand-label 15–20 (requirement, resume) pairs drawn from real JDs with the correct
  Matched/Weak/Gap answer. Store as `test_data/eval_set.json`.
  *Done when:* the set contains at least 4 of each label.
  *Refs:* SM2

- [x] **T036 — Build the classification eval harness**
  `scripts/eval_classifier.py` runs the eval set and prints per-label accuracy and a
  confusion matrix.
  *Done when:* the harness runs and reports a baseline number.

- [x] **T037 — Run the paraphrase (anti-keyword-match) test**
  Rewrite eval requirements so they share no keywords with the resume wording; confirm
  true matches still classify as Matched.
  *Done when:* results are recorded; any keyword-dependence is documented.
  *Refs:* R1, SM2

- [x] **T038 — Tune the prompt and re-run the eval**
  Iterate on prompt/few-shots against T036/T037; record before/after numbers in
  `docs/classifier_eval.md`.
  *Done when:* accuracy improves or the plateau is documented with reasons.

---

## Phase 4 — Rewrite Suggestions (FR10–FR12)

- [x] **T039 — Define the rewrite schema**
  `RewriteSuggestion`: requirement, source_chunk_id, original_text, suggested_text,
  rationale.
  *Done when:* `source_chunk_id` is a required field that cannot be empty.
  *Refs:* FR11

- [x] **T040 — Write the rewrite prompt with the no-fabrication constraint**
  `agent/rewriter.py` prompt: surface the JD's terminology using *only* facts present
  in the supplied chunk; never add unstated tools, scale, metrics, or outcomes.
  *Done when:* one live call returns a rewrite that adds no new facts, checked by eye.
  *Refs:* FR10, R2

- [x] **T041 — Gate rewrites to Weak Matches only**
  Hard guard in code: called only for `weak`; a `gap` input raises.
  *Done when:* a unit test asserts the raise on a `gap` classification.
  *Refs:* FR12

- [x] **T042 — Attach traceability to every suggestion**
  Carry the source chunk ID and its verbatim original text through to the output object.
  *Done when:* every suggestion in a real run can be traced back to a resume line.
  *Refs:* FR11, SM3

- [x] **T043 — Add an automated grounding check**
  Post-generation check flagging capitalized entities, numbers, and tool names in the
  suggestion that do not appear in the source chunk; flagged suggestions are marked,
  not silently shipped.
  *Done when:* an injected fabricated metric is flagged.
  *Refs:* R2

- [x] **T044 — Run the fabrication boundary test**
  Deliberately feed weak matches that tempt embellishment; document what the system
  did in `docs/fabrication_test.md`.
  *Done when:* the test and its outcomes are written up.
  *Refs:* R2

---

## Phase 5 — Report Generation (FR13–FR14)

- [x] **T045 — Implement the match scoring function**
  `reporting/score.py`: weighted score over requirements — required weighted above
  preferred, Matched > Weak > Gap. Pure function, no LLM.
  *Amended by T015a:* score over `classifiable` only. Eligibility items carry no
  Matched/Weak/Gap label and must not enter the numerator or denominator.
  *Done when:* unit tests cover all-matched (100), all-gap (0), and a mixed case.
  *Refs:* FR13

- [x] **T046 — Define the report schema**
  `AlignmentReport`: run_id, score, classifications grouped by label, rewrite
  suggestions, summary text, warnings.
  *Amended by T015a:* add an `eligibility: list[Requirement]` checklist field,
  held separately from classifications and excluded from the score.
  *Done when:* a report object builds from fixture data.
  *Refs:* FR13, FR14

- [x] **T047 — Assemble the structured report**
  `reporting/generate_report.py`: take classifications + suggestions, produce the
  `AlignmentReport`. No LLM in this step.
  *Done when:* a real run's data assembles into a valid report object.
  *Refs:* FR13, FR14

- [x] **T048 — Generate the plain-language summary**
  One LLM call over the assembled report producing a short honest paragraph — strongest
  areas, real gaps, no advice to fabricate.
  *Done when:* the summary on a real run reads accurately against the data.
  *Refs:* FR13, G5

- [x] **T049 — Implement the human-readable renderer**
  Render `AlignmentReport` to Markdown/plain text for direct export.
  *Amended by T015a:* render eligibility as its own unassessed checklist
  section, visibly separate from Matched/Weak/Gap, stating plainly that these
  are for the candidate to verify.
  *Done when:* the same report renders both as JSON and as readable text.
  *Refs:* FR14

- [x] **T050 — Write the pipeline orchestrator**
  `pipeline.py`: `run_pipeline(jd_text, resume_input) -> AlignmentReport`, chaining
  parse → chunk → embed → store → classify → rewrite → report under one run ID.
  *Done when:* one function call produces a complete report.

- [x] **T051 — Run the first true end-to-end**
  `scripts/run_pipeline.py` on one real JD + the real resume.
  *Done when:* a full report is produced and read through for correctness.
  *Refs:* SM1

- [x] **T052 — Measure and fix end-to-end latency**
  Time the T051 run; if over ~30s, cut the cost (concurrency, cheaper model for
  rewrites, fewer retrieval calls).
  *Done when:* a demo-length run completes under 30s, timing recorded.
  *Refs:* NFR1

---

## Phase 6 — Backend API (FR15)

- [x] **T053 — Scaffold the FastAPI app**
  `backend/main.py` with `/health`, run via uvicorn.
  *Done when:* `/health` returns 200 locally.

- [x] **T054 — Add `POST /analyze`**
  Accepts JD text + resume text, calls `run_pipeline`, returns the report JSON.
  *Done when:* a curl call with real data returns a full report.
  *Refs:* FR15

- [x] **T055 — Add `POST /upload-resume`**
  Multipart PDF upload → extracted text response, reusing the T016 parser.
  *Done when:* uploading the real resume PDF returns correct text.
  *Refs:* FR4

- [x] **T056 — Add request/response models and error handling**
  Pydantic request models, size limits, and structured error responses that preserve
  partial results from NFR3.
  *Done when:* empty JD, oversized upload, and a forced pipeline error each return a
  sensible status and body.
  *Refs:* NFR3

- [x] **T057 — Configure CORS and the local run script**
  Allow the Vite dev origin; add `scripts/serve.sh`.
  *Done when:* a browser fetch from the dev origin succeeds.

- [x] **T058 — Manually verify the API against real data**
  Exercise all endpoints with real JD/resume via curl; record example payloads in
  `docs/api_examples.md`.
  *Done when:* every endpoint has a working recorded example.

---

## Phase 7 — Frontend (FR15–FR16)

- [x] **T059 — Scaffold the React app**
  Vite + React in `frontend/`, dev server running.
  *Done when:* the default page loads at the dev URL.

- [x] **T060 — Write the API client module**
  Typed functions for `/analyze` and `/upload-resume` against a configurable base URL.
  *Done when:* a button click round-trips to the backend and logs the report.

- [x] **T061 — Build the input form**
  JD textarea + resume paste-or-upload toggle + submit.
  *Done when:* both input modes successfully trigger an analysis.
  *Refs:* FR15

- [x] **T062 — Add loading and error states**
  Progress indicator during the run; readable error surface; partial reports still render.
  *Done when:* a forced backend error shows a message rather than a blank page.
  *Refs:* NFR3

- [x] **T063 — Build the report header**
  Overall match score plus the plain-language summary.
  *Done when:* score and summary render from a real run.
  *Refs:* FR13

- [x] **T064 — Build the requirement list view**
  Requirements grouped by Matched / Weak / Gap, each showing category, required-vs-
  preferred, and the justification.
  *Amended by T015a:* plus a separate eligibility checklist panel — no
  Matched/Weak/Gap badges on those items.
  *Done when:* a real report renders all three groups correctly.
  *Refs:* FR13

- [x] **T065 — Build the rewrite suggestion cards**
  Each card shows the original resume line beside the suggested rewrite.
  *Done when:* every card displays its source line.
  *Refs:* FR10, FR11, SM3

- [x] **T066 — Build the reasoning trace panel**
  Expandable panel for at least one requirement showing retrieved chunks, scores, and
  the model's justification.
  *Done when:* the trace opens and matches the JSONL log for that run.
  *Refs:* FR16

- [x] **T067 — Styling pass**
  Readable typography, clear color coding for the three labels, sane mobile width.
  *Done when:* the report is legible end to end without horizontal scrolling.

---

## Phase 8 — v1 Hardening

- [x] **T068 — Full end-to-end runs on all real JDs**
  Run every JD from T006 through the UI; log every defect in `docs/defects.md`.
  *Done when:* all sample JDs have been run and defects listed.
  *Refs:* SM1

- [x] **T069 — Fix the defects from T068**
  *Done when:* the defect list is cleared or each remaining item is explicitly deferred
  with a reason.

- [ ] **T070 — Verify SM2 and SM3 on a demo run**
  Confirm one run cleanly distinguishes a true Gap from a Weak Match, and that one
  rewrite is traceably grounded. Capture the screenshots.
  *Done when:* both are demonstrated and captured.
  *Refs:* SM2, SM3

- [ ] **T071 — Write the README**
  What it does, architecture diagram, setup, run instructions, and the design
  decisions worth defending (LangChain choice, no-fabrication constraint, mixed-tier LLM use).

  **API surface to document — all five endpoints:**
  `GET /health` · `POST /analyze` · `POST /upload-resume` ·
  `GET /trace/{run_id}` (added during T066 for FR16; not part of T053–T058, so
  it is easy to miss) · plus the auto-generated `/docs`.

  **Limitations that must be stated, not glossed:**
  - The grounding check (T043) is **lexical and structural, not semantic**. It
    catches invented entities, figures, scale and seniority claims; it cannot
    catch inflation phrased entirely in new words.
  - **Extraction is not fully reproducible at `temperature=0.0`.** Parsing the
    same JD three times yields requirement names that agree
    **81% (EY) / 58% (mathco) / 53% (amazon)** of the time. The cause is
    cross-parse rewording (`18 years of age or older` vs `age 18 or older`),
    which dedup cannot catch because it runs inside a single parse. Since the
    requirement count is the score's denominator, **match scores are quotable
    as rankings between JDs, not as absolute values.** Measured in
    `docs/defects.md` (D3).
  - NFR1's ~30s budget holds for a demo-length JD on a warm process only
    (`docs/latency.md`).
  - `llama3:8b` declines roughly 60% of rewrites (`docs/fabrication_test.md`).
  - Two retrieval failures are a known ceiling (`docs/classifier_eval.md`).

  *Done when:* someone else could clone and run it from the README alone.

- [ ] **T072 — Tag v1**
  *Done when:* `v1.0` tag exists on a commit where the full single-JD flow works.

> **Gate:** do not start Phase 9 until T072 is done. If time runs out here, ship v1
> alone (PRD §9).

---

## Phase 9 — Multi-JD Comparison Mode (FR17–FR20)

- [x] **T073 — Loop the pipeline over multiple JDs**
  `agent/comparator.py`: run `run_pipeline` once per JD (2–3) against one resume,
  reusing the existing pipeline unchanged.
  *Done when:* three JDs produce three independent reports in one call.
  *Refs:* FR18, FR20

- [x] **T074 — Implement the ranking step**
  Single LLM call over the N reports producing a ranked list with a one-line reason
  per rank; validated against a `JDRanking` schema.
  *Done when:* three real JDs come back ranked with reasons.
  *Refs:* FR19

- [x] **T075 — Add `POST /compare`**
  Accepts 2–3 JDs + one resume, returns per-JD scores plus the ranking.
  *Done when:* a curl call returns a complete comparison payload.

- [x] **T076 — Build the comparison view**
  Ranked JD cards with score, reason, and a link into each full report.
  *Done when:* a three-JD comparison renders and each report is reachable.
  *Refs:* FR19

- [x] **T077 — Validate ranking against manual judgment**
  Run two real placement-season JDs; check the ranking matches your own assessment.
  *Done when:* the result is recorded, agreement or disagreement explained.
  *Status:* three JDs. Manual ranking committed **before** the run (938cd42);
  system matched it exactly. `docs/comparison_eval.md`. Also surfaced D4.
  *Refs:* SM4

---

## Phase 10 — Interview Prep Mode (FR21–FR23)

- [x] **T078 — Define the gap-question schema**
  `GapQuestion`: requirement, question, `what_an_honest_answer_covers`.
  *Done when:* the schema has no field that could hold a first-person sample answer.
  *Status:* shipped as `answer_should_cover`, with a validator that rejects
  first-person phrasing — the field cannot *hold* a sample answer.
  *Refs:* FR22, FR23

- [x] **T079 — Write the interview-prep prompt**
  `agent/interview_prep.py`: generate 2–3 probing questions per Gap, plus a description
  of what an honest answer must address. Explicitly forbid drafting a first-person
  answer implying experience the candidate lacks.
  *Done when:* one live call returns valid questions with no fabricated experience.
  *Refs:* FR21, FR22, FR23

- [x] **T080 — Gate generation to Gap classifications only**
  *Done when:* a unit test asserts it refuses non-`gap` inputs.
  *Refs:* FR21

- [x] **T081 — Test the prompt against real gaps**
  Run against 3–4 real Gaps; confirm no output drifts into a memorizable sample answer;
  record in `docs/interview_prep_test.md`.
  *Done when:* all outputs pass the no-fabrication read-through.
  *Status:* six real gaps × two configs. Recorded in `docs/interview_prep.md`.
  Baseline: 2/12 attempts drafted a first-person sample answer; the schema
  caught **2/2**, leaked **0**. One prompt fix, then 12/12 clean — reported
  with the caveat that this has an ~11% chance of luck at the baseline rate.
  *Refs:* FR23, R2

- [x] **T082 — Surface interview prep in API and UI**
  Include questions in the report payload; render them under each Gap.
  *Done when:* Gaps in the UI show their questions inline.
  *Status:* `POST /interview-prep/{run_id}` rather than inside the report
  payload — prep costs ~20s per gap locally, so making every analysis wait for
  it would have broken NFR1 for a feature most runs do not need. On-demand
  button in the UI.

- [x] **T083 — Validate question plausibility**
  Check generated questions for a real Gap read as questions you'd genuinely expect.
  *Done when:* assessment recorded.
  *Status:* SM5 met, with two measured qualifications — a "how do you stay
  current" question appears in **6/6** gaps, and 15/18 notes open with the same
  three words. One question presupposed experience the classifier had just
  called a gap (**D5**).
  *Refs:* SM5

---

## Phase 11 — Resume Version Diffing (FR24–FR27)

- [x] **T084 — Implement `diff_classifications`**
  `agent/diff.py`: pure Python, match by requirement name, bucket into
  improved / regressed / unchanged. No LLM.
  *Status:* shipped as `agent/differ.py`. A fourth bucket was needed —
  `indeterminate`, for a requirement that errored on one side. Calling that
  "unchanged" would claim a stability never established.
  *Done when:* unit tests cover Gap→Weak, Weak→Matched, Matched→Weak, and unchanged.
  *Refs:* FR26, TechStack §4.3

- [x] **T085 — Compute the net-improvement summary line**
  Single summary sentence quantifying net movement plus score delta.
  *Done when:* the line is correct on a fixture with mixed movement.
  *Status:* the score delta is **withheld** whenever the two versions did not
  score the same requirement set — otherwise the line reads "net improvement,
  score down 8 points", which is denominator drift, not a finding.
  *Refs:* FR27

- [x] **T086 — Add the two-version orchestration endpoint**
  `POST /diff`: two resume versions + one JD → two independent pipeline runs (isolated
  Chroma collections, per T022) → diff result.
  *Done when:* a curl call with two real resume versions returns a diff.
  *Status:* the JD is parsed **once** and shared. Two parses would have made
  extraction noise (D3/D4) look like resume progress. FR25 asks that FR6–FR9
  be re-run per version — they are; only the parse is shared.
  *Refs:* FR24, FR25

- [x] **T087 — Build the diff view**
  Summary line at top; per-requirement movement list below with before/after labels.
  *Done when:* a real two-version diff renders clearly.
  *Refs:* FR26, FR27

- [x] **T088 — Validate diffing on two real resume versions**
  *Done when:* at least one requirement is shown correctly moving up a category.
  *Status:* SM6 met — `Vector databases` gap → matched, 20 unchanged, nothing
  spurious (`docs/version_diff.md`). Took three attempts; the two failures were
  the more useful results. Applying Reqoncile's **own** rewrites moved nothing
  (a skills-list claim restated more clearly is still a skills-list claim), and
  the second attempt surfaced **D6**, a thread-unsafe stemmer — which the diff
  reported correctly as `indeterminate` rather than as movement.
  *Refs:* SM6

---

## Phase 12 — Buffer & Demo Prep

- [ ] **T089 — Re-run all three v1.1 features end to end**
  *Done when:* comparison, interview prep, and diffing each work on real data after
  all changes.

- [ ] **T090 — Final latency and graceful-degradation check**
  Re-time the core run and re-verify partial-failure behavior across all modes.
  *Done when:* NFR1 and NFR3 both hold on the final build.

- [ ] **T091 — Write the demo narrative**
  `docs/demo.md`: the run order to show, the Gap-vs-Weak example that proves real
  reasoning, the traceable rewrite, and the fabrication-boundary test as the answer to
  "how do you know it isn't hallucinating?"
  *Done when:* the script can be followed start to finish in one sitting.
  *Refs:* SM2, SM3, R2

- [ ] **T092 — Final polish and tag v1.2**
  *Done when:* the tag exists and the README covers all three added modes.
  *Note:* this task predates the ranking-measurement work, which already took
  the `v1.1` tag (that release narrowed the ranking claim to what the data
  supports). These three feature modes therefore ship as **v1.2**.
