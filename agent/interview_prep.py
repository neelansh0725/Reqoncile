"""Interview prep for gaps (T079-T080, FR21-FR23).

Gated to Gap classifications, mirroring `suggest_rewrite`'s gate to Weak. The
two are complements: a weak match gets rewritten because the experience is
there and under-sold; a gap gets *prepared for* because it is not there and no
rewrite would be honest (FR12).
"""

from __future__ import annotations

import logging
from typing import Sequence

from agent.prompts import INTERVIEW_PREP_SYSTEM, INTERVIEW_PREP_USER
from llm_client import GENERATION, LLMCallError, complete_structured
from logging_utils import log_event, new_run_id, read_run
from schemas import (
    Classification,
    GapPrep,
    GapPrepRecord,
    InterviewPrep,
    MatchLabel,
)

logger = logging.getLogger(__name__)

# How many retrieved chunks to offer as "nearest adjacent experience". A gap
# cites no evidence by definition (FR8), so these are the chunks retrieval
# surfaced and the classifier judged insufficient -- useful for pointing at
# the closest genuine thing, and explicitly labelled as not evidence.
ADJACENT_CHUNKS = 3


def load_gaps_from_run(
    run_id: str,
) -> tuple[list["Classification"], dict[str, str]]:
    """Rebuild a run's Gap classifications and chunk texts from its log.

    The log is already the durable record of what was decided (T033), so prep
    is generated against exactly that rather than against a re-run, which would
    spend hosted quota and could reach different verdicts (D4).
    """
    from schemas import Category, Necessity, Requirement

    events = read_run(run_id)
    if not events:
        raise FileNotFoundError(f"no trace for run {run_id!r}")

    gaps: list[Classification] = []
    chunk_texts: dict[str, str] = {}
    for event in events:
        if event.get("stage") != "classify.done":
            continue
        p = event.get("payload", {})
        for chunk in p.get("retrieved", []):
            chunk_texts[chunk["chunk_id"]] = chunk["text"]
        if p.get("final_label") != MatchLabel.GAP.value:
            continue
        gaps.append(Classification(
            requirement=Requirement(
                name=p["requirement"],
                category=Category(p["category"]),
                necessity=Necessity(p["necessity"]),
                # The trace keeps the retrieved set, not the originating JD
                # line. The name stands in for it -- accurate, and not invented.
                source_text=p["requirement"],
            ),
            label=MatchLabel.GAP,
            justification=p.get("justification", ""),
            retrieved_scores={c["chunk_id"]: c["similarity"]
                              for c in p.get("retrieved", [])},
        ))
    return gaps, chunk_texts


class PrepNotApplicable(ValueError):
    """Raised when prep is requested for a requirement that is not a Gap."""


def prepare_for_gap(
    classification: Classification,
    chunk_texts: dict[str, str] | None = None,
    run_id: str | None = None,
    tier: str = GENERATION,
) -> GapPrepRecord:
    """Generate interview questions for one Gap (FR21-FR22).

    Raises `PrepNotApplicable` for any label but `gap`. Preparing a candidate
    to explain away a *matched* requirement would be actively harmful, and
    doing it for a weak match contradicts FR10, which says to rewrite it.
    """
    if classification.label is not MatchLabel.GAP:
        raise PrepNotApplicable(
            f"interview prep applies to gaps only, got "
            f"{classification.label.value} for "
            f"{classification.requirement.name!r}"
        )

    req = classification.requirement
    adjacent = ""
    if chunk_texts:
        # Ranked by the similarity retrieval assigned, best first.
        ranked = sorted(
            classification.retrieved_scores.items(), key=lambda kv: -kv[1]
        )[:ADJACENT_CHUNKS]
        lines = [f"- {chunk_texts[cid]}" for cid, _ in ranked if cid in chunk_texts]
        if lines:
            adjacent = (
                "The closest things on their resume -- these were judged NOT to "
                "evidence the requirement, so do not present them as if they "
                "did, but they may be the nearest honest thing to point at:\n"
                + "\n".join(lines)
                + "\n\n"
            )

    user = INTERVIEW_PREP_USER.format(
        requirement=req.name,
        necessity=req.necessity.value,
        category=req.category.value,
        source_text=req.source_text,
        justification=classification.justification,
        adjacent=adjacent,
    )

    try:
        prep = complete_structured(
            GapPrep, user=user, system=INTERVIEW_PREP_SYSTEM, tier=tier
        )
    except LLMCallError as exc:
        # Includes FR23 validation failures: a model that drafted a
        # first-person sample answer fails the schema, and the honest outcome
        # is no questions for this gap rather than a fabricated line.
        logger.warning("interview prep failed for %r: %s", req.name, exc)
        if run_id:
            log_event(run_id, "prep.error",
                      {"requirement": req.name, "error": str(exc)})
        return GapPrepRecord(requirement=req.name, error=str(exc))

    if run_id:
        log_event(run_id, "prep.done", {
            "requirement": req.name,
            "questions": [q.model_dump() for q in prep.questions],
        })
    return GapPrepRecord(requirement=req.name, questions=list(prep.questions))


def prepare_for_gaps(
    classifications: Sequence[Classification],
    chunk_texts: dict[str, str] | None = None,
    run_id: str | None = None,
    tier: str = GENERATION,
    limit: int | None = None,
) -> InterviewPrep:
    """Prepare for every Gap in a report (T080, FR21).

    Non-gaps are filtered out here rather than raising -- callers pass a whole
    report's classifications, and the gate belongs on the single-item function
    where a mistake is a programming error rather than ordinary input.
    """
    run_id = run_id or new_run_id()
    gaps = [c for c in classifications if c.label is MatchLabel.GAP]
    warnings: list[str] = []

    if limit is not None and len(gaps) > limit:
        warnings.append(
            f"{len(gaps)} gaps found; prepared for the first {limit}."
        )
        gaps = gaps[:limit]

    log_event(run_id, "prep.start", {"gaps": len(gaps)})

    prepared = [
        prepare_for_gap(c, chunk_texts=chunk_texts, run_id=run_id, tier=tier)
        for c in gaps
    ]

    failed = [p.requirement for p in prepared if p.error]
    if failed:
        warnings.append(
            f"No questions generated for {len(failed)} gap(s): "
            f"{', '.join(failed)}."
        )

    log_event(run_id, "prep.summary", {
        "prepared": len(prepared) - len(failed), "failed": len(failed)
    })
    return InterviewPrep(run_id=run_id, prepared=prepared, warnings=warnings)
