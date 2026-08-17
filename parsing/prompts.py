"""Prompt templates for JD extraction (FR2).

Kept separate from the chain wiring so prompt iteration is a one-file diff and
the text is easy to review on its own.

**The domain-list granularity rule (defect D3).** Extraction was measured
non-reproducible: parsing `mathco_ai_analyst.txt` three times with
`temperature=0.0` gave 6, 6 and 12 requirements. The whole difference was one
sentence listing six AI domains -- one reading treated it as six requirements,
another as none, because the sentence is phrased as a responsibility under an
"AI/ML models" umbrella.

The score's denominator is the requirement count, so unstable extraction makes
the score itself unquotable. The fix is a stated rule rather than sampling
several parses and taking a majority: sampling costs N x the quota, and picks
between two readings by vote rather than by anything defensible.

A first version of the rule was too broad: scoped to "distinct technical
domains", it also shredded EY's single degree phrase
`(BE - B.Tech / IT, Computer Science or Circuit branches)` into five
requirements and took that JD from ~12 requirements to ~54. The rule is now
scoped to technologies/tools/domains and carries an explicit counter-example
for degree and eligibility phrases, plus a discriminating test for ambiguous
lists (all-of -> split; alternatives-satisfying-one-bar -> do not).

Both worked examples live in `JD_EXTRACTION_SYSTEM`. Residual variance after
the rule -- including cross-parse *naming* instability, which is a separate
phenomenon the rule does not address -- is recorded in `docs/defects.md` (D3)
and stated as a limitation in the README.
"""

from __future__ import annotations

JD_EXTRACTION_SYSTEM = """\
You extract structured requirement lists from job descriptions.

Emit one entry per distinct requirement the JD actually states. Work from the \
text in front of you: do not add requirements that are typical for the role but \
absent from this posting, and do not drop ones that are stated casually or \
buried in prose.

For each requirement set three fields.

category:
- technical: a tool, language, framework, platform, or technique (Python, \
LangChain, SQL, distributed systems, A/B testing).
- soft: a behavioural or interpersonal quality (communication, stakeholder \
management, working independently).
- eligibility: a credential or gate (a degree, a field of study, years of \
experience, graduation year, work authorisation, location).

necessity:
- required: the JD presents it as a must-have -- "required", "must have", \
"you have", or a plain declarative in a requirements list.
- preferred: the JD hedges it -- "preferred", "nice to have", "a plus", \
"bonus", "desirable", "familiarity with".
When the framing is genuinely ambiguous, choose required; over-reporting a gap \
is safer here than hiding one.

source_text: the verbatim line or phrase the requirement came from, copied \
exactly. Do not paraphrase it.

Split compound lines. "Experience with Python, SQL, and cloud platforms" is \
three requirements, each carrying that same source line. Keep names short and \
canonical -- "Python", not "strong Python programming skills".

## Lists of technologies — SPLIT

A comma-delimited list of technologies, tools, or technical domains is **one \
requirement per item**, never a single combined requirement, and never \
omitted. This holds even when the items sit under a broader umbrella term: \
the umbrella is a heading, not a substitute for what it lists.

Worked example — this SPLITS:

  "Build and deploy AI/ML models -- spanning Machine Learning, Deep Learning, \
  Neural Networks, NLP, Computer Vision, and Generative AI -- to solve \
  business problems"

That is **six** requirements: Machine Learning, Deep Learning, Neural \
Networks, NLP, Computer Vision, Generative AI. Each carries that same source \
line. It is not one requirement called "AI/ML models", and the six are not \
dropped because the sentence reads as a responsibility -- the candidate is \
being asked to have each of them.

Same reading for "React, Vue, or Angular" (three) and "AWS, Azure, GCP" \
(three).

## Degree and eligibility phrases — DO NOT SPLIT

A degree, eligibility, or qualification phrase is **exactly one requirement**, \
however many alternatives it lists. Degree names, fields of study, branches, \
institutions, and graduation years inside one such phrase describe a single \
bar the candidate either clears or does not.

Worked example — this does NOT split:

  "(BE - B.Tech / IT, Computer Science or Circuit branches)"

That is **one** requirement, category `eligibility`, named for the whole bar: \
"BE/B.Tech in IT, Computer Science or Circuit branches". It is **not** five \
requirements. "IT" and "Computer Science" here are alternative fields of \
study inside one degree requirement, not separate technical requirements -- \
even though the same words would be technical requirements in another \
context.

**The test when a list is ambiguous:** would the candidate need *all* of the \
items (or list them separately on a resume)? Then split. Do the items instead \
offer *alternative ways to satisfy one bar* -- any one of these degrees, any \
one of these branches? Then it is one requirement.

Skip company boilerplate, benefits, EEO statements, and descriptions of what \
the team does. Extract only what is being asked of the candidate.
"""

JD_EXTRACTION_USER = """\
Extract the requirement list from this job description.

<job_description>
{jd_text}
</job_description>
"""


def build_extraction_messages(jd_text: str) -> tuple[str, str]:
    """Return (system, user) for the JD extraction call."""
    return JD_EXTRACTION_SYSTEM, JD_EXTRACTION_USER.format(jd_text=jd_text)
