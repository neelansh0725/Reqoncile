# The test suite

```sh
./.venv/bin/python -m pytest        # 95 tests, ~9s
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
break. Four guards were deliberately reverted:

| Mutation | Result |
|---|---|
| Remove the FR23 first-person validator | **caught** — 3 failures |
| Always report the score delta, ignoring denominator mismatch | **caught** — 1 failure |
| Restore the D6 shared stemmer | **NOT caught** — suite stayed green |
| Count usage per call instead of per attempt | **caught** — 2 failures |

The D6 test as first written used 15 distinct words and passed with the bug
reintroduced. It was false confidence — precisely the failure mode the rest of
this project is about, occurring inside the thing meant to prevent it.

The cause is that the bug needs enough token *variety* for concurrent calls to
interleave destructively. The fix was to build the corpus from the tracked
sample JDs (~1,100 distinct tokens), then verify **both directions**: the test
fails with the bug restored, and passes with the fix in place. Only then was it
kept.

The real resume cannot be used for this — it is gitignored — so the corpus is
the public JD set, which is enough.

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
