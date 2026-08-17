# Model tiers and providers

Reqoncile runs free end to end. Model usage is split into two tiers, each
independently swappable via `.env` — no code change.

| Tier | Used by | Default | Why |
|---|---|---|---|
| `reasoning` | JD extraction (FR2), classification (FR7–FR9) | Google Gemini, free tier | The classification step is the project's actual intellectual work, and both steps need reliable structured output. |
| `generation` | Rewrite suggestions (FR10), interview-prep questions (FR21–FR23) | Ollama, local | These rephrase text already retrieved and grounded from the resume. A 7–8B local model is adequate, and local keeps it permanently free. |

Mixing tiers by task difficulty is a deliberate cost decision, not an
accident of what was lying around — see TechStack §3.

## Setup

**Reasoning tier.** Get a free key at <https://aistudio.google.com/apikey>,
put it in `.env` as `GOOGLE_API_KEY`. That is the only credential the core
pipeline needs.

**Generation tier.** Install Ollama from <https://ollama.com/download>, then:

```sh
ollama pull llama3:8b     # or: ollama pull mistral:7b
```

Ollama must be running for rewrite generation. Nothing in the v1 core path
(JD parse → retrieve → classify → report) depends on it — only rewrites and
interview prep do, so the pipeline is usable before Ollama is set up.

**Verify both:**

```sh
./.venv/bin/python scripts/check_providers.py          # config + reachability
./.venv/bin/python scripts/check_providers.py --live   # one real call per tier
```

Run this before any long session. Free-tier model IDs and availability move
around, and a wrong model name fails at call time — deep inside a run —
rather than at import.

## Which Gemini model — measured, not guessed

Probed against a real free-tier account. Two findings that are not visible
from the model list:

| Model | Result |
|---|---|
| `gemini-3.5-flash` | **5.4s**, consistent extraction, honours `temperature` — **default** |
| `gemini-3.6-flash` | 8.0s, varied run-to-run on identical input, **ignores `temperature`** |
| `gemini-3.7-flash` | 24.2s median, one run returned zero requirements |
| `gemini-3.1-pro-preview`, `gemini-pro-latest` | `429` quota-exceeded on first call |
| `gemini-2.5-pro`, `gemini-2.5-flash` | `404` — withdrawn for new accounts |

Two traps worth knowing:

1. **Listing a model does not mean you can call it.** `models.list()` returns
   38 models, including withdrawn ones that 404 on use and Pro models with no
   free quota that 429. Only `check_providers.py --live` distinguishes them.
2. **There is no usable Pro tier on the free plan.** "Strongest free model"
   resolves to a Flash model, not a Pro one. Newer is not automatically
   better: 3.7-flash was ~4.5× slower than 3.5-flash and less reliable.

`gemini-3.6-flash` ignoring `temperature` matters beyond speed: the classifier
eval (T036) assumes repeated runs on identical input agree. A model sampling
at fixed defaults makes that comparison noisy. Prefer models that honour
`temperature=0.0` for anything the eval measures.

## Free-tier request quotas — measured

Probed by issuing calls until the API returned 429 and reading `quotaValue`
off the error:

| Model | Req / min | Req / **day** |
|---|---:|---:|
| `gemini-3.5-flash` | 5 | **20** |
| `gemini-3.6-flash` | 5 | (not probed) |
| `gemini-3.5-flash-lite` | **15** | **500** |
| `gemini-3.1-flash-lite` | ≥9, not hit | not hit |
| `gemini-flash-lite-latest` | ≥9, not hit | not hit |

**The daily cap is what actually decides this, and it is easy to miss.** The
per-minute limit reads like the constraint, and pacing appears to fix it —
until the *daily* quota lands. `gemini-3.5-flash` allows **20 requests per
day**. A single 15-requirement JD run consumes 15 of them, so the full Flash
models cannot be used for this project at all, irrespective of quality. That
is why the reasoning tier defaults to `gemini-3.5-flash-lite`: not because it
reasons better, but because it is the only free option with enough allowance
to run more than once a day.

Two practical consequences:

- **Budget the *day*, not just the run.** `gemini-3.5-flash-lite` allows
  **500 requests/day**. A nine-JD sweep costs ~300 under the current
  extraction rule, so two sweeps plus evaluation work exhausts a day. A sweep
  that is affordable in isolation can still fail if the day is already spent —
  this happened, and cost a nine-JD re-ordering run.
- **Budget a run before starting one.** JD parsing costs 1 call; classification
  costs one per classifiable requirement (mean 13.4 after the T015a
  eligibility split). Nine sample JDs is ~130 calls.
- **A 429 is not always the rate limiter failing.** Read `quotaId` on the
  error: `GenerateRequestsPerMinutePerProjectPerModel-FreeTier` means slow
  down, `...PerDayPerProjectPerModel...` means stop until tomorrow or switch
  model. `scripts/eval_classifier.py` surfaces the raw error for this reason.

### The pace limiter must own retries

`llm_client` limits outbound requests with a sliding 60-second window
(`REQONCILE_LLM_RPM`). A subtlety cost a whole eval run to find:

> The provider client retries 429s **internally**. Those retries do not pass
> through our limiter, so one paced call can become several real requests and
> blow the quota anyway.

Twelve of twenty eval requirements errored with the limiter apparently set
correctly, because `max_retries=3` on the client turned each paced call into
up to four requests. The fix is to set the provider's `max_retries=0` and own
the retry loop in `_invoke_paced`, which re-acquires the limiter on every
attempt. **Any future provider added to the registry must do the same** — a
client that retries behind the limiter's back silently breaks the guarantee.

## The rate limit is the real constraint

Free-tier Gemini caps **requests per minute**, and the stronger the model the
lower the cap. This collides directly with the classification design:

- One requirement = one classification call (T028–T031), needed for
  per-requirement error isolation (T032) and the reasoning trace (T033).
- A JD with ~15 requirements is therefore ~15 calls, fanned out concurrently
  (T034), against a 30-second end-to-end budget (NFR1).

That can exceed a free-tier per-minute quota in a single run. Mitigations, in
the order worth trying:

1. **Lower concurrency.** `REQONCILE_LLM_MAX_CONCURRENCY` defaults to 4 rather
   than 8 for this reason. Lower still if 429s appear.
2. **Switch to a faster model.** `REQONCILE_REASONING_MODEL=gemini-2.5-flash`
   trades some reasoning quality for a much higher cap. Whether the trade hurts
   is an empirical question — the eval harness (T036) answers it directly.
3. **Batch requirements per call.** Genuinely reduces call count, but costs the
   per-requirement error isolation of T032 and complicates the trace. Do not
   do this pre-emptively; only if 1 and 2 are insufficient.

Do not raise concurrency to chase NFR1 without checking for 429s first — a
retried request is slower than a serialised one.

## Structured output caveat

`complete_structured()` defaults to the **reasoning** tier deliberately. Small
local models are markedly less reliable at adhering to a schema, and both JD
extraction and classification depend on getting a validated object back.

Before moving any structured call to the generation tier, test that specific
schema against the local model — `check_providers.py --live` exercises a
trivial one on both tiers and reports whether the tier honoured the schema
*and* got the content right.
