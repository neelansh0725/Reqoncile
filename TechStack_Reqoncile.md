# Tech Stack Document
## Reqoncile

---

## 1. Core Components & Technology Choices

| Layer | Technology | Why |
|---|---|---|
| JD/Resume parsing | LLM-based structured extraction (via LangChain output parsers) | JDs are unstructured/inconsistent — regex or rule-based parsing breaks easily; an LLM extraction step handles varied formats reliably |
| Resume/document ingestion | `pypdf` or `pdfplumber` (if resume is PDF), plain text otherwise | Lightweight, free, no external service needed |
| Embeddings | `sentence-transformers` (Hugging Face) | Free, local, no API cost |
| Vector store | **Chroma** | Free, local, minimal setup, strong LangChain integration |
| Orchestration | **LangChain** | Direct keyword match with MathCo's JD; use `AgentExecutor` / LangChain's structured output tooling for the classification step |
| LLM (classification + rewrite + report generation) | Hosted API (Anthropic/OpenAI, low-cost tier) or local via Ollama | See section 3 for tradeoffs |
| Backend | FastAPI | Lightweight, async-friendly, pairs well with the rest of your resume's existing FastAPI experience — reinforces stack coherence in interview narrative |
| Frontend | React.js | Consistent with your existing project experience; simple form (paste JD, paste/upload resume) + report view |
| Logging / reasoning trace | Structured JSON logs (flat file or SQLite) | No new infra needed at this scale; satisfies FR16 (reasoning trace) directly |

## 2. Why LangChain Specifically (not a lighter alternative)

You could build this with raw API calls and no framework. Using LangChain
deliberately is the right call here because:
- It's explicitly named in the MathCo JD — using it directly is a precise,
  honest keyword match (you actually used it, not just claimed it).
- Its output-parsing and agent-tooling utilities map cleanly onto FR2 (structured
  JD extraction) and FR7–FR9 (classification with tool use) — you're not forcing
  the framework onto a problem it doesn't fit.

## 3. LLM Choice — Tradeoffs

| Option | Cost | Notes |
|---|---|---|
| Anthropic Claude API (low/free tier) | Low, pay-per-use | Strong reasoning for the classification step (FR7–FR9), which is the project's core — worth prioritizing quality here over saving a few dollars |
| OpenAI API (low/free tier) | Low, pay-per-use | Comparable alternative |
| Local via Ollama (Llama 3 8B / Mistral 7B) | Free | Fully free, good as a fallback or for the "cost-conscious design" talking point, but weaker structured-reasoning consistency for the classification step specifically |

**Recommendation:** use a hosted API for the classification/reasoning step (FR7–FR9)
since that's the part of the project doing the real intellectual work and quality
matters most there; consider a local model for the simpler rewrite-generation step
(FR10) if you want to demonstrate a cost-optimization decision — mixing tiers by
task difficulty is itself a legitimate architecture decision to discuss in an
interview.

## 4. Implementation Notes for v1.1 Features

### 4.1 Multi-JD Comparison Mode (FR17–FR20)
No new components needed. This is a loop over the existing single-JD pipeline
(parsing → retrieval → classification → report) run once per JD, plus a small
ranking step at the end. The ranking step is a single LLM call: given N
per-JD reports, produce a ranked list with a one-line reason per rank — this
can reuse the same LLM client already set up for classification, no new
integration required.

### 4.2 Interview Prep Mode (FR21–FR23)
Also no new components — this is an additional LLM prompt/chain triggered per
Gap-classified requirement, using the same LLM client as the rewrite generator
(`rewriter.py`). The key implementation detail is the prompt constraint from
FR23: the prompt must explicitly instruct the model to describe what an honest
answer would cover, not draft a first-person sample answer — this is a prompt
design problem, not an infrastructure one. Worth unit-testing this prompt
specifically against a few real Gaps to confirm it doesn't drift into writing
fabricated experience.

### 4.3 Resume Version Diffing (FR24–FR27)
Requires one new lightweight piece: a diff function comparing two sets of
per-requirement classifications (from two independent pipeline runs) and
producing a structured change list. This is plain Python logic (comparing two
lists of `{requirement, classification}` objects), not an ML/LLM component —
keep it that way rather than asking the LLM to "compare two reports," which
would be slower and less reliable than a direct structural diff.

```python
# rough shape, not final code
def diff_classifications(run_v1: list[dict], run_v2: list[dict]) -> dict:
    # match by requirement name, compare classification field,
    # bucket into: improved / regressed / unchanged
    ...
```

## 6. Suggested Repository Structure

```
reqoncile/
├── parsing/
│   ├── jd_parser.py          # LLM-based structured JD extraction (FR1-FR3)
│   └── resume_parser.py      # PDF/text ingestion + chunking (FR4-FR5)
├── retrieval/
│   ├── embed.py               # sentence-transformers embedding pipeline
│   └── vector_store.py        # Chroma setup + retrieval (FR6)
├── agent/
│   ├── classifier.py          # Matched/Weak/Gap classification logic (FR7-FR9)
│   ├── rewriter.py            # rewrite suggestion generation (FR10-FR12)
│   ├── comparator.py          # multi-JD ranking logic (FR17-FR20)
│   ├── interview_prep.py      # gap-question generation (FR21-FR23)
│   └── diff.py                # resume version diffing (FR24-FR27)
├── reporting/
│   └── generate_report.py     # final report assembly (FR13-FR14)
├── backend/
│   └── main.py                 # FastAPI endpoints
├── frontend/                   # React app (FR15-FR16)
├── test_data/
│   └── sample_jds/             # real JDs collected this placement season — genuinely useful test set
└── logs/
    └── runs.jsonl               # reasoning-trace logging
```

## 7. Dependencies (Python)

```
langchain
langchain-community
chromadb
sentence-transformers
pypdf                  # or pdfplumber
fastapi
uvicorn
anthropic               # or openai, depending on LLM choice
pydantic                # for structured output schemas (JD requirements, classifications)
# ollama is a separate local install if used, not a pip dependency
```

## 8. A Practical Advantage You Already Have

Your `test_data/sample_jds/` folder doesn't need to be invented — you already
have real, varied JDs from this placement season (Amazon, EY, Osfin, Advantest,
MathCo, Whirlpool) sitting in this conversation. That's a genuinely representative
test set most portfolio projects don't have access to, and it's worth mentioning
explicitly in an interview: the system was validated against real JDs you
personally applied against, not synthetic examples.

## 9. What NOT to Add (keep scope tight)

- No production vector DB (Pinecone, Weaviate) — Chroma is sufficient and free.
- No multi-agent frameworks beyond LangChain's own tooling (no AutoGen/CrewAI) —
  one agent with clear tool boundaries is the right scope for 2 weeks.
- No resume-file generation (LaTeX/docx) — this system's job ends at the report;
  keep the boundary with your existing manual resume-editing workflow clean.
- No authentication/multi-user support — single-user demo tool.

---

*Stack choices prioritize: (1) zero/low cost, (2) a direct, honest keyword match
with the target JD (LangChain), and (3) reasoning quality on the one component
that matters most (classification) over uniform effort across every component.*
