#!/usr/bin/env python
"""Re-establish JD ordering under the current extraction rule (T070/T071).

The ranking is the one claim T071 stands behind: extraction volume is not
reproducible (D3), so absolute scores are not quotable, but the *ordering* of
JDs against one resume should be. This measures whether that survived a rule
change that moved extraction volume substantially.
"""

from __future__ import annotations

import glob
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logging_utils import read_run  # noqa: E402
from pipeline import run_pipeline  # noqa: E402

RESUME = Path("test_data/resumes/Best_withoutphoto.pdf")

# Pre-rule baseline. amazon and ey are their post-D1-fix re-runs; the other
# seven had zero errored requirements, so D1 never affected them.
BEFORE = {
    "advantest_ai_engineering_intern": 60.7,
    "zs_business_technology_solutions_associate": 51.6,
    "mathco_ai_analyst": 50.0,
    "osfin_implementation_engineer": 50.0,
    "amazon_sde1_intern": 42.8,
    "ey_consulting_technology_analyst": 41.5,
    "nse_technology_infrastructure": 30.8,
    "nse_technology_operations": 21.4,
    "zs_decision_analytics_associate": 16.7,
}


def main() -> int:
    rows = []
    started = time.time()
    for index, path in enumerate(sorted(glob.glob("test_data/sample_jds/*.txt")), 1):
        name = Path(path).stem
        print(f"[{index}/9] {name}", flush=True)
        try:
            report, timings = run_pipeline(Path(path), RESUME)
            stages = Counter(e["stage"] for e in read_run(report.run_id))
            rows.append({
                "jd": name, "ok": True, "score": report.score,
                "requirements": len(report.classifications) + len(report.errored),
                "matched": len(report.matched), "weak": len(report.weak),
                "gaps": len(report.gaps), "errored": len(report.errored),
                "seconds": timings.total,
                "rate_limited": stages.get("classify.rate_limited", 0),
                "real_errors": stages.get("classify.error", 0)
                               + stages.get("classify.retrieval_error", 0),
            })
            print(f"    {timings.total:>6.0f}s  {report.score:>5.1f}%  "
                  f"{len(report.classifications) + len(report.errored)} reqs  "
                  f"M{len(report.matched)} W{len(report.weak)} G{len(report.gaps)} "
                  f"E{len(report.errored)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            rows.append({"jd": name, "ok": False, "error": str(exc)})
            print(f"    CRASHED: {exc}", flush=True)

    elapsed = time.time() - started
    Path("/private/tmp/claude-501/-Users-4th-and-bleeker-Desktop-Reqoncile/"
         "86d8ace2-94fe-4fd7-b048-ae1ff8ac69bb/scratchpad/ranking.json").write_text(
        json.dumps({"rows": rows, "before": BEFORE, "elapsed": elapsed}, indent=2))
    print(f"\nfinished in {elapsed/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
