"""Rewrite suggestion generation (T041-T043, FR10-FR12).

Runs on the **generation** tier (local Ollama): this step rephrases text that
retrieval has already produced and the classifier has already judged, so it
does not need the reasoning tier's quota. That also keeps rewrites available
when the hosted daily allowance is spent.

Three guarantees, each enforced in code rather than by prompt alone:

* **Only Weak Matches are rewritten (FR12).** A Gap raises. Gaps are reported,
  not papered over -- generating a rewrite for one would be inventing
  experience, which is exactly what R2 warns about.
* **Every suggestion carries its source (FR11).** The chunk id and verbatim
  original text come from the retrieved evidence, never from the model.
* **Every suggestion is grounding-checked (T043).** Unsupported additions are
  flagged and surfaced, not silently shipped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

from agent.grounding import check_grounding
from agent.prompts import build_rewrite_messages
from config import settings
from llm_client import GENERATION, LLMCallError, complete_structured
from logging_utils import log_event
from schemas import (
    Classification,
    MatchLabel,
    ResumeChunk,
    RewriteDraft,
    RewriteSuggestion,
)

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)


class RewriteNotApplicable(ValueError):
    """Raised when a rewrite is requested for something that must not have one.

    Deliberately an exception rather than a quiet `None`: asking for a rewrite
    of a Gap is a caller bug with real consequences (FR12), and it should be
    impossible to ignore by accident.
    """


def _load_chunk(collection: "Collection", chunk_id: str) -> ResumeChunk | None:
    try:
        got = collection.get(ids=[chunk_id], include=["documents", "metadatas"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load chunk %s: %s", chunk_id, exc)
        return None

    ids = got.get("ids") or []
    if not ids:
        return None
    documents = got.get("documents") or [""]
    metadatas = got.get("metadatas") or [{}]
    metadata = metadatas[0] or {}
    from schemas import Section

    return ResumeChunk(
        chunk_id=ids[0],
        text=documents[0] or "",
        section=Section(metadata.get("section", Section.OTHER.value)),
        source_line_no=int(metadata.get("source_line_no", 0) or 0),
    )


def suggest_rewrite(
    classification: Classification,
    collection: "Collection",
    run_id: str | None = None,
    tier: str = GENERATION,
) -> RewriteSuggestion | None:
    """Propose a rewrite for one Weak Match (FR10).

    Returns None when the model declines, when the source chunk cannot be
    resolved, or when the call fails -- all of which are non-fatal: a missing
    suggestion degrades the report, a wrong one misleads the candidate.

    Raises `RewriteNotApplicable` for any label other than `weak`.
    """
    if classification.label is not MatchLabel.WEAK:
        raise RewriteNotApplicable(
            f"rewrites are only generated for weak matches; "
            f"{classification.requirement.name!r} is {classification.label.value}. "
            "Gaps are reported, never rewritten (FR12)."
        )
    if not classification.evidence_chunk_ids:
        raise RewriteNotApplicable(
            f"{classification.requirement.name!r} is weak but cites no evidence; "
            "there is no source line to rewrite"
        )

    # The classifier is told to list evidence most-convincing-first, so the
    # first id is the line a reader would point at.
    source_id = classification.evidence_chunk_ids[0]
    chunk = _load_chunk(collection, source_id)
    if chunk is None or not chunk.text.strip():
        logger.warning("evidence chunk %s could not be loaded", source_id)
        if run_id:
            log_event(run_id, "rewrite.missing_chunk",
                      {"requirement": classification.requirement.name,
                       "chunk_id": source_id})
        return None

    system, user = build_rewrite_messages(classification.requirement, chunk)

    try:
        draft = complete_structured(RewriteDraft, user=user, system=system, tier=tier)
    except LLMCallError as exc:
        logger.warning("rewrite failed for %r: %s",
                       classification.requirement.name, exc)
        if run_id:
            log_event(run_id, "rewrite.error",
                      {"requirement": classification.requirement.name,
                       "chunk_id": source_id, "error": str(exc)})
        return None

    suggested = (draft.suggested_text or "").strip()

    if draft.declined or not suggested:
        # An expected, healthy outcome -- the model refused to stretch the
        # bullet. Logged so the fabrication-boundary test (T044) can count it.
        if run_id:
            log_event(run_id, "rewrite.declined",
                      {"requirement": classification.requirement.name,
                       "chunk_id": source_id, "rationale": draft.rationale})
        return None

    if suggested == chunk.text.strip():
        if run_id:
            log_event(run_id, "rewrite.noop",
                      {"requirement": classification.requirement.name,
                       "chunk_id": source_id})
        return None

    flags = check_grounding(
        suggested_text=suggested,
        original_text=chunk.text,
        requirement_name=classification.requirement.name,
    )

    suggestion = RewriteSuggestion(
        requirement=classification.requirement,
        source_chunk_id=chunk.chunk_id,
        original_text=chunk.text,
        suggested_text=suggested,
        rationale=draft.rationale.strip(),
        grounding_flags=flags,
    )

    if run_id:
        log_event(
            run_id,
            "rewrite.done",
            {
                "requirement": classification.requirement.name,
                "chunk_id": chunk.chunk_id,
                "source_line_no": chunk.source_line_no,
                "original": chunk.text,
                "suggested": suggested,
                "rationale": suggestion.rationale,
                "grounding_flags": flags,
            },
        )
    if flags:
        logger.warning("rewrite for %r flagged: %s",
                       classification.requirement.name, flags)

    return suggestion


def suggest_rewrites(
    classifications: Sequence[Classification],
    collection: "Collection",
    run_id: str | None = None,
    tier: str = GENERATION,
) -> list[RewriteSuggestion]:
    """Generate suggestions for every Weak Match in a classification set.

    Non-weak labels are skipped silently here -- filtering a mixed report is
    the expected use, and only a *direct* request to rewrite a Gap is a bug
    worth raising on.
    """
    weak = [c for c in classifications if c.label is MatchLabel.WEAK
            and c.evidence_chunk_ids]

    suggestions: list[RewriteSuggestion] = []
    for classification in weak:
        try:
            suggestion = suggest_rewrite(classification, collection,
                                         run_id=run_id, tier=tier)
        except RewriteNotApplicable:
            continue
        if suggestion is not None:
            suggestions.append(suggestion)

    if run_id:
        log_event(run_id, "rewrite.summary", {
            "weak_matches": len(weak),
            "suggested": len(suggestions),
            "flagged": sum(1 for s in suggestions if s.is_flagged),
        })
    return suggestions
