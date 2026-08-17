# API examples (T058)

Recorded against a live server, real JD and real resume. Start with
`./scripts/serve.sh` (http://127.0.0.1:8000; interactive docs at `/docs`).

## `GET /health`

```sh
curl -s http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "embedding_model_loaded": true,
  "reasoning_tier": "google/gemini-3.5-flash-lite",
  "generation_tier": "ollama/llama3:8b"
}
```

`status` is `degraded` if the embedding model failed to load — the endpoint
still answers, so an operator can see *why* rather than getting a dead port.

## `POST /upload-resume`

Extracts text from a PDF and hands it back for the user to check before
analysing. It deliberately does **not** analyse: the user should be able to
see and correct what was extracted first.

```sh
curl -s -X POST http://127.0.0.1:8000/upload-resume \
  -F "file=@test_data/resumes/Best_withoutphoto.pdf"
```

```json
{
  "text": "NEELANSH SINGH\nPhone: +91-... (full extracted text)",
  "characters": 5527,
  "lines": 78
}
```

Verified: the text returned over HTTP is byte-identical to the T007 ground
truth fixture.

## `POST /analyze`

```sh
curl -s -X POST http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"jd_text": "<job description>", "resume_text": "<resume text>"}'
```

Optional: `"include_rewrites": false`, `"include_summary": false` — both skip
generation-tier work, which is the fastest way to get a report when Ollama is
not running.

Response (trimmed; one real run):

```json
{
  "report": {
    "run_id": "run_20260816T211407_faef3935",
    "score": 44.4,
    "score_explanation": "44% \u2014 3 matched, 2 weak (half credit), 4 gaps across 9 scored requirements (4 of 9 weighted points).",
    "score_is_meaningful": true,
    "classifications": [
      {
        "label": "matched",
        "justification": "The resume explicitly demonstrates analytical capabilities by documenting actionable business insights and surfacing revenue trends and category-level KPIs in project dashboards.",
        "evidence_chunk_ids": [
          "projects-33b3220e",
          "projects-7c2bbee7"
        ],
        "requirement": {
          "name": "analytical",
          "category": "soft",
          "necessity": "required"
        }
      },
      {
        "label": "gap",
        "justification": "The resume describes projects and volunteer work, but contains no evidence or mention of self-motivation or a proactive mindset.",
        "evidence_chunk_ids": [],
        "requirement": {
          "name": "self-motivation",
          "category": "soft",
          "necessity": "required"
        }
      },
      "... 7 more"
    ],
    "rewrites": [
      {
        "requirement": {
          "name": "proactive mindset"
        },
        "source_chunk_id": "projects-a791c5df",
        "original_text": "Integrated GitHub API to flag stale PRs/tasks, with a scheduled worker auto-generating workflow health reports.",
        "suggested_text": "Demonstrated a proactive mindset by integrating the GitHub API to flag stale PRs/tasks and auto-generating workflow health reports.",
        "grounding_flags": []
      }
    ],
    "eligibility": [],
    "errored": [],
    "summary": "Your resume shows some promising matches with the job description, particularly in your experience with analytical work, SQL, and automation projects. However, ...",
    "warnings": []
  },
  "markdown": "# Resume alignment report\n\n## Match score: ...  (full report, 71 lines)",
  "timings": {
    "jd_parse": 2.52,
    "resume_index": 0.48,
    "classify": 4.08,
    "rewrite": 12.52,
    "report": 6.06
  },
  "total_seconds": 25.66
}
```

**FR14 in one response.** `report` is the structured object for the UI;
`markdown` is the same report rendered for direct use or export. Clients never
have to re-render.

## Error responses

| Case | Status | Detail |
|---|---:|---|
| Unsupported upload type | 400 | `unsupported file type 'csv'; upload a PDF or text file` |
| Empty upload | 400 | `uploaded file is empty` |
| PDF with no text layer | 400 | `has no extractable text layer -- it is probably a scan` |
| Blank / missing / oversized field | 422 | FastAPI validation detail |
| Upload over 10MB | 413 | `file is N bytes; limit is 10485760` |
| Missing API key | 503 | `GOOGLE_API_KEY is not set...` |

**A partly-failed analysis returns 200, not 500.** If some requirements could
not be classified they appear in `report.errored` with a warning, and the rest
of the report is intact (NFR3). Failing the whole request would discard a
report that is mostly correct — and the failure is already visible in the
response.

## Timing

The run recorded above: `{'jd_parse': 2.52, 'resume_index': 0.48, 'classify': 4.08, 'rewrite': 12.52, 'report': 6.06}` — **25.66s** total.

The embedding model loads at server startup (~9s), so no request pays for it.
See `docs/latency.md` for why classification dominates and when the ~30s NFR1
budget does and does not hold.
