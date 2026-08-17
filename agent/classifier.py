"""Matched / Weak / Gap classification (T028-T034, FR7-FR9).

The core reasoning step. One model call per requirement, because the three
things the PRD asks for all need per-requirement granularity: an individual
justification (FR8), failure isolation so one bad call cannot sink a report
(NFR3), and a per-requirement reasoning trace (FR16).

Eligibility requirements never arrive here — they are split out upstream
(T015a) because retrieval-and-reason cannot honestly assess a city name or a
visa status.
"""

from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Sequence

from agent.prompts import build_classification_messages
from config import settings
from llm_client import (
    REASONING,
    LLMCallError,
    LLMConfigurationError,
    complete_structured,
    is_rate_limited,
)
from logging_utils import log_event
from retrieval.vector_store import query_chunks
from schemas import (
    Classification,
    ClassificationVerdict,
    MatchLabel,
    Requirement,
    RetrievedChunk,
)

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)


def _errored(requirement: Requirement, message: str, retrieved) -> Classification:
    """Build the ERRORED record for a requirement we could not assess.

    Deliberately not a Gap. Reporting 'we failed to check this' is honest;
    silently downgrading it to 'you lack this skill' would fabricate a finding
    (G5), and would quietly drag the match score down.
    """
    return Classification(
        requirement=requirement,
        label=MatchLabel.ERRORED,
        justification="This requirement could not be assessed automatically.",
        evidence_chunk_ids=[],
        retrieved_scores={h.chunk.chunk_id: h.similarity for h in (retrieved or [])},
        error=message,
    )


def _validate_evidence(
    verdict: ClassificationVerdict,
    retrieved: Sequence[RetrievedChunk],
) -> tuple[list[str], list[str]]:
    """Drop cited ids that were not in the retrieved set (T031).

    A model citing a chunk it was never shown is either hallucinating an id or
    mangling one. Either way the citation cannot be trusted, and FR11
    traceability depends on every cited id resolving to a real resume line.
    """
    offered = {hit.chunk.chunk_id for hit in retrieved}
    kept, rejected = [], []
    for chunk_id in verdict.evidence_chunk_ids:
        (kept if chunk_id in offered else rejected).append(chunk_id)
    return kept, rejected


def classify_requirement(
    requirement: Requirement,
    collection: "Collection",
    run_id: str | None = None,
    top_k: int | None = None,
    tier: str = REASONING,
) -> Classification:
    """Classify one requirement against the indexed resume (FR7-FR9).

    Never raises on a model or retrieval failure -- returns an ERRORED record
    instead, so a fan-out over many requirements always yields one result per
    requirement (T032 / NFR3).
    """
    retrieved: list[RetrievedChunk] = []
    try:
        retrieved = query_chunks(collection, requirement.name, k=top_k)
    except Exception as exc:  # noqa: BLE001 - retrieval must not sink the run
        # Log the traceback, not just the message. A transient
        # "string index out of range" was seen once here during a concurrent
        # run and could not be reproduced single-threaded; without the stack
        # there is nothing to diagnose on a recurrence.
        logger.warning("retrieval failed for %r: %s", requirement.name, exc,
                       exc_info=True)
        if run_id:
            log_event(run_id, "classify.retrieval_error",
                      {"requirement": requirement.name, "error": str(exc),
                       "traceback": traceback.format_exc()})
        return _errored(requirement, f"retrieval failed: {exc}", retrieved)

    scores = {hit.chunk.chunk_id: hit.similarity for hit in retrieved}
    system, user = build_classification_messages(requirement, retrieved)

    try:
        verdict = complete_structured(
            ClassificationVerdict, user=user, system=system, tier=tier
        )
    except LLMConfigurationError:
        # A missing credential is not a per-item failure -- fail loudly rather
        # than emitting a report full of 'could not assess'.
        raise
    except LLMCallError as exc:
        # A quota rejection is not a defect in this system -- it means the
        # free tier said "not yet". Logging it under the same stage as a real
        # failure would make a defect sweep (T068) unreadable, so it gets its
        # own stage and an unmistakable prefix on the recorded error.
        quota = is_rate_limited(exc)
        stage = "classify.rate_limited" if quota else "classify.error"
        logger.warning("%s for %r: %s",
                       "RATE LIMITED" if quota else "classification failed",
                       requirement.name, exc)
        if run_id:
            log_event(run_id, stage,
                      {"requirement": requirement.name, "error": str(exc),
                       "rate_limited": quota})
        prefix = "RATE_LIMITED: " if quota else ""
        return _errored(requirement, f"{prefix}{exc}", retrieved)

    evidence, rejected = _validate_evidence(verdict, retrieved)

    label = verdict.label
    repaired: str | None = None
    # A matched/weak verdict whose every citation was bogus has no support
    # left. Rather than reject the whole classification, record what happened
    # and fall back to the honest answer: we cannot evidence this.
    if label in (MatchLabel.MATCHED, MatchLabel.WEAK) and not evidence:
        repaired = (
            f"verdict {label.value!r} cited no valid evidence "
            f"(rejected ids: {rejected or 'none'}); recorded as gap"
        )
        label = MatchLabel.GAP
    if label is MatchLabel.GAP:
        evidence = []

    classification = Classification(
        requirement=requirement,
        label=label,
        justification=verdict.justification.strip(),
        evidence_chunk_ids=evidence,
        retrieved_scores=scores,
    )

    if run_id:
        # The full trace for this requirement (T033 / FR16): what was
        # retrieved, what the model said, and what we recorded.
        log_event(
            run_id,
            "classify.done",
            {
                "requirement": requirement.name,
                "category": requirement.category.value,
                "necessity": requirement.necessity.value,
                "retrieved": [
                    {
                        "chunk_id": hit.chunk.chunk_id,
                        "section": hit.chunk.section.value,
                        "similarity": hit.similarity,
                        "source_line_no": hit.chunk.source_line_no,
                        "text": hit.chunk.text,
                    }
                    for hit in retrieved
                ],
                "model_label": verdict.label.value,
                "model_evidence": verdict.evidence_chunk_ids,
                "rejected_evidence": rejected,
                "repaired": repaired,
                "final_label": label.value,
                "justification": classification.justification,
            },
        )

    return classification


def classify_requirements(
    requirements: Sequence[Requirement],
    collection: "Collection",
    run_id: str | None = None,
    top_k: int | None = None,
    max_concurrency: int | None = None,
    tier: str = REASONING,
) -> list[Classification]:
    """Classify many requirements concurrently, preserving input order (T034).

    Concurrency is capped because the hosted reasoning tier is rate-limited
    per minute (`docs/providers.md`); raising it past the cap trades latency
    for 429s rather than saving time.
    """
    if not requirements:
        return []

    workers = max_concurrency or settings.llm_max_concurrency
    workers = max(1, min(workers, len(requirements)))

    if run_id:
        log_event(run_id, "classify.start",
                  {"requirements": len(requirements), "concurrency": workers})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # `map` preserves input order, which the report depends on.
        results = list(
            pool.map(
                lambda requirement: classify_requirement(
                    requirement, collection, run_id=run_id, top_k=top_k, tier=tier
                ),
                requirements,
            )
        )

    if run_id:
        counts: dict[str, int] = {}
        for item in results:
            counts[item.label.value] = counts.get(item.label.value, 0) + 1
        log_event(run_id, "classify.summary", {"counts": counts})

    return results
