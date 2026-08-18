#!/usr/bin/env python
"""Compare several JDs against one resume (T073-T074, FR17-FR20)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.comparator import MAX_JDS, compare_jds  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jds", nargs="+", help=f"2 to {MAX_JDS} JD files")
    ap.add_argument("resume")
    ap.add_argument("--rewrites", action="store_true",
                    help="also generate rewrites per JD (slow, usually wasted)")
    args = ap.parse_args()

    started = time.time()
    result = compare_jds(args.jds, args.resume, skip_rewrites=not args.rewrites)
    elapsed = time.time() - started

    by_id = {r.run_id: r for r in result.reports}
    labels = {r.run_id: Path(str(s)).stem
              for r, s in zip(result.reports, args.jds)}

    print(f"\nrun {result.run_id}  ({elapsed:.0f}s)\n")
    print(f"{'rank':<5} {'jd':<48} {'score':>7} {'M':>3} {'W':>3} {'G':>3}")
    print("-" * 74)
    ranked_labels = set()
    for r in result.ranking:
        ranked_labels.add(r.label)
        rep = next((x for x in result.reports if labels[x.run_id] == r.label), None)
        tie = f"  (tied with {', '.join(r.tied_with)})" if r.tied_with else ""
        score = f"{rep.score:.1f}%" if rep and rep.classifications else "n/a"
        print(f"{r.rank:<5} {r.label:<48} {score:>7} "
              f"{len(rep.matched):>3} {len(rep.weak):>3} {len(rep.gaps):>3}")
        print(f"      {r.reason}{tie}")
    for rep in result.reports:
        if labels[rep.run_id] not in ranked_labels:
            print(f"{'—':<5} {labels[rep.run_id]:<48} {'unranked':>7}")

    if result.overall_note:
        print(f"\n{result.overall_note}")
    for w in result.warnings:
        print(f"\n! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
