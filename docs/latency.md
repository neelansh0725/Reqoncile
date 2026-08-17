# Latency and the NFR1 budget (T052)

NFR1 asks for an end-to-end run "under ~30s for a demo-length JD/resume pair".

**Short answer: met for a demo-length JD on a warm process with fresh quota
(~18s); not met otherwise. The binding constraint is the free-tier request
quota, not compute.**

## Measured, three real JDs, warm process

| JD | parse | index | classify | rewrite | report | **total** | reqs |
|---|---:|---:|---:|---:|---:|---:|---:|
| mathco_ai_analyst | 3.1 | 0.8 | 4.0 | 5.5 | 4.7 | **18.2** | 10 |
| osfin_implementation_engineer | 2.1 | 0.2 | 46.4 | 2.5 | 4.0 | **55.1** | 10 |
| advantest_ai_engineering_intern | 3.8 | 0.1 | 64.6 | 15.2 | 5.7 | **89.4** | 21 |

Within budget: **1 of 3**.

Share of the median run: classify **84%**, rewrite 10%, report 9%,
parse 6%, indexing **0%**.

## Read the variance, not the median

Two JDs with the *same* number of requirements (10) took 4.0s and 46.4s to
classify. That is not model variance — it is the rate limiter doing its job.

Classification is one call per requirement, paced to 15 requests/minute
(`docs/providers.md`). So wall time is set by quota arithmetic:

- **10 requirements, fresh window** → all fit inside the first minute → ~4s.
- **10 requirements, window already spent by a previous run** → the limiter
  waits for slots to age out → ~46s.
- **21 requirements** → 15 immediate, 6 must wait for the window to roll →
  ~65s. There is no way to go faster without exceeding the quota.

**Consecutive runs share one 60-second window**, so the second and third runs
in a batch pay for the first. A single demo run behaves very differently from
a benchmark loop, and the 55.1s and 89.4s figures above are partly an artifact
of measuring three runs back to back.

## Cold start is a separate, one-time cost

Loading the sentence-transformers model takes **8.8s**, once per process.
Warm, indexing the resume is **0.2s** — effectively free.

The first end-to-end run in a fresh process measured 31.2s; the same run warm
measured 18.2s. Nearly all of that difference is the model load. A server that
loads the model at startup (as the FastAPI backend will, T053–T057) pays this
once, not per request.

## What this means for NFR1

**Met** — demo-length JD (~10 classifiable requirements), warm process, quota
not already consumed: **~18s**.

**Not met** — JDs with more than ~15 classifiable requirements, or runs issued
back to back. At 15 requests/minute, 21 requirements cannot complete in under
30 seconds by arithmetic, regardless of implementation.

This should be stated plainly rather than tuned around: the project chose a
free tier, and the free tier's quota is the floor. The v1.1 multi-JD mode
(FR17–FR20) will feel this hardest, since it multiplies requirement count by
the number of JDs.

## Levers, if the budget ever has to hold for large JDs

1. **Batch classification** — 5 requirements per call cuts a 21-requirement JD
   from 21 calls to 5. Biggest single win. Costs per-requirement error
   isolation (T032) and coarsens the reasoning trace (FR16), both of which are
   explicit PRD requirements, so this is a real trade rather than free.
2. **Cache JD parses by content hash** — removes ~3s from every repeat run and
   from every multi-JD/version-diff run that re-parses the same JD. Cheap,
   no downside, not yet implemented.
3. **Raise `REQONCILE_LLM_RPM`** — only if the account's real quota is higher.
   Above the true limit this trades latency for 429s, which is strictly worse.
4. **Move classification to the local tier** — no quota at all, but puts the
   project's core reasoning step on a 7–8B model. Given T044 showed
   `llama3:8b` is already decline-biased on the much simpler rewrite task,
   this would likely cost real accuracy.

Nothing here is worth doing until the UI exists and the real interaction
pattern is known — a user analysing one JD at a time never sees the
back-to-back case that produced the worst numbers above.
