"""Report assembly and rendering (T047-T049, FR13-FR14).

Assembly is pure and deterministic — the same classifications always produce
the same report. Only `summarise` calls a model, and it is additive: a failed
summary costs a paragraph, never the report (NFR3).
"""

from __future__ import annotations

import logging
from typing import Sequence

from llm_client import GENERATION, LLMCallError, complete
from reporting.score import explain_score, score_classifications
from schemas import (
    ComparisonResult,
    AlignmentReport,
    Classification,
    MatchLabel,
    Requirement,
    RewriteSuggestion,
)

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM = """\
You write the closing paragraph of a resume-to-job-description alignment
report, for the candidate to read about their own application.

You are given counts and the specific findings. Write 3-5 sentences of plain
prose. No headings, no bullets, no preamble.

Cover, in this order: where the resume is genuinely strong for this role;
which gaps are real; and, if any requirements were under-communicated rather
than missing, that rewriting could close them.

Rules:
- State gaps plainly. Do not soften them, and do not suggest ways to work
  around them or imply the candidate could claim them. A gap means the resume
  does not evidence that requirement, and saying so is the useful thing.
- Never suggest adding anything to the resume that is not already there.
- Do not invent detail beyond the findings given.
- Address the candidate directly ("your resume"), plainly, without flattery.
"""

SUMMARY_USER = """\
Write the summary for this alignment report.

Overall match: {score}
Strong matches ({n_matched}): {matched}
Under-communicated ({n_weak}): {weak}
Genuine gaps ({n_gaps}): {gaps}
Rewrite suggestions available: {n_rewrites}
{extra}"""


def assemble_report(
    run_id: str,
    classifications: Sequence[Classification],
    rewrites: Sequence[RewriteSuggestion] = (),
    eligibility: Sequence[Requirement] = (),
    warnings: Sequence[str] = (),
) -> AlignmentReport:
    """Build the structured report (T047). No model call."""
    assessed = [c for c in classifications if c.label is not MatchLabel.ERRORED]
    errored = [c for c in classifications if c.label is MatchLabel.ERRORED]

    breakdown = score_classifications(classifications)
    all_warnings = list(warnings)

    if not breakdown.is_meaningful and classifications:
        all_warnings.append(
            "No requirement could be scored; the 0% is not an assessment."
        )
    if errored:
        all_warnings.append(
            f"{len(errored)} requirement(s) could not be assessed and are "
            "excluded from the score."
        )
    flagged = [r for r in rewrites if r.is_flagged]
    if flagged:
        all_warnings.append(
            f"{len(flagged)} rewrite suggestion(s) introduce wording the "
            "source line may not support — review before using."
        )

    return AlignmentReport(
        run_id=run_id,
        score=breakdown.score,
        score_explanation=explain_score(breakdown),
        score_is_meaningful=breakdown.is_meaningful,
        classifications=list(assessed),
        rewrites=list(rewrites),
        eligibility=list(eligibility),
        errored=errored,
        warnings=all_warnings,
    )


def summarise(report: AlignmentReport, tier: str = GENERATION) -> str:
    """Generate the plain-language summary (T048, FR13).

    Additive by design: on failure the report keeps everything else and simply
    has no summary paragraph.
    """
    def names(items: Sequence[Classification], limit: int = 8) -> str:
        listed = [c.requirement.name for c in items[:limit]]
        if not listed:
            return "none"
        suffix = f", and {len(items) - limit} more" if len(items) > limit else ""
        return ", ".join(listed) + suffix

    extra = ""
    if report.eligibility:
        extra = (
            "Eligibility items listed separately for the candidate to check "
            f"(not assessed): {', '.join(r.name for r in report.eligibility)}\n"
        )

    user = SUMMARY_USER.format(
        score=f"{report.score:.0f}%" if report.score_is_meaningful else "not scored",
        n_matched=len(report.matched), matched=names(report.matched),
        n_weak=len(report.weak), weak=names(report.weak),
        n_gaps=len(report.gaps), gaps=names(report.gaps),
        n_rewrites=len(report.rewrites),
        extra=extra,
    )

    try:
        return complete(user=user, system=SUMMARY_SYSTEM, tier=tier).strip()
    except LLMCallError as exc:
        logger.warning("summary generation failed: %s", exc)
        report.warnings.append(f"Summary could not be generated: {exc}")
        return ""


def render_markdown(report: AlignmentReport) -> str:
    """Render the report as human-readable Markdown (T049, FR14)."""
    out: list[str] = ["# Resume alignment report", ""]

    if report.score_is_meaningful:
        out += [f"## Match score: {report.score:.0f}%", "", report.score_explanation, ""]
    else:
        out += ["## Match score: not available", "", report.score_explanation, ""]

    if report.summary:
        out += [report.summary, ""]

    if report.warnings:
        out.append("> **Note**")
        out += [f"> - {w}" for w in report.warnings]
        out.append("")

    def section(title: str, items: Sequence[Classification], blurb: str) -> None:
        # `out.extend`, not `out +=` -- the latter rebinds `out` as a local
        # inside the closure and shadows the list being built.
        out.extend([f"## {title} ({len(items)})", ""])
        if not items:
            out.extend(["_None._", ""])
            return
        out.extend([blurb, ""])
        for c in items:
            out.append(
                f"- **{c.requirement.name}** "
                f"_({c.requirement.necessity.value}, {c.requirement.category.value})_  "
            )
            out.append(f"  {c.justification}")
        out.append("")

    section("Matched", report.matched,
            "The resume clearly evidences these.")
    section("Under-communicated", report.weak,
            "The experience is there, but a reader scanning for these could "
            "miss it. Rewrites below.")
    section("Gaps", report.gaps,
            "The resume does not evidence these. Stated plainly — no rewrite "
            "is offered, because there is nothing to surface.")

    if report.rewrites:
        out += [f"## Suggested rewrites ({len(report.rewrites)})", "",
                "Each suggestion uses only what the original line already "
                "says, and shows the line it came from.", ""]
        for r in report.rewrites:
            out += [f"### {r.requirement.name}", "",
                    f"**Current** (`{r.source_chunk_id}`):", "",
                    f"> {r.original_text}", "",
                    "**Suggested:**", "",
                    f"> {r.suggested_text}", "",
                    f"_{r.rationale}_", ""]
            if r.grounding_flags:
                out.append("**⚠ Review before using:**")
                out += [f"- {f}" for f in r.grounding_flags]
                out.append("")

    if report.eligibility:
        out += [f"## Eligibility checklist ({len(report.eligibility)})", "",
                "These were **not assessed**. A resume cannot reliably "
                "evidence work authorisation, location or graduation year, so "
                "the system reports them for you to confirm rather than "
                "guessing.", ""]
        for r in report.eligibility:
            out.append(f"- [ ] **{r.name}** — _{r.source_text}_")
        out.append("")

    if report.errored:
        out += [f"## Could not assess ({len(report.errored)})", "",
                "These failed during analysis. They are listed rather than "
                "counted as gaps — the system did not assess them, so it "
                "makes no claim either way.", ""]
        for c in report.errored:
            out.append(f"- **{c.requirement.name}** — {c.error}")
        out.append("")

    out += ["---", f"_Run `{report.run_id}`._"]
    return "\n".join(out)


def render_comparison_markdown(
    result: "ComparisonResult", labels: dict[str, str]
) -> str:
    """Render a multi-JD comparison (T075, FR19).

    `labels` maps each report's run_id to its comparison label. Ties are
    rendered as ties rather than flattened into an order -- see the module
    docstring in `agent/comparator.py` for why the system declines to assert
    fine-grained rank.
    """
    out: list[str] = ["# JD comparison", ""]
    by_label = {labels[r.run_id]: r for r in result.reports}

    if result.overall_note:
        out += [result.overall_note, ""]

    if result.ranking:
        out += ["| rank | job description | score | matched | under-comm. | gaps |",
                "|---:|---|---:|---:|---:|---:|"]
        for r in result.ranking:
            rep = by_label.get(r.label)
            score = (f"{rep.score:.0f}%"
                     if rep and rep.score_is_meaningful else "—")
            tie = " *(tied)*" if r.tied_with else ""
            out.append(
                f"| {r.rank}{tie} | {r.label} | {score} | "
                f"{len(rep.matched) if rep else 0} | "
                f"{len(rep.weak) if rep else 0} | "
                f"{len(rep.gaps) if rep else 0} |"
            )
        out.append("")
        for r in result.ranking:
            out.append(f"**{r.rank}. {r.label}** — {r.reason}")
            if r.tied_with:
                out.append(
                    f"  Too close to separate from {', '.join(r.tied_with)}; "
                    "the order between them is not resolvable."
                )
            out.append("")
    else:
        out += ["_No ranking was produced._", ""]

    unranked = sorted(set(by_label) - {r.label for r in result.ranking})
    if unranked:
        out += ["## Not ranked", "",
                "These produced no classifiable requirements, so they have no "
                "score and were excluded rather than guessed at.", ""]
        out += [f"- {label}" for label in unranked] + [""]

    if result.warnings:
        out.append("> **Note**")
        out += [f"> - {w}" for w in result.warnings]
        out.append("")

    out += ["---", "",
            "Scores are comparable within this run only: requirement counts "
            "vary between extractions, and each score has its own denominator. "
            "This system separates strong fits from weak ones; it does not "
            "resolve fine-grained rank between JDs of similar strength.", ""]
    return "\n".join(out)
