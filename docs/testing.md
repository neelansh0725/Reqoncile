# The test suite

```sh
./.venv/bin/python -m pytest        # 147 tests, ~11s
```

**No network, no model call, no quota.** Everything here is pure logic, which
is deliberate: the tests cover the *honesty constraints*, and those are exactly
the parts that are decidable offline.

## What it covers, and why these things

Each test corresponds to a claim made in the README. If one fails, a published
claim has become false.

| File | Pins |
|---|---|
| `test_schema_constraints.py` | FR8 evidence rules (a gap citing evidence is rejected; matched/weak without evidence is rejected), `errored` not being a verdict a model can return, the FR23 first-person guard, the 2–3 question bound, ties being representable |
| `test_differ.py` | The gap→weak→matched scale, `errored` becoming `indeterminate` rather than `unchanged`, score deltas withheld when denominators differ, name-mismatch warnings, every summary-line branch |
| `test_gates.py` | `suggest_rewrite` refusing anything but `weak` (FR12), `prepare_for_gap` refusing anything but `gap` (FR21) |
| `test_grounding.py` | What the grounding check catches — figures, entities, seniority, scale — and the SM3 rewrite still passing clean |
| `test_chunk_stability.py` | Content-derived chunk ids surviving document reordering, one edit changing exactly one id, the `chunk_min_chars` floor |
| `test_lexical.py` | Porter2 stemming behaviour and the **D6** concurrency regression |
| `test_run_id.py` | Run-id format validation, including the trailing-newline bypass |
| `test_comparator.py` | JD count bounds, duplicate labels, refusing to rank fewer than two scoreable JDs |
| `test_usage_accounting.py` | The usage ledger, and that **every attempt** is counted — a retried request consumes quota whether or not it succeeded, while a permanent failure still fails fast on one call |
| `test_api_validation.py` | Request validation at every endpoint boundary, and that a traversal attempt on `/interview-prep/{run_id}` never reaches the handler |
| `test_render_diff.py` | Every branch of the diff renderer, plus a parametrised "never raises" case. Added after the renderer shipped broken: nothing called it, so nothing caught it |
| `test_index_caching.py` | Chunks already in a collection are not re-embedded, and an unreadable collection falls back to re-embedding rather than assuming |
| `test_frontend_copy.py` | No em-dashes in UI copy, no operator telemetry (model ids, stage names) in product surfaces, `…` over `...`, and that the loading skeleton never names a pipeline stage it cannot know |
| `test_frontend_a11y.py` | Every textarea labelled, the tab pattern complete (roving tabindex, arrow keys, controlled panel), results announced via a live region, contextual names on disclosure buttons, and all three paste boxes offering PDF upload |

## Two tests that are unusual on purpose

**One test asserts a limitation, not a capability.**
`test_semantic_inflation_in_new_words_is_not_caught` asserts that the grounding
check *misses* inflation phrased entirely in new words. The README says so, and
the test exists so that claim cannot quietly become an over-claim. If it ever
fails, the check got stronger and the README should be updated to claim more —
the good direction, but it must be deliberate.

**One test guards another test.**
`test_corpus_is_varied_enough_to_be_a_real_test` asserts the D6 corpus has more
than 800 distinct tokens, because the concurrency test is worthless below that
(see below).

## The suite was mutation-checked, and one test failed the check

A suite that passes proves nothing until it has been shown to fail on a real
break. Every guard here was deliberately reverted to check it fires:

| Mutation | Result |
|---|---|
| Remove the FR23 first-person validator | **caught** — 3 failures |
| Always report the score delta, ignoring denominator mismatch | **caught** — 1 failure |
| Count usage per call instead of per attempt | **caught** — 2 failures |
| Reintroduce `out +=` in the diff renderer | **caught** — 4 failures |
| Re-embed chunks already in the collection | **caught** — 2 failures |
| Drop the "nothing extracted" vs "no names in common" distinction | **caught** — 1 failure |
| Reintroduce an em-dash into UI copy | **caught** |
| Remove the tab keyboard handler | **caught** |
| Point the third upload control at the wrong box | **caught** |
| Restore the D6 shared stemmer | **NOT caught** — suite stayed green |
| Delete the compare-mode textarea labels | **NOT caught** — suite stayed green |

**Two tests failed their own mutation check.** Both were lint-shaped: they
grepped source rather than executing it, and both were quietly inert.

The D6 concurrency test used 15 distinct words and passed with the bug
reintroduced. The bug needs enough token *variety* for concurrent calls to
interleave destructively. Rebuilt against the tracked sample JDs (~1,100
distinct tokens) and verified in both directions before being kept. The real
resume cannot be used — it is gitignored — so the public JD set stands in.

The textarea-label test matched `<textarea\b[^>]*?/>`, which cannot span the
`>` inside `onChange={(e) => ...}`. It therefore matched no multi-line
textarea at all and passed with every label deleted. Fixed, re-verified in
both directions, and a guard-the-guard test now asserts the matcher sees every
textarea in the file.

The lesson generalised: **a test that greps source is not trusted until it has
been shown to fail.** Both inert tests looked entirely reasonable in review.

## What is not covered

**Model quality is not regression-guarded.** Retrieval relevance, classifier
accuracy, extraction stability, and rewrite fidelity are all measured by the
scripts behind `docs/` and re-run by hand. They cost hosted quota, they are
non-deterministic (D7 — the reasoning model ignores `temperature` entirely), and
a pass/fail threshold on a noisy measurement would be worse than no test.

The practical consequence: **this suite can tell you a refactor broke the
honesty constraints. It cannot tell you a prompt change made the classifier
worse.** For that, re-run `scripts/eval_classifier.py` and compare against
`docs/classifier_eval.md`.
