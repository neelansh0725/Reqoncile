"""Shared data models.

Grown per phase rather than defined all at once -- JD models land here first
(FR2), classification and rewrite models arrive with their own phases so no
task has to revisit a model it didn't introduce.
"""

from __future__ import annotations

from enum import Enum

import re

from pydantic import BaseModel, Field, field_validator, model_validator

# FR23: phrasing that marks text as an answer written *as the candidate*.
# Deliberately narrow -- second person ("you should explain...") is the correct
# register for this field and must not trip it.
_FIRST_PERSON_RE = re.compile(
    r"\b(?:I|I'm|I've|I'd|I'll|me|my|mine|myself|we|we're|we've|our|ours)\b",
    re.IGNORECASE,
)


class Category(str, Enum):
    """FR2: requirement type."""

    TECHNICAL = "technical"
    SOFT = "soft"
    ELIGIBILITY = "eligibility"


class Necessity(str, Enum):
    """FR2: required vs preferred."""

    REQUIRED = "required"
    PREFERRED = "preferred"


class Section(str, Enum):
    """Resume section a line belongs to (T018).

    Carried through chunking into retrieval metadata, so the classifier can
    tell a claim made under EXPERIENCE (a thing done at a job) from the same
    words under SKILLS (a thing listed). That distinction is exactly what
    separates a Matched from a Weak Match in FR9.
    """

    HEADER = "header"          # name + contact block, before any section
    SUMMARY = "summary"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    SKILLS = "skills"
    ACHIEVEMENTS = "achievements"
    CERTIFICATIONS = "certifications"
    ACTIVITIES = "activities"
    OTHER = "other"


class Requirement(BaseModel):
    """One extracted JD requirement.

    `source_text` is the verbatim JD line it came from -- it keeps extraction
    auditable, and gives the classifier the original phrasing rather than only
    the normalised name.
    """

    name: str = Field(
        ...,
        description=(
            "Short canonical name of the skill or qualification, e.g. 'Python' "
            "or 'Bachelor's degree in Computer Science'."
        ),
    )
    category: Category = Field(
        ...,
        description=(
            "technical = a tool, language, framework, or technique. "
            "soft = a behavioural or interpersonal skill. "
            "eligibility = a credential, degree, visa, or experience-duration bar."
        ),
    )
    necessity: Necessity = Field(
        ...,
        description=(
            "required = the JD states it as a must-have. "
            "preferred = the JD frames it as nice-to-have, a plus, or desirable."
        ),
    )
    source_text: str = Field(
        ...,
        description="The verbatim line or phrase from the JD this came from.",
    )

    @field_validator("name", "source_text")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("must not be empty or whitespace-only")
        return cleaned


class ResumeChunk(BaseModel):
    """One retrievable unit of resume content (T019, FR5).

    `chunk_id` is derived from the chunk's own text, not its position, so it
    survives edits elsewhere in the document. That is what makes a rewrite
    suggestion traceable back to the exact line it came from (FR11) even after
    the resume has been reordered, and what lets version diffing (FR24-FR27)
    tell a moved bullet from a rewritten one.
    """

    chunk_id: str = Field(..., description="Stable, content-derived identifier.")
    text: str
    section: Section
    source_line_no: int = Field(
        ..., description="1-based first line of this chunk in the normalised text."
    )

    @field_validator("text")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk text must not be empty")
        return value


class RetrievedChunk(BaseModel):
    """A resume chunk returned for a requirement, with its similarity (FR6).

    `similarity` is carried into the classifier prompt as context, never as
    the decision rule. FR9 is explicit that Gap-vs-Weak is a reasoning call
    about what the retrieved text actually says, not a threshold on this
    number — the score only tells the model how confident retrieval was.
    """

    chunk: ResumeChunk
    similarity: float = Field(
        ..., description="Cosine similarity in [-1, 1]; higher is closer."
    )
    retriever: str = Field(
        default="dense",
        description=(
            "'dense' = found by embedding similarity. 'lexical' = found by "
            "BM25 term match after the embedding missed it (T026a); its "
            "`similarity` is not meaningful and must not be shown as 0.0, "
            "which would read as 'no match at all'."
        ),
    )


class MatchLabel(str, Enum):
    """Outcome of classifying one requirement against the resume (FR7)."""

    MATCHED = "matched"
    WEAK = "weak"
    GAP = "gap"
    # Not a verdict the model can return. Set by the pipeline when a single
    # requirement's classification fails, so the rest of the report still
    # generates (NFR3) and the failure is reported rather than silently
    # becoming a Gap — claiming a gap we never actually assessed would be
    # exactly the over-claiming G5 forbids.
    ERRORED = "errored"


class ClassificationVerdict(BaseModel):
    """What the model returns for one requirement.

    Deliberately narrow: the model supplies only the judgement and its
    evidence. Similarity scores, the requirement itself, and the retrieved set
    are attached by the pipeline afterwards — asking the model to echo data we
    already hold invites it to alter them.
    """

    label: MatchLabel = Field(
        ...,
        description=(
            "matched = the resume clearly evidences this. "
            "weak = the resume shows related work but under-states it. "
            "gap = the resume does not evidence this at all."
        ),
    )
    justification: str = Field(
        ...,
        min_length=1,
        description=(
            "One or two sentences citing what the resume actually says. "
            "Must reference concrete resume content, not a similarity score."
        ),
    )
    evidence_chunk_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Chunk ids supporting a matched/weak verdict. Empty for a gap — "
            "a gap means none of the retrieved chunks evidence the requirement."
        ),
    )

    @field_validator("label", mode="before")
    @classmethod
    def _reject_errored(cls, value: object) -> object:
        if value in (MatchLabel.ERRORED, MatchLabel.ERRORED.value):
            raise ValueError("'errored' is a pipeline state, not a model verdict")
        return value


class Classification(BaseModel):
    """The full record for one classified requirement (FR7-FR9)."""

    requirement: Requirement
    label: MatchLabel
    justification: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    # Every chunk retrieval offered, with its similarity. Kept for the
    # reasoning trace (FR16) and so an evaluation can see what the model was
    # actually looking at when it decided.
    retrieved_scores: dict[str, float] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def _check_evidence_matches_label(self) -> "Classification":
        has_evidence = bool(self.evidence_chunk_ids)

        if self.label is MatchLabel.GAP and has_evidence:
            raise ValueError(
                "a gap cites no evidence: if a retrieved chunk supports the "
                "requirement, the verdict is matched or weak, not gap"
            )
        if self.label in (MatchLabel.MATCHED, MatchLabel.WEAK) and not has_evidence:
            raise ValueError(
                f"a {self.label.value} verdict must cite at least one evidence "
                "chunk (FR8: justified against actual resume text)"
            )
        if self.label is MatchLabel.ERRORED:
            if has_evidence:
                raise ValueError("an errored classification cites no evidence")
            if not self.error:
                raise ValueError("an errored classification must carry the error")
        return self

    @property
    def is_assessed(self) -> bool:
        """False for ERRORED — excluded from scoring, like eligibility."""
        return self.label is not MatchLabel.ERRORED


class RewriteDraft(BaseModel):
    """What the model returns for one rewrite (T039, FR10).

    Narrow on purpose, mirroring `ClassificationVerdict`: the model supplies
    only the new wording and why. It is never given the chance to restate the
    source chunk id or the original text, because those are the traceability
    record (FR11) — a model that can rewrite its own citation can quietly
    detach a suggestion from the line it came from.
    """

    suggested_text: str = Field(
        default="",
        description=(
            "The rewritten bullet, using only facts already in the original. "
            "Empty if the original does not actually support the requirement."
        ),
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description=(
            "One sentence on what was made explicit and why, or — if "
            "suggested_text is empty — why no honest rewrite is possible."
        ),
    )
    declined: bool = Field(
        default=False,
        description=(
            "True when no rewrite can be made without inventing facts. "
            "Declining is a valid, expected outcome (R2)."
        ),
    )


class RewriteSuggestion(BaseModel):
    """A rewrite proposal, bound to the resume line it came from (FR10-FR11).

    `source_chunk_id` and `original_text` are attached by the pipeline from the
    retrieved evidence, never by the model. That is what makes FR11's "show
    which original resume line a suggestion was derived from" a structural
    guarantee rather than a hope.
    """

    requirement: Requirement
    source_chunk_id: str = Field(
        ...,
        min_length=1,
        description="Chunk this rewrite is derived from. Never empty (FR11).",
    )
    original_text: str = Field(
        ..., min_length=1, description="Verbatim text of the source chunk."
    )
    suggested_text: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    # Populated by the grounding check (T043). Non-empty means the suggestion
    # introduced something the source does not support and must be surfaced to
    # the user rather than shipped silently.
    grounding_flags: list[str] = Field(default_factory=list)

    @field_validator("source_chunk_id", "original_text", "suggested_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def _must_actually_change_something(self) -> "RewriteSuggestion":
        if self.suggested_text.strip() == self.original_text.strip():
            raise ValueError(
                "suggested_text is identical to the original; a no-op is not a "
                "suggestion and should have been declined instead"
            )
        return self

    @property
    def is_flagged(self) -> bool:
        return bool(self.grounding_flags)


class AlignmentReport(BaseModel):
    """The finished report for one JD/resume pair (T046, FR13-FR14).

    Renders as structured data for the UI and as text for direct use (FR14),
    from this one object.

    Note what is held separately: `eligibility` is a checklist the system
    never assessed (T015a), and `errored` records requirements it failed to
    assess (T032). Both are kept out of `classifications` and out of the
    score, because folding either into "gap" would report a finding that was
    never made.
    """

    run_id: str
    score: float = Field(..., ge=0.0, le=100.0)
    score_explanation: str
    score_is_meaningful: bool = Field(
        default=True,
        description="False when nothing could be scored; the 0.0 is not a verdict.",
    )

    classifications: list[Classification] = Field(default_factory=list)
    rewrites: list[RewriteSuggestion] = Field(default_factory=list)

    eligibility: list[Requirement] = Field(
        default_factory=list,
        description=(
            "Unassessed checklist (T015a) — location, degree, work "
            "authorisation. For the candidate to verify; never scored."
        ),
    )
    errored: list[Classification] = Field(
        default_factory=list,
        description="Requirements the system failed to assess (NFR3).",
    )

    summary: str = ""
    warnings: list[str] = Field(default_factory=list)

    def by_label(self, label: MatchLabel) -> list[Classification]:
        return [c for c in self.classifications if c.label is label]

    @property
    def matched(self) -> list[Classification]:
        return self.by_label(MatchLabel.MATCHED)

    @property
    def weak(self) -> list[Classification]:
        return self.by_label(MatchLabel.WEAK)

    @property
    def gaps(self) -> list[Classification]:
        return self.by_label(MatchLabel.GAP)

    @property
    def flagged_rewrites(self) -> list[RewriteSuggestion]:
        """Suggestions the grounding check marked (T043) — never hidden."""
        return [r for r in self.rewrites if r.is_flagged]


class GapQuestion(BaseModel):
    """One interview question probing a gap, plus what to address (FR21-FR22).

    **FR23 is enforced by this schema, not requested in the prompt.** The field
    is `answer_should_cover` -- a description of what an honest answer needs to
    address -- and a validator rejects first-person phrasing outright. A model
    that starts drafting "I built a RAG pipeline..." fails validation rather
    than handing the candidate a fabricated line to memorise.

    Note the same limitation the grounding check carries (T044): this is a
    lexical guard. It catches answers written *as the candidate*, which is the
    form a memorisable fabrication takes. It cannot catch an impersonal
    sentence that still implies experience.
    """

    question: str = Field(
        ...,
        min_length=1,
        description="A question an interviewer would plausibly ask about this gap.",
    )
    answer_should_cover: str = Field(
        ...,
        min_length=1,
        description=(
            "What an honest, defensible answer would need to address. Describe "
            "the shape of a good answer in the second person or impersonally. "
            "This is NOT a sample answer and must never be written as the "
            "candidate speaking."
        ),
    )

    @field_validator("question", "answer_should_cover")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("must not be empty or whitespace-only")
        return cleaned

    @field_validator("answer_should_cover")
    @classmethod
    def _no_sample_answer(cls, value: str) -> str:
        """FR23: reject a drafted answer in the candidate's voice."""
        if _FIRST_PERSON_RE.search(value):
            raise ValueError(
                "must describe what an honest answer covers, not draft one in "
                "the candidate's voice (first-person phrasing found)"
            )
        return value


class GapPrep(BaseModel):
    """What the model returns for one gap (FR21).

    Two to three questions. Fewer than two is not preparation; more than three
    turns a single gap into a study list nobody reads.
    """

    questions: list[GapQuestion] = Field(..., min_length=2, max_length=3)


class GapPrepRecord(BaseModel):
    """One gap's prep, with the failure case kept visible (NFR3)."""

    requirement: str
    questions: list[GapQuestion] = Field(default_factory=list)
    error: str | None = None


class InterviewPrep(BaseModel):
    """Interview preparation for a report's gaps (FR21-FR23)."""

    run_id: str
    prepared: list[GapPrepRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def question_count(self) -> int:
        return sum(len(p.questions) for p in self.prepared)


class ChangeDirection(str, Enum):
    """Which way a requirement moved between resume versions (FR26)."""

    IMPROVED = "improved"
    REGRESSED = "regressed"
    UNCHANGED = "unchanged"
    # One side errored, so the move is unknown. Not "unchanged" -- claiming no
    # change we never established is the same over-claim as calling an
    # unassessed requirement a gap.
    INDETERMINATE = "indeterminate"


class RequirementChange(BaseModel):
    """One requirement's movement between two resume versions (FR26)."""

    requirement: str
    before: MatchLabel
    after: MatchLabel
    direction: ChangeDirection

    @property
    def moved(self) -> bool:
        return self.before is not self.after


class VersionDiff(BaseModel):
    """A diff of one JD against two resume versions (FR24-FR27).

    Computed in pure Python. There is no model call here: comparing two
    finished classifications is set arithmetic, and asking an LLM to do it
    would add a way to be wrong about something already known exactly.
    """

    run_id: str
    before_run_id: str
    after_run_id: str
    before_score: float | None = None
    after_score: float | None = None
    changes: list[RequirementChange] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    compared_nothing: bool = Field(
        default=False,
        description=(
            "True when neither version had a scoreable requirement, so the "
            "failure is in JD extraction rather than in the comparison."
        ),
    )

    @property
    def improved(self) -> list[RequirementChange]:
        return [c for c in self.changes
                if c.direction is ChangeDirection.IMPROVED]

    @property
    def regressed(self) -> list[RequirementChange]:
        return [c for c in self.changes
                if c.direction is ChangeDirection.REGRESSED]

    @property
    def unchanged(self) -> list[RequirementChange]:
        return [c for c in self.changes
                if c.direction is ChangeDirection.UNCHANGED]

    @property
    def indeterminate(self) -> list[RequirementChange]:
        return [c for c in self.changes
                if c.direction is ChangeDirection.INDETERMINATE]


class RankedJD(BaseModel):
    """One job description's position in a comparison (FR19)."""

    label: str = Field(..., description="Identifier for the JD, as supplied.")
    rank: int = Field(..., ge=1, description="1 is the best fit. Ties share a rank.")
    reason: str = Field(
        ..., min_length=1,
        description="One line on why it sits here, citing the actual findings.",
    )
    tied_with: list[str] = Field(
        default_factory=list,
        description=(
            "Other JDs too close to separate. Non-empty means the order "
            "between them is not resolvable, not that they are identical."
        ),
    )


class JDRanking(BaseModel):
    """What the model returns when ranking several JDs (FR19)."""

    ranked: list[RankedJD] = Field(default_factory=list)
    overall_note: str = Field(
        default="",
        description=(
            "At most two short sentences on the shape of the comparison. "
            "Stop after two sentences."
        ),
    )

    @field_validator("overall_note")
    @classmethod
    def _drop_degenerate_note(cls, value: str) -> str:
        """Discard a looping note instead of rendering it.

        Observed live: the model ran away on this field, emitting ~1200
        characters of "properly nicely well fine good ok yes sure alrightly
        indeed indeedly absolutely totally..." and exhausting the output budget
        before `ranked` was populated -- so the decorative field cost the
        actual ranking. Non-deterministic (a local re-run produced a clean
        103-character note), which is expected: the reasoning model ignores
        `temperature` entirely (D7).

        Dropped rather than raised. This field is decorative; the ranking is
        the substance, and failing validation here would discard a good
        ranking over a bad sentence. Dropped rather than truncated, because
        the first 200 characters of a degenerate note still read as broken.

        **Length is the only check, deliberately.** A vocabulary-repetition
        heuristic was written first and measured against the real failure: it
        scored 0.69 unique words against a healthy note's 0.89, nowhere near
        separable, because this model degenerates into *varied* filler
        ("henceforth therefrom thereupon herein therein whereby wherein")
        rather than repeating one word. The heuristic was removed rather than
        kept as reassurance that would never fire. Word count separates the
        two cleanly: 154 against 19.
        """
        note = " ".join(value.split())
        if not note:
            return ""
        # Two sentences is generously under 60 words. The observed failure was
        # 154 and still mid-sentence when the budget ran out.
        return "" if len(note.split()) > 60 else note


class ComparisonResult(BaseModel):
    """A multi-JD comparison run (FR17-FR20).

    Holds one full report per JD plus the ranking over them. The reports are
    produced by the unchanged single-JD pipeline -- this mode is a loop and a
    ranking step, not a different classification method (FR20).
    """

    run_id: str
    reports: list[AlignmentReport] = Field(default_factory=list)
    ranking: list[RankedJD] = Field(default_factory=list)
    overall_note: str = ""
    warnings: list[str] = Field(default_factory=list)

    @property
    def best(self) -> RankedJD | None:
        return min(self.ranking, key=lambda r: r.rank) if self.ranking else None


class RequirementSplit(BaseModel):
    """Requirements partitioned by how they can honestly be assessed (T015a).

    Eligibility requirements — location, degree, work authorisation, graduation
    year — are deliberately kept out of Matched/Weak/Gap classification. The
    retrieval-and-reason pipeline cannot honestly assess them: nothing in a
    resume semantically matches a city name, so a classifier would emit a
    confident Gap for every one and drag the match score down for reasons that
    have nothing to do with fit.

    They are reported as a checklist for the candidate to verify instead. That
    is the same honesty constraint as FR12/G5 — state the thing plainly rather
    than papering over it with an assessment the system cannot support.
    """

    classifiable: list[Requirement] = Field(
        default_factory=list,
        description="Technical and soft requirements -> the classifier (FR7-FR9).",
    )
    eligibility: list[Requirement] = Field(
        default_factory=list,
        description="Reported as an unassessed checklist, never classified.",
    )


class ParsedJD(BaseModel):
    """The full structured extraction for one job description (FR2)."""

    requirements: list[Requirement] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Non-fatal extraction problems. Lets a partial parse still be "
            "usable rather than raising (NFR3)."
        ),
    )

    @property
    def required(self) -> list[Requirement]:
        return [r for r in self.requirements if r.necessity is Necessity.REQUIRED]

    @property
    def preferred(self) -> list[Requirement]:
        return [r for r in self.requirements if r.necessity is Necessity.PREFERRED]

    def split(self) -> RequirementSplit:
        """Partition into classifiable vs eligibility (T015a).

        Every requirement lands in exactly one bucket -- the split is by
        category alone, so it is total and order-preserving. Call this before
        retrieval so eligibility items never reach the embedder or the
        classifier; that also shrinks the per-JD classification fan-out, which
        is the main lever on end-to-end latency (NFR1).
        """
        classifiable: list[Requirement] = []
        eligibility: list[Requirement] = []
        for requirement in self.requirements:
            target = (
                eligibility
                if requirement.category is Category.ELIGIBILITY
                else classifiable
            )
            target.append(requirement)
        return RequirementSplit(classifiable=classifiable, eligibility=eligibility)
