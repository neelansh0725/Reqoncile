"""Resume version diffing (T084-T085, FR24-FR27).

**No LLM.** Comparing two finished classifications is set arithmetic on a
three-point scale. Handing that to a model would introduce a way of being
wrong about something already known exactly, which is the opposite of what
this project is for.
"""

from __future__ import annotations

import logging

from pathlib import Path

from logging_utils import log_event, new_run_id
from parsing.jd_parser import parse_jd
from pipeline import run_pipeline
from schemas import (
    AlignmentReport,
    ChangeDirection,
    MatchLabel,
    RequirementChange,
    VersionDiff,
)

logger = logging.getLogger(__name__)

# The only ordering the diff asserts. `errored` is deliberately absent: it is
# not a weaker verdict than `gap`, it is the absence of one.
_RANK = {MatchLabel.GAP: 0, MatchLabel.WEAK: 1, MatchLabel.MATCHED: 2}


def _direction(before: MatchLabel, after: MatchLabel) -> ChangeDirection:
    if before not in _RANK or after not in _RANK:
        return ChangeDirection.INDETERMINATE
    if _RANK[after] > _RANK[before]:
        return ChangeDirection.IMPROVED
    if _RANK[after] < _RANK[before]:
        return ChangeDirection.REGRESSED
    return ChangeDirection.UNCHANGED


def summarise_diff(diff: VersionDiff) -> str:
    """The single net-improvement line FR27 asks for."""
    up, down = len(diff.improved), len(diff.regressed)
    same, unknown = len(diff.unchanged), len(diff.indeterminate)

    if not diff.changes:
        return "No requirements in common between the two versions to compare."

    if up and not down:
        verdict = f"Net improvement: {up} requirement{'s' if up != 1 else ''} stronger"
    elif down and not up:
        verdict = f"Net regression: {down} requirement{'s' if down != 1 else ''} weaker"
    elif not up and not down:
        verdict = f"No change: all {same} requirement{'s' if same != 1 else ''} landed the same way"
    elif up > down:
        verdict = f"Net improvement: {up} stronger against {down} weaker"
    elif down > up:
        verdict = f"Net regression: {down} weaker against {up} stronger"
    else:
        # Equal movement in both directions is not "no change" -- the resume
        # traded one requirement for another, which is worth seeing.
        verdict = f"Mixed: {up} stronger and {down} weaker, no net gain"

    parts = [verdict]
    if same and (up or down):
        parts.append(f"{same} unchanged")
    if unknown:
        parts.append(f"{unknown} not comparable")

    line = ", ".join(parts) + "."
    if diff.before_score is not None and diff.after_score is not None:
        delta = diff.after_score - diff.before_score
        sign = "+" if delta >= 0 else ""
        line += (f" Score {diff.before_score:.0f}% → {diff.after_score:.0f}% "
                 f"({sign}{delta:.0f} points).")
    return line


def diff_reports(
    before: AlignmentReport,
    after: AlignmentReport,
    run_id: str | None = None,
) -> VersionDiff:
    """Diff two reports for the same JD across two resume versions (FR26).

    Requirements are matched by name. That is only sound when both reports came
    from the *same* JD parse -- extraction rewords requirements between parses
    (D3/D4), so names from independent parses do not reliably denote the same
    requirement. `diff_resume_versions` guarantees the shared parse; when a
    caller assembles reports itself, any name present on only one side is
    reported as a warning rather than silently dropped.
    """
    run_id = run_id or new_run_id()

    # `errored` is kept out of `report.classifications`, but a requirement
    # that classified in one version and failed in the other has NOT vanished
    # from the JD -- it is uncomparable, which is a different fact from
    # absent. Including it here is what makes INDETERMINATE reachable and
    # keeps the "did not share a JD parse" warning honest.
    def by_name(report: AlignmentReport) -> dict[str, "Classification"]:
        return {c.requirement.name: c
                for c in [*report.classifications, *report.errored]}

    before_by_name, after_by_name = by_name(before), by_name(after)
    shared = [n for n in before_by_name if n in after_by_name]

    changes = [
        RequirementChange(
            requirement=name,
            before=before_by_name[name].label,
            after=after_by_name[name].label,
            direction=_direction(before_by_name[name].label,
                                 after_by_name[name].label),
        )
        for name in shared
    ]
    # Movement first, then alphabetically -- the point of the view is what
    # changed, and an unchanged list is what you scroll past.
    order = {ChangeDirection.IMPROVED: 0, ChangeDirection.REGRESSED: 1,
             ChangeDirection.INDETERMINATE: 2, ChangeDirection.UNCHANGED: 3}
    changes.sort(key=lambda c: (order[c.direction], c.requirement))

    warnings: list[str] = []
    only_before = sorted(set(before_by_name) - set(after_by_name))
    only_after = sorted(set(after_by_name) - set(before_by_name))
    if only_before or only_after:
        warnings.append(
            f"{len(only_before) + len(only_after)} requirement(s) appear in only "
            "one version and could not be compared. This means the two reports "
            "did not share a JD parse — see D3/D4. "
            f"Only in first: {only_before or 'none'}. "
            f"Only in second: {only_after or 'none'}."
        )

    # A score delta is only meaningful when both versions scored the *same*
    # set of requirements. An errored or uncompared requirement changes the
    # denominator, and "net improvement, score down 8 points" is a
    # self-contradicting line that would be read as a bug in the scoring.
    comparable = not warnings and not any(
        c.direction is ChangeDirection.INDETERMINATE for c in changes
    )
    if not comparable and (before.score_is_meaningful or after.score_is_meaningful):
        warnings.append(
            "Scores are not compared: the two versions did not score the same "
            "set of requirements, so their denominators differ and a delta "
            "between them would not mean what it appears to."
        )

    diff = VersionDiff(
        run_id=run_id,
        before_run_id=before.run_id,
        after_run_id=after.run_id,
        before_score=before.score if comparable and before.score_is_meaningful else None,
        after_score=after.score if comparable and after.score_is_meaningful else None,
        changes=changes,
        warnings=warnings,
    )
    diff.summary = summarise_diff(diff)

    log_event(run_id, "diff.done", {
        "before": before.run_id, "after": after.run_id,
        "improved": len(diff.improved), "regressed": len(diff.regressed),
        "unchanged": len(diff.unchanged), "summary": diff.summary,
    })
    return diff


def diff_resume_versions(
    jd_source: str | Path,
    resume_before: str | Path,
    resume_after: str | Path,
    run_id: str | None = None,
    skip_rewrites: bool = True,
) -> tuple[VersionDiff, AlignmentReport, AlignmentReport]:
    """Run one JD against two resume versions and diff them (FR24-FR27).

    **The JD is parsed once and the same requirement set is used for both
    versions.** This is the whole reason the diff is trustworthy: extraction is
    not reproducible (D3), and rewording alone can change a verdict on
    identical evidence (D4), so two independent parses would produce a diff
    contaminated by extraction noise that looks exactly like resume progress.

    FR25 asks that classification be re-run independently on both versions --
    it is. Only the parse is shared, and parsing is FR1-FR3, not FR6-FR9.

    Sharing the parse also pins the denominator, which makes the score delta in
    the summary a real comparison rather than two numbers computed over
    different requirement sets.
    """
    run_id = run_id or new_run_id()

    parsed = parse_jd(jd_source, run_id=run_id)
    log_event(run_id, "diff.start", {
        "requirements": len(parsed.requirements),
        "before": str(resume_before)[:200],
        "after": str(resume_after)[:200],
    })

    before, _ = run_pipeline(jd_source, resume_before, parsed=parsed,
                             skip_rewrites=skip_rewrites, skip_summary=True)
    after, _ = run_pipeline(jd_source, resume_after, parsed=parsed,
                            skip_rewrites=skip_rewrites, skip_summary=True)

    diff = diff_reports(before, after, run_id=run_id)
    return diff, before, after


def render_diff_markdown(diff: VersionDiff) -> str:
    """Render a version diff (FR26-FR27)."""
    out = ["# Resume version diff", "", f"**{diff.summary}**", ""]

    if diff.warnings:
        out.append("> **Note**")
        out += [f"> - {w}" for w in diff.warnings]
        out.append("")

    def block(title: str, items: list[RequirementChange], blurb: str) -> None:
        if not items:
            return
        # `out.extend`, never `out +=`. Augmented assignment binds `out` as a
        # local for the whole of `block()`, so the *earlier* extend on the line
        # above raises UnboundLocalError before this line ever runs. Same trap
        # already hit and commented in reporting/generate_report.py -- and hit
        # again here anyway, which is why there is now a test.
        out.extend([f"## {title} ({len(items)})", "", blurb, ""])
        out.extend(f"- **{c.requirement}** — {c.before.value} → {c.after.value}"
                   for c in items)
        out.append("")

    block("Stronger", diff.improved,
          "These moved up between versions.")
    block("Weaker", diff.regressed,
          "These moved down. Worth checking whether an edit removed something "
          "the earlier version was evidencing.")
    block("Not comparable", diff.indeterminate,
          "One version failed to classify these, so no movement can be "
          "claimed either way.")
    block("Unchanged", diff.unchanged,
          "Same verdict in both versions.")
    return "\n".join(out)
