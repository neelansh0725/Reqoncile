# T088 — SM6: version diffing on real resume versions

> SM6: *"Version diffing correctly shows at least one requirement moving from
> Gap or Weak Match to Matched between two real resume versions."*

**SM6 is met.** It took three attempts, and the two that failed are more
informative than the one that succeeded.

JD throughout: `advantest_ai_engineering_intern`. Base version: the real
resume (`v1`), gitignored like every other copy of it.

---

## The design decision that makes this trustworthy

The JD is **parsed once** and the same requirement set is used for both
versions.

This is load-bearing, not an optimisation. Extraction rewords requirements
between parses (D3), and a rewording alone can flip a verdict on identical
evidence (D4). Two independent parses would therefore produce a diff
contaminated by extraction noise **that looks exactly like resume progress** —
the single most misleading thing this feature could do.

FR25 asks that classification be re-run independently on both versions. It is.
Only the parse is shared, and parsing is FR1–FR3, not FR6–FR9. Sharing it also
pins the denominator, which is what makes the score delta in the summary line a
real comparison rather than two numbers over different requirement sets.

---

## Attempt 1 — applying Reqoncile's own rewrites changed nothing

`v2` applied two of the system's own rewrite suggestions for this JD, both
grounding-clean, merged into the existing skills line rather than replacing it
(replacing would have discarded DSA, DBMS and Operating Systems):

> `Demonstrated proficiency in object-oriented programming (OOP) principles;
> solid understanding of software engineering fundamentals across the Software
> Development Lifecycle (SDLC) and Agile practices`

Result: **`No change: all 19 requirements landed the same way. Score 59% → 59%.`**

`Software engineering` stayed **weak**, and the classifier said exactly why:

> v2: "lists a solid understanding of software engineering under core subjects,
> but this knowledge is **only asserted in a skills list rather than being
> demonstrated through practical application** in experience or project
> section"

**This is the matched-vs-weak rule (T037) working correctly, and it exposes a
real limitation of the rewrite feature.** Rewrites operate on the line the
evidence already sits in. If that line is in SKILLS, phrasing it more
explicitly does not change the *kind* of evidence, and the verdict does not
move. All five weak requirements in this run shared that one cause: present in
SKILLS, absent from project bullets.

Worth stating plainly: **Reqoncile's own suggestions, applied faithfully, did
not improve its own score.** The system is not gaming itself.

Also note this parse produced 19 requirements and did not extract
`Object-oriented programming` at all, so one of the two edits was never tested
(D3 again).

## Attempt 2 — a real crash, correctly reported

`v3` named Python in two project bullets, where each project's own tech-stack
line already lists it — surfacing existing content, not adding a claim, and
exactly what the classifier said was missing.

First run returned:

```
No change: all 20 requirements landed the same way, 1 not comparable.
  ? Python                          weak → errored
! Scores are not compared: the two versions did not score the same set of
  requirements, so their denominators differ...
```

The cause was **D6** — a thread-unsafe Snowball stemmer shared across the
concurrent classification fan-out. Fixed (thread-local instances; 24 → 0
failures on an 8-thread hammer).

**The diff machinery behaved correctly under a genuine fault**, which is the
part worth keeping: it marked the requirement `indeterminate` rather than
claiming movement, and suppressed the score delta rather than reporting a
change across mismatched denominators. That is T084/T085 validated on a real
failure instead of a constructed one.

After the fix, the same diff returned `No change: all 21 requirements landed
the same way. Score 61% → 61%.` — because `Python` came back **matched in
both** versions this time. It had been **weak in both** in the earlier run, on
byte-identical input. That observation is what led to **D7**: the configured
model ignores `temperature`, so nothing here ever ran deterministically.

## Attempt 3 — SM6 met

`v4` added a project the candidate actually built this season: **this
repository**. This is the PRD's own SM5 scenario ("LangChain/RAG before
Reqoncile itself existed") run forwards.

The entry's claims are verifiable in the repo — **with one exception that was
caught later and removed**, see the correction at the end of this document. It
is worth reading that section before quoting this one.

Run `run_20260818T153751_0f6923c5`, 815s:

```
Net improvement: 1 requirement stronger, 20 unchanged. Score 64% → 66% (+2 points).
  ↑ Vector databases                gap → matched
```

> "The resume describes implementing hybrid retrieval over a Chroma vector
> store in project work."

**A Gap moved to Matched, 20 requirements held still, and nothing moved
spuriously.** SM6 satisfied.

### What did not move, and whether that is right

Three requirements looked like plausible candidates. Only one moved.

| requirement | verdict | assessment |
|---|---|---|
| `Vector databases` | gap → **matched** | Correct. Chroma is named explicitly. |
| `Hugging Face` | gap → gap | **Defensible.** The entry lists `sentence-transformers`, which *is* a Hugging Face library, but the resume never says "Hugging Face". The classifier declined to infer the vendor from the library — conservative, and consistent with "adjacent is not evidence". |
| `LLM evaluation` | gap → gap | **Contestable.** The entry describes evaluating a classifier against a hand-labelled set and measuring retrieval behaviour. That is arguably LLM evaluation. Recorded as contestable rather than argued away. |

One clean move, one defensible refusal, one I would score differently. That
ratio is consistent with the classifier eval (17/20, with one contestable
label there too), and it is a better summary of this feature than "SM6 passed".

---

## Latency

| run | wall clock |
|---|---:|
| v1 ↔ v2 (19 requirements) | 136s |
| v1 ↔ v3 (21 requirements) | 140s |
| v1 ↔ v4 (21 requirements, longer resume) | **815s** |

The last is six times the others for the same requirement count. The added
project lengthened the resume, producing more chunks and more retrieval work
per requirement, and the run competed with free-tier pacing throughout. A diff
is two full pipeline runs by construction, so **NFR1's ~30s budget does not
apply to this mode and was never expected to** (`docs/latency.md`).

---

## A correction to this document's own test material

The `v4` entry originally claimed the anti-fabrication constraints were
"verified with a pytest suite plus 14 deliberately baited rewrite attempts."

**At the time, there was no pytest suite in this repository** (one exists now —
`docs/testing.md` — but it was written *after* this claim, and did not exist
when the claim was made). Verification was real but ad-hoc: inline scripts
under `scripts/` and one-off checks. The claim was
written by the same process this project exists to catch, onto a resume
version, and it is exactly the failure mode the grounding check (T044) targets
— a plausible credential with nothing behind it. It has been removed; the entry
now claims only the 14 baited attempts, which are documented in
`docs/fabrication_test.md`.

**Does this invalidate the SM6 result?** No. The requirement that moved was
`Vector databases`, and the classifier cited the *retrieval* line — "implementing
hybrid retrieval over a Chroma vector store in project work" — not the testing
line. The moved verdict does not rest on the removed claim. The run was not
repeated, because the day's hosted quota was nearly spent; that is a stated
limitation of this correction rather than a silent one.

**This gap has since been closed.** At the time of writing the project had no
automated test suite. It now has 87 offline tests covering the honesty
constraints, including a regression test for D6 — see `docs/testing.md`. Model
quality is still measured by hand, not guarded.
