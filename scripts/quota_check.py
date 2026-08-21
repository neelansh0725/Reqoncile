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

    # Per model, never summed across models. Quotas are per model
    # ("GenerateRequestsPerMinutePerProjectPerModel"), so adding a second
    # hosted model's calls into one total would report a budget that does not
    # exist -- and would silently mis-gate a run once the generation tier
    # moved off local Ollama onto a hosted provider.
    used_by_model: dict[str, int] = {}
    for (provider, model), outcomes in sorted(by_model.items()):
        total = sum(outcomes.values())
        local = provider == PROVIDER_OLLAMA
        detail = ", ".join(f"{k} {v}" for k, v in sorted(outcomes.items()))
        if local:
            print(f"  {provider}/{model}: {total} calls ({detail}) — local, no quota")
            continue
        used_by_model[model] = used_by_model.get(model, 0) + total
        limit = DAILY_LIMITS.get(model)
        if limit:
            print(f"  {provider}/{model}: {total}/{limit} used, "
                  f"{limit - total} remaining ({detail})")
        else:
            print(f"  {provider}/{model}: {total} used, daily limit unknown ({detail})")

    if args.planned is None:
        return 0

    # A planned run is gated against every hosted model it would touch. With
    # the generation tier on a hosted provider that is two models -- or one,
    # when both tiers share a model, in which case they share the budget too.
    hosted: dict[str, list[str]] = {}
    for tier_name in ("reasoning", "generation"):
        tier = settings.tier(tier_name)
        if tier.provider != PROVIDER_OLLAMA:
            # Both tiers on one model means they share the budget, and the
            # label should say so rather than naming whichever was seen last.
            hosted.setdefault(tier.model, []).append(tier_name)
    if not hosted:
        print(f"\n  planned run: {args.planned} calls — both tiers are local, "
              "no daily quota applies")
        return 0

    blocked = False
    print()
    for model, tier_names in sorted(hosted.items()):
        tier = "+".join(tier_names)
        limit = DAILY_LIMITS.get(model)
        if not limit:
            print(f"  {model} ({tier}): daily limit unknown — cannot gate")
            continue
        remaining = limit - used_by_model.get(model, 0)
        fits = args.planned <= remaining
        blocked |= not fits
        print(f"  {model} ({tier}): planned {args.planned} against {remaining} "
              f"remaining — {'fits' if fits else 'DOES NOT FIT'}")

    if blocked:
        print("  Do not start it. A sweep that dies halfway wastes what it "
              "already spent and produces no usable result.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
