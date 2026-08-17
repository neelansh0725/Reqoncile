#!/usr/bin/env python
"""Score the classifier against the labelled eval set (T036-T037).

    ./.venv/bin/python scripts/eval_classifier.py
    ./.venv/bin/python scripts/eval_classifier.py --model gemini-3.5-flash-lite --rpm 15
    ./.venv/bin/python scripts/eval_classifier.py --paraphrase        # T037 R1 test
    ./.venv/bin/python scripts/eval_classifier.py --compare gemini-3.5-flash gemini-3.5-flash-lite

Reports per-label accuracy and a confusion matrix. `--paraphrase` re-runs with
each requirement restated in vocabulary the resume never uses, which is the
direct test of R1 (that the system is not keyword matching with extra steps).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.classifier import classify_requirements  # noqa: E402
from config import TierConfig, settings  # noqa: E402
import llm_client  # noqa: E402
from parsing.resume_parser import chunk_resume, load_resume_text  # noqa: E402
from retrieval.vector_store import index_resume  # noqa: E402
from schemas import Requirement  # noqa: E402

LABELS = ("matched", "weak", "gap")


def load_eval_set(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_requirements(items: list[dict], paraphrase: bool) -> list[Requirement]:
    """Turn eval items into Requirements.

    With `paraphrase`, the requirement *name* is replaced by a restatement that
    shares no vocabulary with the resume. Retrieval keys off the name, so this
    changes what the classifier is given, not just how it reads.
    """
    out = []
    for item in items:
        out.append(
            Requirement(
                name=item["paraphrase"] if paraphrase else item["name"],
                category=item["category"],
                necessity=item["necessity"],
                source_text=item["source_text"],
            )
        )
    return out


def run_once(items: list[dict], collection, paraphrase: bool) -> list[dict]:
    requirements = build_requirements(items, paraphrase)
    started = time.time()
    results = classify_requirements(requirements, collection)
    elapsed = time.time() - started

    rows = []
    for item, got in zip(items, results):
        rows.append(
            {
                "name": item["name"],
                "expected": item["expected"],
                "actual": got.label.value,
                "correct": got.label.value == item["expected"],
                "justification": got.justification,
                "evidence": got.evidence_chunk_ids,
                "error": got.error,
            }
        )
    rows.append({"_elapsed": round(elapsed, 1)})
    return rows


def report(rows: list[dict], title: str) -> dict:
    elapsed = next((r["_elapsed"] for r in rows if "_elapsed" in r), None)
    graded = [r for r in rows if "_elapsed" not in r]
    assessed = [r for r in graded if r["actual"] != "errored"]
    errored = len(graded) - len(assessed)
    correct = sum(r["correct"] for r in assessed)

    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")
    if assessed:
        print(f"accuracy: {correct}/{len(assessed)} = {correct / len(assessed):.0%}"
              f"   errored: {errored}   wall: {elapsed}s")
    else:
        print(f"no requirements were assessed (all {errored} errored)")

    print(f"\n{'expected':>9} |" + "".join(f"{c:>9}" for c in LABELS) + "   <- predicted")
    print("-" * 46)
    for expected in LABELS:
        row = Counter(r["actual"] for r in assessed if r["expected"] == expected)
        print(f"{expected:>9} |" + "".join(f"{row.get(c, 0):>9}" for c in LABELS))

    print("\nper-label recall:")
    for label in LABELS:
        subset = [r for r in assessed if r["expected"] == label]
        if subset:
            hit = sum(r["correct"] for r in subset)
            print(f"  {label:8} {hit}/{len(subset)} = {hit / len(subset):.0%}")

    misses = [r for r in assessed if not r["correct"]]
    if misses:
        print(f"\nmisclassified ({len(misses)}):")
        for r in misses:
            print(f"  {r['name'][:30]:32} expected {r['expected']:8} got {r['actual']:8}")
            print(f"    {r['justification'][:96]}")

    return {
        "accuracy": (correct / len(assessed)) if assessed else 0.0,
        "correct": correct,
        "assessed": len(assessed),
        "errored": errored,
        "elapsed": elapsed,
    }


def set_model(model: str | None, rpm: int | None) -> None:
    if model:
        object.__setattr__(
            settings, "reasoning",
            TierConfig(name="reasoning", provider=settings.reasoning.provider,
                       model=model, temperature=settings.reasoning.temperature),
        )
        llm_client._model_cache.clear()
    if rpm is not None:
        object.__setattr__(settings, "llm_requests_per_minute", rpm)
    llm_client._rate_limiters.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the classifier.")
    parser.add_argument("--eval-set", type=Path, default=Path("test_data/eval_set.json"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--rpm", type=int, default=None)
    parser.add_argument("--paraphrase", action="store_true",
                        help="Restate requirements without resume vocabulary (T037).")
    parser.add_argument("--compare", nargs="+", default=None,
                        help="Run the eval on several models and compare.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    data = load_eval_set(args.eval_set)
    items = data["items"]

    text = load_resume_text(Path(data["resume"]))
    collection = index_resume(text, chunk_resume(text))
    print(f"eval set : {len(items)} pairs from {args.eval_set}")
    print(f"resume   : {data['resume']}")

    all_rows: dict[str, list[dict]] = {}
    summaries: dict[str, dict] = {}

    models = args.compare or [args.model or settings.reasoning.model]
    for model in models:
        set_model(model, args.rpm)
        label = f"{model}{' (paraphrased)' if args.paraphrase else ''}"
        rows = run_once(items, collection, args.paraphrase)
        all_rows[label] = rows
        summaries[label] = report(rows, label)

    if len(summaries) > 1:
        print(f"\n{'=' * 74}\ncomparison\n{'=' * 74}")
        print(f"{'model':44}{'accuracy':>10}{'errored':>9}{'wall':>8}")
        for label, s in summaries.items():
            print(f"{label:44}{s['correct']}/{s['assessed']:<7}"
                  f"{s['errored']:>9}{s['elapsed']:>7}s")

    if args.out:
        args.out.write_text(json.dumps(all_rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
