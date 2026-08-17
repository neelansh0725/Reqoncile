#!/usr/bin/env python
"""T068 — run every sample JD end to end and record defects.

    ./.venv/bin/python scripts/validate_all.py

Deliberately a *sweep*, not a fix pass. Nothing is repaired while it runs; the
point is a complete defect list, and stopping to fix the first finding would
bias the rest of the run.

Paced for the free tier: JDs run strictly one at a time, and every hosted call
goes through the client's 15/min limiter. A 429 is recorded as `rate_limited`,
never as a defect -- the quota saying "not yet" is not a bug in this system,
and conflating the two would make the list unreadable.
"""

from __future__ import annotations

import glob
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.grounding import check_grounding  # noqa: E402
from logging_utils import read_run  # noqa: E402
from pipeline import run_pipeline  # noqa: E402
from reporting.generate_report import render_markdown  # noqa: E402
from schemas import MatchLabel  # noqa: E402

RESUME = Path("test_data/resumes/Best_withoutphoto.pdf")
OUT = Path("docs/defects.md")


def audit(jd_name: str, report, markdown: str) -> list[dict]:
    """Invariant checks against one finished report.

    Each of these is a property the project claims elsewhere; a violation here
    is a defect regardless of whether anything crashed.
    """
    found: list[dict] = []

    def defect(kind: str, detail: str, severity: str = "high") -> None:
        found.append({"jd": jd_name, "kind": kind, "detail": detail,
                      "severity": severity})

    gap_names = {c.requirement.name for c in report.gaps}
    rewritten = {r.requirement.name for r in report.rewrites}
    if gap_names & rewritten:
        defect("FR12 violation",
               f"gap requirement(s) received a rewrite: {sorted(gap_names & rewritten)}")

    for r in report.rewrites:
        if not r.source_chunk_id or not r.original_text.strip():
            defect("FR11 violation",
                   f"rewrite for {r.requirement.name!r} has no traceable source")
        # Re-run the grounding check independently of the pipeline: if the
        # stored flags disagree, one of the two paths is wrong.
        recomputed = check_grounding(r.suggested_text, r.original_text,
                                     r.requirement.name)
        if bool(recomputed) != bool(r.grounding_flags):
            defect("grounding inconsistency",
                   f"{r.requirement.name!r}: stored flags {r.grounding_flags} "
                   f"vs recomputed {recomputed}", "medium")

    for c in report.classifications:
        if c.label in (MatchLabel.MATCHED, MatchLabel.WEAK) and not c.evidence_chunk_ids:
            defect("FR8 violation",
                   f"{c.requirement.name!r} is {c.label.value} but cites no evidence")
        if c.label is MatchLabel.GAP and c.evidence_chunk_ids:
            defect("schema violation",
                   f"{c.requirement.name!r} is a gap but cites evidence")
        if not c.justification.strip():
            defect("FR8 violation", f"{c.requirement.name!r} has an empty justification")

    for r in report.eligibility:
        if r.category.value != "eligibility":
            defect("T015a violation",
                   f"non-eligibility requirement {r.name!r} in the checklist")

    if report.score_is_meaningful and not (0 <= report.score <= 100):
        defect("scoring", f"score out of range: {report.score}")
    if not report.classifications and not report.errored:
        defect("empty analysis", "no requirements were classified at all")

    for section in ("# Resume alignment report", "## Matched", "## Gaps"):
        if section not in markdown:
            defect("rendering", f"markdown missing {section!r}", "low")

    return found


def main() -> int:
    jds = sorted(glob.glob("test_data/sample_jds/*.txt"))
    print(f"T068 sweep: {len(jds)} JDs, serialised, paced to the free tier.\n")

    results, defects = [], []
    started = time.time()

    for index, path in enumerate(jds, 1):
        name = Path(path).stem
        print(f"[{index}/{len(jds)}] {name}")
        row = {"jd": name}
        try:
            report, timings = run_pipeline(Path(path), RESUME)
            markdown = render_markdown(report)

            trace_events = read_run(report.run_id)
            stages = Counter(e["stage"] for e in trace_events)
            rate_limited = stages.get("classify.rate_limited", 0)
            real_errors = stages.get("classify.error", 0) + stages.get(
                "classify.retrieval_error", 0)

            row |= {
                "run_id": report.run_id, "ok": True, "seconds": timings.total,
                "score": report.score, "matched": len(report.matched),
                "weak": len(report.weak), "gaps": len(report.gaps),
                "errored": len(report.errored), "eligibility": len(report.eligibility),
                "rewrites": len(report.rewrites),
                "flagged_rewrites": len(report.flagged_rewrites),
                "rate_limited": rate_limited, "real_errors": real_errors,
                "warnings": report.warnings,
            }
            found = audit(name, report, markdown)
            defects.extend(found)

            print(f"    {timings.total:>6.1f}s  score {report.score:>5.1f}%  "
                  f"M{len(report.matched)} W{len(report.weak)} G{len(report.gaps)} "
                  f"E{len(report.errored)}  rewrites {len(report.rewrites)}"
                  f"{f' ({len(report.flagged_rewrites)} flagged)' if report.flagged_rewrites else ''}")
            if rate_limited:
                print(f"    rate-limited: {rate_limited} (quota, not a defect)")
            if real_errors:
                print(f"    REAL ERRORS: {real_errors}")
            for d in found:
                print(f"    DEFECT [{d['severity']}] {d['kind']}: {d['detail'][:88]}")

        except Exception as exc:  # noqa: BLE001 - the sweep must finish
            row |= {"ok": False, "error": str(exc)}
            defects.append({"jd": name, "kind": "pipeline crash",
                            "detail": f"{type(exc).__name__}: {exc}", "severity": "high"})
            print(f"    CRASHED: {type(exc).__name__}: {exc}")
            traceback.print_exc()
        results.append(row)

    elapsed = time.time() - started
    write_report(results, defects, elapsed)
    print(f"\nfinished in {elapsed / 60:.1f} min · {len(defects)} defect(s) · wrote {OUT}")
    return 0


def write_report(results: list[dict], defects: list[dict], elapsed: float) -> None:
    ok = [r for r in results if r.get("ok")]
    lines = [
        "# T068 — end-to-end defect sweep", "",
        f"All {len(results)} sample JDs against `{RESUME.name}`, run one at a "
        f"time. Wall clock **{elapsed / 60:.1f} min**.", "",
        "Nothing was fixed during the run — this is the defect list as found.", "",
        "## Runs", "",
        "| JD | s | score | M | W | G | err | elig | rewrites | 429s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if not r.get("ok"):
            lines.append(f"| {r['jd']} | — | **CRASHED** | | | | | | | |")
            continue
        lines.append(
            f"| {r['jd']} | {r['seconds']:.0f} | {r['score']:.0f}% | {r['matched']} "
            f"| {r['weak']} | {r['gaps']} | {r['errored']} | {r['eligibility']} "
            f"| {r['rewrites']} | {r['rate_limited']} |"
        )

    if ok:
        lines += ["", f"Median run {sorted(r['seconds'] for r in ok)[len(ok)//2]:.0f}s · "
                  f"total {sum(r['rate_limited'] for r in ok)} rate-limited call(s) · "
                  f"{sum(r['real_errors'] for r in ok)} real error(s)."]

    lines += ["", "## Defects", ""]
    if not defects:
        lines.append("None. Every invariant held on every JD.")
    else:
        by_kind: dict[str, list[dict]] = {}
        for d in defects:
            by_kind.setdefault(d["kind"], []).append(d)
        for kind, items in sorted(by_kind.items()):
            lines += [f"### {kind} ({len(items)})", ""]
            for d in items:
                lines.append(f"- **{d['jd']}** [{d['severity']}] — {d['detail']}")
            lines.append("")

    lines += ["## What is deliberately not counted as a defect", "",
              "- **Rate-limited calls (429).** The free tier refusing a request "
              "is quota, not a bug. They are logged to `classify.rate_limited` "
              "and prefixed `RATE_LIMITED:` so they can never be mistaken for "
              "a real failure.",
              "- **Declined rewrites.** `llama3:8b` declines ~60% of the time "
              "(`docs/fabrication_test.md`); refusing to embellish is the "
              "intended behaviour.",
              "- **Requirements classified as gaps.** A gap is a finding, not "
              "an error.", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
