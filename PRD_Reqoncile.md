# Product Requirements Document
## Reqoncile
### An agentic RAG system for resume-to-job-description alignment

---

## 1. Overview

Reqoncile takes a job description and a resume as input and produces a
structured alignment report: a match score, a categorized list of matched
requirements, a list of genuine gaps, and specific, grounded rewrite suggestions
for resume bullets that under-communicate existing experience.

The system is built around a retrieval step (matching resume content against JD
requirements) and an agentic decision step (deciding, per requirement, whether it's
a strong match, a weak/implicit match worth rewriting, or a true gap) — not a fixed
keyword-matching script.

## 2. Problem Statement

Manually comparing a resume against a JD, requirement by requirement, is slow and
inconsistent. It's also easy to either under-sell existing experience (a real skill
stated in vague language scores lower than it should) or over-claim a gap (adding
a keyword that isn't backed by real experience, which fails at interview stage).
A good system needs to distinguish between these three cases explicitly, not just
run a keyword count.

## 3. Goals

- G1: Parse unstructured JD text into a structured requirement list (required vs.
  preferred, categorized by type — technical skill, soft skill, eligibility).
- G2: Retrieve the most relevant resume content for each requirement using
  semantic search, not exact keyword matching.
- G3: Classify each requirement as **Matched**, **Weak/Implicit Match**, or
  **Gap** — and justify the classification.
- G4: For Weak/Implicit Matches, generate a specific rewrite suggestion grounded
  in what the resume already says (no fabrication).
- G5: For Gaps, state them plainly rather than suggesting a workaround — the
  system should never suggest inventing experience.
- G6: Produce a final report in plain language, with an overall match score.

## 4. Non-Goals (Out of Scope)

- The system does not fabricate or suggest fabricating experience to close a gap.
- No resume file generation/formatting (LaTeX/docx output) — this system produces
  a report and suggested text, not a final formatted resume.
- No job-search/scraping functionality — JD is provided as input, not discovered.
- No multi-resume comparison beyond the same-candidate version diffing in FR24–FR27
  (i.e., no comparing two different people's resumes).
- No confidence self-critique/re-query pass in v1 — noted as a possible future
  extension, not committed scope (see Risks, R4).

## 5. Target Users

- **Primary:** the builder themself, evaluating personal job applications.
- **Secondary (framing for interview narrative):** any student/early-career
  candidate applying to multiple roles who needs consistent, honest resume
  tailoring rather than generic keyword stuffing.

## 6. Functional Requirements

### 6.1 JD Ingestion & Parsing
- FR1: Accept raw JD text (pasted or from a file).
- FR2: Extract a structured requirement list: skill/qualification name, category
  (technical/soft/eligibility), and required vs. preferred.
- FR3: Handle JDs of varying structure/quality (bulleted, prose, mixed) without
  requiring a fixed template.

### 6.2 Resume Ingestion & Retrieval
- FR4: Accept resume text (parsed from PDF/plain text).
- FR5: Chunk and embed resume content (by bullet/section) into a vector store.
- FR6: For each extracted JD requirement, retrieve the top-k most semantically
  relevant resume chunks.

### 6.3 Agent Classification & Reasoning
- FR7: For each requirement + retrieved resume content pair, the agent classifies
  the match as Matched / Weak Match / Gap.
- FR8: Classification must be justified with a short explanation referencing the
  actual resume text, not just a similarity score.
- FR9: The agent must distinguish "no relevant content retrieved" (Gap) from
  "relevant content retrieved but vaguely worded" (Weak Match) — this is the
  core reasoning step, not a fixed threshold on similarity score alone.

### 6.4 Rewrite Suggestion Generation
- FR10: For each Weak Match, generate a specific rewrite suggestion that surfaces
  the JD's terminology using only facts already present in the retrieved resume
  content.
- FR11: Rewrite suggestions must be traceable — the system should be able to show
  which original resume line a suggestion was derived from.
- FR12: The system must never suggest a rewrite for a Gap — gaps are reported,
  not papered over.

### 6.5 Report Generation
- FR13: Generate a final report: overall match score, categorized requirement
  list (Matched/Weak/Gap), rewrite suggestions, and a short plain-language
  summary.
- FR14: Report must be renderable both as structured data (for the UI) and as
  human-readable text (for direct use/export).

### 6.6 Interface
- FR15: Simple web UI (or CLI, if time-constrained) — paste JD, upload/paste
  resume, view report.
- FR16: Display the agent's reasoning trace for at least one example requirement
  per run, for demo/transparency purposes.

### 6.7 Multi-JD Comparison Mode (v1.1)
- FR17: Accept 2–3 JDs in a single session against one resume.
- FR18: Run the full classification pipeline (FR6–FR9) independently per JD.
- FR19: Produce a ranked comparison view — which JD the resume currently fits
  best, with the per-JD match score and a short reason for the ranking.
- FR20: Reuse the single-JD pipeline as-is; this mode adds a loop and a
  comparison/ranking step, not a new classification method.

### 6.8 Interview Prep Mode for Gaps (v1.1)
- FR21: For each requirement classified as a Gap, generate 2–3 plausible
  interview questions that would probe that specific gap.
- FR22: For each generated question, produce a short note on what an honest,
  defensible answer would need to cover — not a suggested answer to memorize,
  a description of what a good answer would honestly address.
- FR23: This mode must not generate a false/fabricated "sample answer" that
  implies experience the candidate doesn't have — it prepares the candidate to
  discuss the gap honestly, consistent with the FR12 constraint against
  fabrication.

### 6.9 Resume Version Diffing (v1.1)
- FR24: Accept two resume versions (e.g., v1 and v2) against the same JD.
- FR25: Re-run classification (FR6–FR9) on both versions independently.
- FR26: Produce a diff view: which requirements moved category between
  versions (e.g., Gap → Weak Match → Matched), and which stayed unchanged.
- FR27: Diff view should highlight net improvement (or regression) as a single
  summary line, plus the detailed per-requirement changes.

## 7. Non-Functional Requirements

- NFR1: End-to-end run (JD + resume in, report out) should complete in under
  ~30s for a demo-length JD/resume pair.
- NFR2: All components must run on free-tier/local infrastructure — no paid
  hosting required to demo.
- NFR3: System must degrade gracefully — if the LLM/agent step fails on one
  requirement, the rest of the report should still generate.

## 8. Success Metrics (portfolio-project framing)

- SM1: Demonstrable end-to-end run on a real JD (can literally use the JDs from
  this placement season as test cases).
- SM2: Correctly distinguishes at least one true Gap from at least one Weak
  Match in a demo run — proves the classification step is doing real reasoning,
  not just keyword counting.
- SM3: At least one rewrite suggestion is traceably grounded in real resume
  content (satisfies FR11) — this is the fact you'll point to if an interviewer
  asks "how do you know it's not hallucinating gaps or matches?"
- SM4: Multi-JD comparison correctly ranks at least 2 real JDs from this
  placement season against your actual resume, matching your own manual
  assessment of which fits best.
- SM5: Interview-prep questions generated for a real Gap (e.g., LangChain/RAG
  before Reqoncile itself existed) are plausible questions you'd genuinely
  expect to be asked.
- SM6: Version diffing correctly shows at least one requirement moving from
  Gap or Weak Match to Matched between two real resume versions you've
  actually produced this season.

## 9. Milestones (suggested, ~2 weeks of evening effort)

| Week | Milestone |
|---|---|
| Week 1, early | JD parsing (FR1–FR3): LLM-based structured extraction, test on 3–4 real JDs |
| Week 1, mid | Resume chunking + embedding + retrieval (FR4–FR6) |
| Week 1, late | Agent classification logic (FR7–FR9) — this is the core, spend real time here |
| Week 2, early | Rewrite suggestion generation (FR10–FR12) |
| Week 2, mid | Report generation (FR13–FR14) |
| Week 2, late | UI (FR15–FR16), end-to-end testing on real JD/resume pairs, polish for demo |
| Week 3, early | Multi-JD comparison mode (FR17–FR20) — thin layer over existing pipeline |
| Week 3, mid | Interview prep mode (FR21–FR23) |
| Week 3, late | Resume version diffing (FR24–FR27) |
| Week 4 | Buffer — polish, re-test all three v1.1 features end-to-end, prep demo narrative |

Core v1 (single-JD matching) is the priority — it must work solidly before any
v1.1 feature is started. If time runs short, ship v1 alone rather than a
half-working set of four features.

## 10. Risks

- **R1: Classification collapses into a keyword-match with extra steps.**
  Mitigation: explicitly test cases where a requirement is semantically present
  but phrased completely differently from the JD — this is the case that proves
  the system is doing real retrieval + reasoning, not string matching.
- **R2: Rewrite suggestions drift into fabrication.** Mitigation: hard constraint
  in the prompt — rewrites may only rephrase/surface existing content, never add
  unstated facts. Worth testing this boundary deliberately and documenting that
  you tested it (strong interview answer about safety-conscious design).
- **R3: Scope creep into a full "auto-apply" tool.** Mitigation: v1 stays a
  report generator; it advises, it does not act.
- **R4: Self-critique/re-query pass (confidence calibration) was deliberately
  excluded from v1.1.** It's a real, legitimate agentic pattern (the agent
  re-checking its own Gap classifications before finalizing) but roughly
  doubles the complexity of the classification step. Only take this on as a
  v2 extension if core + all three v1.1 features are solid with time to spare.
- **R5: Three added features (6.7–6.9) could each individually balloon in
  scope.** Mitigation: all three are explicitly built as thin layers over the
  existing single-JD pipeline (FR20, FR25), not new classification logic —
  if any of them starts requiring new reasoning capability beyond what v1
  already has, that's a signal to cut scope back, not add complexity.

---

*This PRD is scoped for a solo-built portfolio/resume project, not a production
system. Requirements favor demonstrable reasoning quality and honesty
constraints (R2, FR12) over completeness — those honesty constraints are
themselves a legitimate design decision worth highlighting in an interview.*
