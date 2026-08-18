#!/usr/bin/env python
"""Interview prep for the gaps in a finished run (T081, FR21-FR23).

Reads a stored run's trace rather than re-running the pipeline: the gaps are
already recorded, and re-classifying them would spend hosted quota to learn
nothing new. Prep itself runs on the local generation tier, so this is free.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.interview_prep import (  # noqa: E402
    load_gaps_from_run as load_gaps,
    prepare_for_gaps,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    gaps, chunk_texts = load_gaps(args.run_id)
    print(f"{len(gaps)} gap(s) in {args.run_id}\n")

    prep = prepare_for_gaps(gaps, chunk_texts=chunk_texts, limit=args.limit)

    for record in prep.prepared:
        print(f"\n## {record.requirement}")
        if record.error:
            print(f"   ! no questions generated: {record.error[:200]}")
            continue
        for i, q in enumerate(record.questions, 1):
            print(f"   {i}. {q.question}")
            print(f"      → {q.answer_should_cover}")

    ok = sum(1 for p in prep.prepared if not p.error)
    print(f"\n{ok}/{len(prep.prepared)} gaps prepared · "
          f"{prep.question_count} questions")
    for w in prep.warnings:
        print(f"! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
