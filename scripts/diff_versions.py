#!/usr/bin/env python
"""Diff two resume versions against one JD (T088, FR24-FR27)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.differ import diff_resume_versions, render_diff_markdown  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd")
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    started = time.time()
    diff, before, after = diff_resume_versions(args.jd, args.before, args.after)
    elapsed = time.time() - started

    if args.markdown:
        print(render_diff_markdown(diff))
    else:
        print(f"\nrun {diff.run_id}  ({elapsed:.0f}s)")
        print(f"before {before.run_id}  ·  after {after.run_id}\n")
        print(f"  {diff.summary}\n")
        for c in diff.changes:
            mark = {"improved": "↑", "regressed": "↓",
                    "indeterminate": "?", "unchanged": " "}[c.direction.value]
            if c.direction.value != "unchanged":
                print(f"  {mark} {c.requirement:<44} {c.before.value} → {c.after.value}")
        print(f"\n  ({len(diff.unchanged)} unchanged)")
        for w in diff.warnings:
            print(f"\n! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
