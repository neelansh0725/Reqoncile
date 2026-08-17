"""Shared data models.

Grown per phase rather than defined all at once -- JD models land here first
(FR2), classification and rewrite models arrive with their own phases so no
task has to revisit a model it didn't introduce.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


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
