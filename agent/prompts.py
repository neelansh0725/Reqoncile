"""Agent prompts — classification (T029-T030) and rewriting (T040).

Both live here so every instruction the model receives is reviewable in one
file. The Matched/Weak/Gap call is the project's core reasoning step and the
rewrite prompt is its main safety surface, so neither should be scattered
through the modules that call them.

Two things in this prompt are load-bearing and were derived from measurement,
not taste (see `test_data/retrieval_notes.md`):

1. **The similarity score is not the decision rule.** On the real resume,
   requirements genuinely absent from it scored 0.123-0.374, while correct
   paraphrase matches scored 0.195-0.402. The ranges overlap almost entirely
   -- an absent "Salesforce CRM administration" outscored six of eight correct
   matches. Any threshold that admits the true matches also admits the absent
   ones, so the prompt tells the model to read the text and ignore the number.

2. **Retrieval always returns k chunks.** There is no empty result set to
   signal "nothing relevant". The model is therefore told explicitly that
   receiving chunks is not evidence that the requirement is met -- the chunks
   are simply the closest things in the document, however far away that is.
"""

from __future__ import annotations

from typing import Sequence

from schemas import Requirement, ResumeChunk, RetrievedChunk

CLASSIFICATION_SYSTEM = """\
You judge whether a candidate's resume evidences one specific job requirement.

You are given the requirement and the handful of resume excerpts that are
closest to it. Return exactly one verdict.

## The three verdicts

**matched** — the resume clearly evidences this requirement. The candidate has
demonstrably done this thing, and says so in terms a reader would recognise.

**weak** — the resume evidences this requirement, but under-communicates it.
The underlying work is genuinely there; it is described in vague, generic, or
non-standard language, or buried inside a bullet about something else, so a
reader scanning for this requirement could miss it.

**gap** — the resume does not evidence this requirement. Nothing in the
excerpts shows the candidate has done this.

## The distinction that matters most: weak vs gap

This is the judgement you are here to make, so make it deliberately.

Ask one question: **does the retrieved text actually show the candidate doing
this thing, in any wording?**

- Yes, and it is clearly stated → **matched**
- Yes, but a reader could easily miss it → **weak**
- No → **gap**

A **weak** verdict requires that the evidence really is present. "Related
topic", "adjacent technology", or "they could probably do it" is not evidence.
If the candidate has used Docker and the requirement is Kubernetes, that is a
**gap**, not a weak match — container experience is not orchestration
experience. Calling that weak would invent experience the candidate does not
have.

A **gap** verdict is not a failure of retrieval. It is a legitimate, useful
answer, and stating it plainly is more valuable to the candidate than a
generous reading that falls apart in an interview.

## Two things that are NOT evidence

**The similarity scores are unreliable — do not use them to decide.** They are
shown only so you know how confident the search was. On real data, skills the
candidate genuinely lacked scored *higher* than skills they genuinely had. A
high score does not mean the requirement is met; a low score does not mean it
is missing. Read the excerpt text and judge that.

**Receiving excerpts is not evidence.** The search always returns its closest
few excerpts, no matter how distant. If none of them show the candidate doing
this thing, the answer is **gap**, even though you were handed several
excerpts.

## Citing evidence

- For **matched** and **weak**, list the chunk ids that actually support your
  verdict, most convincing first. Only cite ids from the excerpts provided.
- For **gap**, cite nothing. An empty list is required.

## Justification

One or two sentences. Refer to what the resume specifically says — quote or
closely paraphrase the wording you relied on. Do not mention scores, rankings,
or the retrieval process. For a gap, say what is missing rather than
describing what was retrieved instead.

## Where the excerpt appears decides matched vs weak

This rule resolves the most common ambiguity, so apply it directly:

- The requirement named **only** in a SKILLS list, with nothing showing it in
  use → **weak**. A list entry asserts familiarity; it does not evidence
  having done anything, and that is precisely the under-communication a
  rewrite should fix.
- The requirement shown **being used** in EXPERIENCE or PROJECTS — built,
  deployed, optimised, containerised, queried — → **matched**, whether or not
  it also appears in the skills list.

So a tool that appears in both a skills list *and* a project bullet
describing its use is **matched**, not weak. Look across all the excerpts
before deciding; do not stop at the skills line.
"""

# Few-shot examples. Deliberately unrelated to the resume under test so they
# teach the distinction rather than the answers.
CLASSIFICATION_EXAMPLES = """\
## Worked examples

**Requirement:** SQL (technical, required)
**Excerpts:** `[experience-1 | experience | 0.61]` "Optimized SQL queries to
cut report load time from 40s to under 3s."
→ **matched.** The resume states SQL work directly and shows a concrete
outcome. Evidence: experience-1.

**Requirement:** Workflow orchestration (technical, required)
**Excerpts:** `[projects-7 | projects | 0.24]` "Wrote a script that runs the
nightly imports in order and retries the ones that fail."
→ **weak.** The candidate has built dependency-ordered, retrying scheduled
jobs — that is orchestration — but never uses the term, so a reader scanning
for it would miss it. Evidence: projects-7. Note the low score did not make
this a gap.

**Requirement:** Kubernetes (technical, required)
**Excerpts:** `[skills-2 | skills | 0.39]` "Tools: Docker, Git, Postman."
`[projects-4 | projects | 0.31]` "Containerised the API with Docker Compose."
→ **gap.** Docker and Compose are containerisation, not cluster
orchestration; nothing here shows Kubernetes. The high score on an adjacent
technology is exactly the case where the number misleads. Evidence: none.

**Requirement:** Stakeholder communication (soft, required)
**Excerpts:** `[experience-9 | experience | 0.28]` "Ran fortnightly reviews
with the partner teams and the business owners to agree priorities."
→ **weak.** Recurring cross-team priority meetings are stakeholder
communication; the resume never names the skill. Evidence: experience-9.
"""

CLASSIFICATION_USER = """\
Classify this requirement against the resume excerpts below.

<requirement>
name: {name}
category: {category}
necessity: {necessity}
stated in the job description as: "{source_text}"
</requirement>

<resume_excerpts count="{count}">
{excerpts}
</resume_excerpts>
"""

_NO_EXCERPTS = (
    "(no excerpts were retrieved — the resume index is empty for this query)"
)


def render_excerpts(retrieved: Sequence[RetrievedChunk]) -> str:
    """Render retrieved chunks with the ids the model must cite back."""
    if not retrieved:
        return _NO_EXCERPTS
    blocks = []
    for hit in retrieved:
        # A lexical rescue has no cosine score. Printing "similarity 0.000"
        # would read as "no match at all" and bias the model toward gap on
        # exactly the evidence the embedding failed to surface.
        score = (
            "keyword match"
            if hit.retriever == "lexical"
            else f"similarity {hit.similarity:.3f}"
        )
        blocks.append(
            f"[{hit.chunk.chunk_id} | {hit.chunk.section.value} | {score}]"
            f"\n{hit.chunk.text}"
        )
    return "\n\n".join(blocks)


def build_classification_messages(
    requirement: Requirement,
    retrieved: Sequence[RetrievedChunk],
) -> tuple[str, str]:
    """Return (system, user) for classifying one requirement (T028)."""
    system = f"{CLASSIFICATION_SYSTEM}\n{CLASSIFICATION_EXAMPLES}"
    user = CLASSIFICATION_USER.format(
        name=requirement.name,
        category=requirement.category.value,
        necessity=requirement.necessity.value,
        source_text=requirement.source_text,
        count=len(retrieved),
        excerpts=render_excerpts(retrieved),
    )
    return system, user


# ==========================================================================
# Rewrite suggestions (T040, FR10-FR12, R2)
# ==========================================================================

REWRITE_SYSTEM = """\
You rewrite a single resume bullet so that it makes explicit an ability the
candidate already demonstrates but has under-communicated.

You are given one job requirement and one bullet from the candidate's resume.
The bullet has already been judged to evidence that requirement in vague or
non-standard wording. Your job is to surface it — not to strengthen it.

## The one rule

**Every fact in your rewrite must already be present in the original bullet.**

You are re-describing existing work, not improving it. The candidate will be
asked about this line in an interview. Anything you add that they did not do
will fail there, and that failure is far more costly to them than a bullet
that reads plainly.

## You may

- Use the requirement's own vocabulary **when the original supports it** —
  "ran the imports in order and retried failures" genuinely is orchestration,
  so naming it is surfacing, not inventing.
- Make an implicit capability explicit.
- Reorder the sentence so the relevant work leads.
- Tighten wording, remove filler.

## You may not add

- **Tools, languages, frameworks or platforms** not named in the original.
- **Numbers of any kind** — percentages, durations, row counts, team sizes,
  latencies, user counts. If the original has no number, yours has no number.
- **Outcomes or impact** not stated: revenue, savings, adoption, speedups.
- **Scale or seniority**: "large-scale", "production", "enterprise", "led",
  "owned", "mentored", "cross-functional" — unless the original says so.
- **Duration or frequency** not stated: "over two years", "daily".

Uncertain whether something is present? It is not. Leave it out.

## Declining is a correct answer

If the bullet cannot support the requirement without adding something, set
`declined` to true, leave `suggested_text` empty, and say why in the
rationale. A declined rewrite is a good outcome — it means the system refused
to manufacture experience. Never stretch a bullet to avoid declining.

## Form

One bullet, roughly the length of the original. Same voice as a resume line —
start with a verb, no first person, no trailing period unless the original has
one. Do not add a preamble or explain yourself inside `suggested_text`.
"""

REWRITE_EXAMPLES = """\
## Worked examples

**Requirement:** Workflow orchestration
**Original:** "Wrote a script that runs the nightly imports in order and
retries the ones that fail."
→ suggested_text: "Orchestrated nightly import workflows with ordered
execution and automatic retry on failure"
→ rationale: "Names the orchestration the bullet already describes; every
element — ordering, retries, scheduling — is in the original."
*Nothing was added. "Orchestrated" renames work that is fully stated.*

**Requirement:** Performance optimisation
**Original:** "Improved the checkout page load."
→ suggested_text: "Optimised checkout page load performance"
→ rationale: "Surfaces 'optimisation'; no figure is given because the
original states none."
*Note what did NOT happen: no "by 40%", no "under 2s". Inventing a plausible
number is the single most common failure here, and the most damaging.*

**Requirement:** Kubernetes
**Original:** "Containerised the API with Docker Compose."
→ declined: true, suggested_text: ""
→ rationale: "The bullet shows containerisation with Docker Compose, not
cluster orchestration. Rewriting it to mention Kubernetes would claim
experience the candidate does not have."
*Correct outcome. The rewrite was refused rather than stretched.*

**Requirement:** Stakeholder communication
**Original:** "Ran fortnightly reviews with the partner teams and the
business owners to agree priorities."
→ suggested_text: "Led fortnightly stakeholder reviews with partner teams and
business owners to align on priorities"
→ rationale: "Names the stakeholders and the communication cadence the bullet
already describes."
*"Led" is acceptable only because "Ran" is in the original. It would not be
acceptable against "Attended".*
"""

REWRITE_USER = """\
Rewrite this resume bullet to surface the requirement, using only what the
bullet already says.

<requirement>
name: {name}
stated in the job description as: "{source_text}"
</requirement>

<resume_bullet section="{section}">
{original_text}
</resume_bullet>
"""


def build_rewrite_messages(
    requirement: Requirement,
    chunk: ResumeChunk,
) -> tuple[str, str]:
    """Return (system, user) for rewriting one bullet (T040).

    Exactly one chunk is passed, never the whole retrieved set: a rewrite must
    be traceable to a single resume line (FR11), and handing the model several
    bullets invites it to blend facts from one into another — which is
    fabrication even though every fact appears somewhere in the resume.
    """
    system = f"{REWRITE_SYSTEM}\n{REWRITE_EXAMPLES}"
    user = REWRITE_USER.format(
        name=requirement.name,
        source_text=requirement.source_text,
        section=chunk.section.value,
        original_text=chunk.text,
    )
    return system, user


# --- Interview prep for gaps (T079, FR21-FR23) ---------------------------

INTERVIEW_PREP_SYSTEM = """\
You prepare a candidate to talk honestly about a gap in their resume.

A gap means the resume shows **no evidence** of this requirement. You are not
here to help them hide that. You are here to help them walk into the room able
to discuss it without bluffing and without falling apart.

## What to produce

Two or three questions an interviewer would plausibly ask to probe this
specific requirement. For each, a short note on what an honest, defensible
answer would need to **cover**.

## The note is a description, never a draft

Write what a good answer must address, in the second person or impersonally:

- GOOD: "Should acknowledge you have not used Kubernetes in production, then
  show that you understand what problem it solves and describe the closest
  thing you have actually done -- containerising a service with Docker."
- BAD: "I haven't used Kubernetes in production, but I containerised a
  service with Docker, so I understand the fundamentals."

The second is a line to memorise and recite. That is exactly what this must
not produce. **Never write in the first person.** Never put words in the
candidate's mouth.

**This includes illustrative examples.** Do not append a quoted specimen
answer — no "For example, 'I worked with...'", no "They might say: '...'".
A quoted example is still a line to recite, and it is the form this mistake
usually takes. Describe what the answer must address and stop there.

## Honesty is the point

- **Never invent experience**, or imply the candidate has any, or suggest they
  frame something as more than it was.
- An honest answer usually has three parts: acknowledge the gap plainly, show
  you understand why the skill matters, and point to the nearest genuine
  adjacent experience or to how you would go about learning it.
- "Say you are a fast learner" is not preparation. Be specific to *this*
  requirement.
- If the resume genuinely has no adjacent experience, say the answer should
  acknowledge that directly. That is a better outcome than a stretch an
  interviewer will see through.

## Questions

Ask what an interviewer would actually ask -- practical, specific to the
requirement, the kind of thing that gets asked in a real screen. Not quiz
trivia, and not the same question phrased three ways.
"""

INTERVIEW_PREP_USER = """\
The candidate is applying for a role requiring: **{requirement}**
({necessity}, {category})

The job description phrases it as:
{source_text}

Their resume shows no evidence of this. The classifier's finding:
{justification}

{adjacent}Write 2-3 interview questions probing this gap, each with a note on \
what an honest answer would need to cover.
"""
