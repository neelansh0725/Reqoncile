#!/usr/bin/env python
"""Report hosted-model usage against the free-tier daily cap.

Reads the usage ledger written at the call boundary by `llm_client`, not
pipeline stages. That distinction is the whole point: a stage-counting check
missed `scripts/eval_classifier.py` entirely (it classifies directly, without
the pipeline) and reported 0 calls immediately after 60 real ones. It also
missed retries, which consume quota whether or not they succeed.

Budget the day before starting a sweep. A sweep that is affordable in
isolation can still fail against a day that is already spent.
"""

from __future__ import annotations

import argparse
import collections
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROVIDER_OLLAMA, settings  # noqa: E402
from logging_utils import read_usage  # noqa: E402

# Measured, not documented by the vendor -- see docs/providers.md.
DAILY_LIMITS = {
    "gemini-3.5-flash-lite": 500,
    "gemini-3.5-flash": 20,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None,
                    help="UTC day as YYYY-MM-DD (default: today, UTC).")
    ap.add_argument("--planned", type=int, default=None,
                    help="Calls a planned run would cost; reports whether it fits.")
    args = ap.parse_args()

    # Provider quotas reset on the provider's clock, which is UTC.
    day = args.day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = read_usage(day=day)

    if not settings.usage_path.exists():
        print(f"no usage ledger at {settings.usage_path} — nothing recorded yet")
        return 0

    by_model: dict[tuple[str, str], collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for r in records:
        by_model[(r.get("provider", "?"), r.get("model", "?"))][
            r.get("outcome", "?")
        ] += 1

    print(f"usage for {day} (UTC)\n")
    if not by_model:
        print("  no model calls recorded today")

    hosted_total = 0
    for (provider, model), outcomes in sorted(by_model.items()):
        total = sum(outcomes.values())
        local = provider == PROVIDER_OLLAMA
        detail = ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items()))
        if local:
            print(f"  {provider}/{model}: {total} calls ({detail}) — local, no quota")
            continue
        hosted_total += total
        limit = DAILY_LIMITS.get(model)
        if limit:
            print(f"  {provider}/{model}: {total}/{limit} used, "
                  f"{limit - total} remaining ({detail})")
        else:
            print(f"  {provider}/{model}: {total} used, daily limit unknown ({detail})")

    limit = DAILY_LIMITS.get(settings.reasoning.model)
    if args.planned is not None and limit:
        remaining = limit - hosted_total
        verdict = "fits" if args.planned <= remaining else "DOES NOT FIT"
        print(f"\n  planned run: {args.planned} calls against {remaining} "
              f"remaining — {verdict}")
        if args.planned > remaining:
            print("  Do not start it. A sweep that dies halfway wastes what it "
                  "already spent and produces no usable result.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
