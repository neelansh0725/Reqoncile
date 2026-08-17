#!/usr/bin/env python
"""Parse one JD and print the requirement list as JSON (T013).

    ./.venv/bin/python scripts/parse_jd.py test_data/sample_jds/mathco.txt
    ./.venv/bin/python scripts/parse_jd.py some_jd.txt --clean-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logging_utils import new_run_id  # noqa: E402
from parsing.jd_parser import load_jd_text, parse_jd  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a JD into requirements.")
    parser.add_argument("path", help="Path to a JD text file ('-' for stdin).")
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Print normalised JD text and exit -- no model call, no API key needed.",
    )
    parser.add_argument(
        "--tier",
        default="reasoning",
        choices=("reasoning", "generation"),
        help="Model tier to extract with (default: reasoning).",
    )
    args = parser.parse_args()

    source: str | Path
    source = sys.stdin.read() if args.path == "-" else Path(args.path)

    if args.clean_only:
        print(load_jd_text(source))
        return 0

    run_id = new_run_id()
    parsed = parse_jd(source, run_id=run_id, tier=args.tier)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "requirement_count": len(parsed.requirements),
                "required": len(parsed.required),
                "preferred": len(parsed.preferred),
                "warnings": parsed.warnings,
                "requirements": [r.model_dump(mode="json") for r in parsed.requirements],
            },
            indent=2,
        )
    )

    if not parsed.requirements:
        print("\nNo requirements extracted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
