# T081 / T083 — Interview prep for gaps (FR21–FR23)

Gaps get *prepared for*, not rewritten. The complement of FR10: a weak match
is rewritten because the experience is there and under-sold; a gap cannot
honestly be rewritten, so the useful thing is to walk in able to discuss it.

Gate: `prepare_for_gap` raises `PrepNotApplicable` for any label but `gap`,
mirroring `suggest_rewrite`'s gate to `weak`.

---

## FR23 is enforced by the schema, and it had to be

FR23 forbids a fabricated sample answer implying experience the candidate does
not have. That is enforced in `GapQuestion`: a validator rejects first-person
phrasing in `answer_should_cover` outright.

**This is not decorative. It caught a real violation on the first live run.**

Given a system prompt that says *"Never write in the first person"* and shows a
worked GOOD/BAD pair, `llama3:8b` returned all three notes ending like this:

> "…highlight any relevant data analysis skills or tools used. For example,
> **'In my previous role, I worked with data visualization tools** to identify
> trends and patterns…'"

That is the exact failure FR23 names: a memorisable line asserting a previous
role the resume does not evidence. The instruction did not hold. The validator
did — all three were rejected, and the honest outcome was *no questions for
that gap* rather than a fabricated line.

This is the same lesson as the grounding check (T044), reproduced
independently: **a safety property enforced only by asking nicely is not a
property.**

### Measured rate

Six real gaps from `run_20260818T111956_37edd7b8`
(`advantest_ai_engineering_intern`), two prompt configurations, before and
after one prompt fix:

| | attempts | validated | FR23 violations caught | leaked | median |
|---|---:|---:|---:|---:|---:|
| **Baseline**, no adjacent context | 6 | 5 | 1 | **0** | 13.8s |
| **Baseline**, with adjacent context | 6 | 5 | 1 | **0** | 18.3s |
| **After fix**, no adjacent context | 6 | 6 | 0 | **0** | 14.1s |
| **After fix**, with adjacent context | 6 | 6 | 0 | **0** | 20.0s |

Baseline violation rate: **2 of 12 (17%)**, on a different gap each time
(`PyTorch` without context, `Applied Statistics` with it) — so the failure is
non-deterministic and not tied to a particular requirement.

**The fix.** Every violation took one form: an appended `For example, '…'`
quote. The prompt banned first-person writing but never banned an illustrative
quoted specimen, which is still a line to recite. One rule was added naming
that construction.

**What 12/12 does and does not show.** It is consistent with the fix helping.
It is not evidence that the failure mode is gone: under the baseline rate of
17%, the chance of seeing 12 clean attempts by luck alone is **≈ 11%**. That is
nowhere near significant. Per the project's standing rule, the prompt was fixed
**once**, on a deficiency nameable in advance, and not iterated further to make
the number prettier.

**The guard, not the prompt, is what makes FR23 hold.** The prompt reduces how
often the model tries; the schema is what guarantees nothing gets through.

---

## SM5 — are the questions plausible?

> SM5: *"Interview-prep questions generated for a real Gap are plausible
> questions you'd genuinely expect to be asked."*

Judged across all 18 questions from the six real gaps. **SM5 is met**, with two
qualifications that belong in the same breath.

A representative gap — **Vector Databases**, genuinely absent from the resume:

> 1. *"Can you tell me about your experience with databases? How do you think
>    your skills in relational databases and MongoDB could be applied to a role
>    that requires vector databases?"*
>    → Acknowledge the gap in vector database experience, highlight the
>    relevance of relational databases and MongoDB, and explain how the
>    candidate would approach learning them.
>
> 2. *"What do you think are the key differences between relational databases
>    and vector databases?"*

These are questions a real screen would ask. The second in particular is the
standard way an interviewer probes whether an unclaimed skill is understood
conceptually. The notes describe what to address and never draft an answer.

### Qualification 1 — the questions are templated

| pattern | frequency |
|---|---|
| A *"how do you stay current with…"* question | **6 of 18 — exactly one in every one of the 6 gaps** |
| Note opening *"Acknowledge the lack/gap of…"* | **15 of 18** |

The prompt says "not the same question phrased three ways", and *within* a gap
it complies. **Across** gaps it fills the same slot every time. So the third
question of any gap is largely predictable, and the real yield is closer to two
useful questions per gap than three. This is an 8B local model behaving like an
8B local model; the tier is swappable if it matters.

### Qualification 2 — a question can carry a false premise (see D5)

One of the 18 asserts experience rather than asking about it:

> *"**In your previous role, you worked on a project that required
> collaboration with stakeholders.** Can you walk me through…"*

This was generated for **Communication**, which the classifier had just
labelled a **gap** — meaning no evidence. The question presupposes the very
thing found to be missing.

The FR23 validator guards `answer_should_cover`, not `question`, and cannot
easily guard the latter: questions legitimately address the candidate in the
second person (*"Can you walk me through your experience…"*), so a first-person
or second-person check would reject correct questions. What is wrong here is
the **declarative presupposition**, which is not lexically separable from a
normal question.

Recorded as **D5** rather than patched on a single observation. The harm is
also lower than the FR23 case: a false premise in a *question* is something the
candidate notices and corrects in the room, whereas a fabricated *answer* is
something they recite.

---

## Latency

Prep runs entirely on the local generation tier, so it costs **no hosted
quota** — but it is not fast.

| | median | max |
|---|---:|---:|
| Without adjacent-chunk context | 14.1s | 18.0s |
| With adjacent-chunk context (shipped) | 20.0s | 23.5s |

Adjacent context costs roughly **6s per gap** and is kept: it is what lets a
note point at the nearest genuine thing on the resume instead of only saying
"acknowledge the gap".

**The first call also pays model load.** A cold `llama3:8b` took **over ten
minutes** to return a single gap — 0% CPU throughout, entirely waiting on
Ollama loading 4.6 GB from disk. Warm, the same call takes ~20s. This was
initially misread as a prompt-complexity problem; it is not. Anything timing
this path must warm the model first.

Consequence for the API: `POST /interview-prep/{run_id}` defaults to
`limit=5` and caps at 15. A 17-gap report (`nse_technology_operations`) would
otherwise run for six minutes.
