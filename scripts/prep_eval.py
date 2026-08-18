#!/usr/bin/env python
"""T081 — measure interview prep against real gaps.

Records per gap: elapsed time, whether it validated, and whether the failure
was specifically the FR23 first-person guard. The point is the rate, not a
sample: FR23 is enforced in the schema, and how often the model tries to
violate it is what tells you whether that enforcement is load-bearing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.interview_prep import prepare_for_gap  # noqa: E402
from scripts.interview_prep import load_gaps  # noqa: E402

FR23_MARK = "first-person phrasing found"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--out", default="docs/_prep_eval.json")
    ap.add_argument("--adjacent", action="store_true",
                    help="include nearest-chunk context in the prompt")
    args = ap.parse_args()

    gaps, chunk_texts = load_gaps(args.run_id)
    rows = []
    for c in gaps:
        started = time.time()
        record = prepare_for_gap(
            c, chunk_texts=chunk_texts if args.adjacent else None
        )
        elapsed = time.time() - started
        fr23 = bool(record.error and FR23_MARK in record.error)
        rows.append({
            "requirement": record.requirement,
            "seconds": round(elapsed, 1),
            "ok": not record.error,
            "fr23_violation": fr23,
            "questions": [q.model_dump() for q in record.questions],
            "error": (record.error or "")[:300],
        })
        status = "ok" if not record.error else ("FR23" if fr23 else "other")
        print(f"  {elapsed:6.1f}s  {status:<5}  {record.requirement}", flush=True)

    ok = sum(r["ok"] for r in rows)
    fr23 = sum(r["fr23_violation"] for r in rows)
    times = [r["seconds"] for r in rows]
    print(f"\n{ok}/{len(rows)} validated · {fr23} FR23 violations caught · "
          f"median {sorted(times)[len(times)//2]:.1f}s, max {max(times):.1f}s")
    Path(args.out).write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
