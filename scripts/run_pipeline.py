#!/usr/bin/env python
"""Run the full pipeline on one JD + resume (T051).

    ./.venv/bin/python scripts/run_pipeline.py \
        test_data/sample_jds/mathco_ai_analyst.txt \
        test_data/resumes/Best_withoutphoto.pdf

    ... --json report.json --markdown report.md --no-rewrites
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import run_pipeline  # noqa: E402
from reporting.generate_report import render_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Reqoncile end to end.")
    parser.add_argument("jd", type=Path)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--no-rewrites", action="store_true")
    parser.add_argument("--no-summary", action="store_true")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only the timing line and headline numbers.")
    args = parser.parse_args()

    report, timings = run_pipeline(
        args.jd, args.resume,
        skip_rewrites=args.no_rewrites, skip_summary=args.no_summary,
    )

    print(f"\nrun      : {report.run_id}")
    print(f"timings  : {timings}")
    budget = "within" if timings.total <= 30 else "OVER"
    print(f"NFR1     : {budget} the ~30s budget")
    print(f"score    : {report.score:.0f}%"
          if report.score_is_meaningful else "score    : not available")
    print(f"           {report.score_explanation}")
    print(f"breakdown: {len(report.matched)} matched, {len(report.weak)} weak, "
          f"{len(report.gaps)} gaps, {len(report.errored)} errored, "
          f"{len(report.eligibility)} eligibility")
    print(f"rewrites : {len(report.rewrites)} "
          f"({len(report.flagged_rewrites)} flagged)")
    for warning in report.warnings:
        print(f"warning  : {warning}")

    if not args.quiet:
        print()
        print(render_markdown(report))

    if args.json:
        args.json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    if args.markdown:
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
        print(f"wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
