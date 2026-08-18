# T077 — SM4: does the ranking match a manual judgment?

> SM4: *"The multi-JD comparison ranks JDs in an order a human reviewer
> agrees with."*

## Test design

The failure mode this test exists to avoid is reading the system's output and
then constructing a justification for it. So the manual ranking below was
**written and committed before the comparison was run**, from the JD text and
the resume alone.

Three JDs, chosen to span the range rather than to be easy:

| JD | why it is in the set |
|---|---|
| `advantest_ai_engineering_intern` | Closest thing in the sample set to a direct hit |
| `osfin_implementation_engineer` | Middle: the technical asks are met, the behavioural ones are not evidenced |
| `nse_technology_operations` | Adjacent field, almost no overlapping evidence |

---

## Manual ranking (pre-registered)

**1. `advantest_ai_engineering_intern`** — near-direct hit. Python, data
structures, DBMS, Git, testing, ML fundamentals, and "at least one substantial
AI/ML project beyond tutorials" are all evidenced (the Multimodal AI Content
Detection System). Most of the *preferred* list lands too: FastAPI, Docker,
cloud (Azure/Databricks). The gaps I expect are preferred items —
PyTorch, Hugging Face, vector databases — plus applied statistics.

**2. `osfin_implementation_engineer`** — the hard requirements are met. SQL is
throughout, MS Excel appears in the Power BI project, and "previous experience
working on automation projects" is directly evidenced by the Airflow pipeline.
What is missing is the behavioural half — self-motivation, ownership, working
independently with minimal guidance — which a resume rarely states outright.
Second, not first: fewer requirements met in absolute terms and the shortfalls
are on stated *required* items.

**3. `nse_technology_operations`** — the widest gap in the set, and I expect
it to be obvious. Linux OS concepts and IPC, Java/C, PL/SQL, ITIL, ITRS /
ServiceNow / Control-M, application monitoring tooling, Java 3-tier
client-server, AWS: none of these are evidenced. The resume has C++ (not
Java/C), Azure (not AWS), and a monitoring *table* in a data pipeline, which is
not application monitoring in the ITIL sense.

**Ordering: advantest > osfin > nse_ops.**

Confidence is not uniform, and that matters for how the result should be read:
the advantest-vs-nse_ops separation is wide and I would defend it strongly;
osfin-vs-nse_ops likewise. **advantest vs osfin is the one I hold less firmly**
— different requirement counts, different mixes of required and preferred.
A tie between them would not be a wrong answer.

<!-- RESULT BELOW THIS LINE WAS WRITTEN AFTER THE RUN -->

---

## Result

Run `run_20260818T111956_d477e7f3`, 219s, three JDs against
`Best_withoutphoto.pdf`.

| rank | JD | score | matched | under-comm. | gaps |
|---:|---|---:|---:|---:|---:|
| 1 | `advantest_ai_engineering_intern` | 60.7% | 9 | 6 | 6 |
| 2 | `osfin_implementation_engineer` | 44.4% | 3 | 2 | 4 |
| 3 | `nse_technology_operations` | 20.8% | 3 | 4 | 17 |

**The ordering matches the pre-registered manual ranking exactly:
advantest > osfin > nse_ops. SM4 is met.**

The stated reasons also match the *grounds* given in the pre-registration, not
just the order:

| JD | predicted shortfall | system's reason |
|---|---|---|
| advantest | gaps would be preferred items | "only minor gaps in preferred AI tools" |
| osfin | the behavioural half, not the technical | "required gaps in independence and communication" |
| nse_ops | almost nothing evidenced | "heavy gaps across seventeen required … competencies" |

No ties were emitted. The pre-registration allowed for advantest/osfin tying;
the system separated them by 16 points, which the score spread supports.

### What this test does not establish

The three JDs were chosen to **span** the range, which makes this a favourable
case for a system whose measured weakness is fine-grained rank (README status
note, v1.1). A 60.7 / 44.4 / 20.8 spread is exactly the coarse separation the
system is claimed to do well. **This result confirms that claim; it does not
extend it.** Ranking three JDs that all scored within a few points of each
other is the case that would probe the weakness, and it is not tested here.

---

## An unplanned finding: rewording can change a verdict, not just a name

`osfin_implementation_engineer` was run twice within twenty minutes — once in
a two-JD comparison (`run_20260818T111439_539ad7a2`) and once here
(`run_20260818T112121_bc942855`). It scored **50.0%** and then **44.4%**.

Both runs extracted **the same nine requirements** with **the same
denominator**. So this is *not* the denominator effect D3 already documents.
Four requirements were merely reworded between parses:

| run A | run B | verdict |
|---|---|---|
| `automation projects` | `automation projects experience` | matched → matched |
| `working independently` | `working independently with minimal guidance` | gap → gap |
| `sense of responsibility and ownership` | `strong sense of responsibility and ownership` | gap → gap |
| `communication skills` | **`Strong communication skills`** | **weak → gap** |

Three rewordings were inert. **One flipped the verdict**, and that single flip
is the whole 5.6-point difference.

The flip is not a retrieval difference — both runs retrieved the same top three
chunks (`skills-fb9d4fa6`, `achievements-a16a3378`, `experience-0f79372f`):

> **A, given `communication skills` → weak:** "The resume lists language
> fluency and documents community outreach and coordination tasks, which
> require communication, but it lacks an explicit demonstration of *strong*
> professional communication skills."
>
> **B, given `Strong communication skills` → gap:** "The resume lists language
> proficiencies and documents business insights, but lacks any evidence of
> direct customer interaction or communication skills used to gather
> requirements."

**Each verdict is defensible on its own input.** "Strong communication skills"
is a higher bar than "communication skills", and the classifier applied the
bar it was given — run A's justification even reaches for the word *strong* to
explain why it stopped short of matched. The classifier is behaving correctly.
The non-determinism is upstream, in whether the extractor carries the JD's
adjective into the requirement name.

**Why this matters beyond D3 as written.** D3 was recorded as a *naming and
counting* problem: names vary, so the denominator moves, so absolute scores are
not quotable. This shows the mechanism is broader — **an extraction rewording
can propagate into a different verdict on identical evidence.** The existing
limitation ("absolute match scores are not quotable") already covers the
consequence, but it understated the cause.

It also bounds this very test: the ordering was reproduced across two runs for
the JDs common to both (advantest was identical at 60.7%, 9/6/6, in each),
while osfin moved 5.6 points without changing rank. Coarse separation survived
the wobble. That is consistent with the v1.1 claim, and is the second
independent observation of it.
