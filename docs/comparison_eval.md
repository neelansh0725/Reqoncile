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
