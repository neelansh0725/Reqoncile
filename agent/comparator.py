"""Multi-JD comparison (T073-T074, FR17-FR20).

A loop over the unchanged single-JD pipeline plus one ranking call. No new
classification method (FR20) -- if this file ever needs its own reasoning,
that is the signal to cut scope, not to add complexity (R5).

**The ranking deliberately admits ties.** v1.1 measured that this system
separates strong-fit JDs from weak-fit ones but does not resolve fine-grained
rank among JDs of similar strength: across a full re-run, four of eight JDs
held their exact position while the top four reordered inside a 10-point band
(Kendall tau +0.63). Emitting a confident 1..N ordering would assert precision
the measurement says is not there, so `RankedJD.tied_with` exists and the
prompt is told to use it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from llm_client import REASONING, LLMCallError, complete_structured
from logging_utils import log_event, new_run_id
from pipeline import run_pipeline
from schemas import ComparisonResult, JDRanking, MatchLabel, RankedJD

logger = logging.getLogger(__name__)

MAX_JDS = 3

RANKING_SYSTEM = """\
You rank job descriptions by how well one candidate's resume already fits
them. You are given, per JD, the counts and the specific requirements sorted
into matched / under-communicated / gap.

Rank 1 is the best fit.

## Ties are expected — use them

The scores you are shown are not precise enough to separate JDs of similar
strength. Where two or more JDs are genuinely close, give them the **same
rank** and list each other in `tied_with`. Do not invent an ordering between
them to produce a tidy list.

Separate JDs confidently when the gap is substantive: many more required
matches, or gaps on the requirements that clearly matter most for the role.

## What to weigh

- **Gaps on required items** count far more than gaps on preferred ones.
- **Under-communicated matches are strengths, not weaknesses.** The experience
  is present; only the wording is missing, and that is fixable. A JD whose
  shortfalls are mostly under-communication fits better than one with the same
  score made of real gaps.
- Ignore the eligibility checklist entirely — it was never assessed.

## Reasons

One line per JD, citing the actual requirements, not the number. "Strongest
on the data-engineering requirements; the only gaps are preferred items" is
useful. "Scored highest" is not.
"""

RANKING_USER = """\
Rank these {n} job descriptions for this candidate.

{blocks}"""


def _summarise(label: str, report) -> str:
    def names(items, limit=10):
        listed = [c.requirement.name for c in items[:limit]]
        extra = f" (+{len(items) - limit} more)" if len(items) > limit else ""
        return (", ".join(listed) + extra) if listed else "none"

    required_gaps = [c for c in report.gaps
                     if c.requirement.necessity.value == "required"]
    return (
        f"<jd label=\"{label}\">\n"
        f"score: {report.score:.0f}%\n"
        f"matched ({len(report.matched)}): {names(report.matched)}\n"
        f"under-communicated ({len(report.weak)}): {names(report.weak)}\n"
        f"gaps ({len(report.gaps)}, of which {len(required_gaps)} required): "
        f"{names(report.gaps)}\n"
        f"</jd>"
    )


def rank_reports(
    labelled: Sequence[tuple[str, object]],
    run_id: str | None = None,
    tier: str = REASONING,
) -> tuple[list[RankedJD], str, list[str]]:
    """Rank finished reports (T074). Returns (ranking, note, warnings)."""
    scoreable = [(label, r) for label, r in labelled if r.classifications]
    if len(scoreable) < 2:
        return [], "", [
            "Ranking needs at least two JDs with classifiable requirements."
        ]

    blocks = "\n\n".join(_summarise(label, r) for label, r in scoreable)
    user = RANKING_USER.format(n=len(scoreable), blocks=blocks)

    try:
        result = complete_structured(JDRanking, user=user,
                                     system=RANKING_SYSTEM, tier=tier)
    except LLMCallError as exc:
        logger.warning("ranking failed: %s", exc)
        if run_id:
            log_event(run_id, "compare.rank_error", {"error": str(exc)})
        return [], "", [f"Ranking could not be generated: {exc}"]

    known = {label for label, _ in scoreable}
    warnings: list[str] = []

    # Drop rankings for JDs that were never submitted -- the same guard the
    # classifier applies to invented chunk ids (T031).
    ranking = [r for r in result.ranked if r.label in known]
    if len(ranking) != len(result.ranked):
        invented = [r.label for r in result.ranked if r.label not in known]
        warnings.append(f"Ranking referenced unknown JD(s): {invented}")
    missing = known - {r.label for r in ranking}
    if missing:
        warnings.append(f"Ranking omitted {sorted(missing)}; shown unranked.")

    ranking.sort(key=lambda r: r.rank)
    if run_id:
        log_event(run_id, "compare.ranked", {
            "ranking": [r.model_dump() for r in ranking],
            "note": result.overall_note,
        })
    return ranking, result.overall_note, warnings


def compare_jds(
    jd_sources: Sequence[str | Path],
    resume_source: str | Path,
    labels: Sequence[str] | None = None,
    run_id: str | None = None,
    skip_rewrites: bool = True,
) -> ComparisonResult:
    """Run several JDs against one resume and rank them (FR17-FR20).

    Rewrites are skipped by default. Comparison answers "which of these should
    I apply to"; rewriting for all of them is work thrown away on the ones not
    chosen. Run the single-JD pipeline on the winner to get rewrites.

    Each JD goes through `run_pipeline` unchanged. A JD that fails to produce
    any classifiable requirement is kept in `reports` and excluded from the
    ranking -- the same treatment the v1.1 measurement gave
    `zs_decision_analytics_associate`, rather than dropping it silently.
    """
    if not 2 <= len(jd_sources) <= MAX_JDS:
        raise ValueError(f"compare 2 to {MAX_JDS} JDs, got {len(jd_sources)}")

    run_id = run_id or new_run_id()
    labels = list(labels) if labels else [Path(str(s)).stem for s in jd_sources]
    if len(set(labels)) != len(labels):
        raise ValueError(f"JD labels must be unique, got {labels}")

    log_event(run_id, "compare.start", {"jds": labels})

    reports, warnings = [], []
    for label, source in zip(labels, jd_sources):
        # Each JD gets its own run id so its trace stays separable (FR16),
        # while compare.* events tie them together under this run.
        report, _ = run_pipeline(source, resume_source, skip_rewrites=skip_rewrites)
        reports.append(report)
        log_event(run_id, "compare.jd_done",
                  {"label": label, "child_run_id": report.run_id,
                   "score": report.score,
                   "classifiable": len(report.classifications)})
        if not report.classifications:
            warnings.append(
                f"{label}: no classifiable requirements were extracted, so it "
                "has no score and is excluded from the ranking."
            )

    ranking, note, rank_warnings = rank_reports(
        list(zip(labels, reports)), run_id=run_id
    )
    warnings.extend(rank_warnings)

    log_event(run_id, "compare.done",
              {"ranked": len(ranking), "warnings": warnings})

    return ComparisonResult(run_id=run_id, reports=reports, ranking=ranking,
                            overall_note=note, warnings=warnings)
