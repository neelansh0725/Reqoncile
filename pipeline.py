"""End-to-end pipeline (T050).

One call takes a JD and a resume to a finished report:

    parse JD (FR1-FR3)
      -> split off eligibility (T015a)
      -> load, chunk, embed, index the resume (FR4-FR5)
      -> classify each classifiable requirement (FR7-FR9)
      -> rewrite the weak matches (FR10-FR12)
      -> assemble, summarise, return (FR13-FR14)

Every stage degrades rather than aborting (NFR3). A failed JD parse yields an
empty report with a warning; a failed classification errors one requirement;
a failed rewrite costs one suggestion; a failed summary costs a paragraph.
Only a missing credential raises, because that is a setup problem the user has
to fix rather than a partial result worth reporting.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from agent.classifier import classify_requirements
from agent.rewriter import suggest_rewrites
from logging_utils import log_event, new_run_id
from parsing.jd_parser import parse_jd
from parsing.resume_parser import chunk_resume, load_resume_text
from reporting.generate_report import assemble_report, summarise
from retrieval.vector_store import index_resume
from schemas import AlignmentReport

logger = logging.getLogger(__name__)


@dataclass
class StageTimings:
    """Wall-clock per stage, for the NFR1 budget check (T052)."""

    stages: dict[str, float] = field(default_factory=dict)

    def record(self, name: str, seconds: float) -> None:
        self.stages[name] = round(seconds, 2)

    @property
    def total(self) -> float:
        return round(sum(self.stages.values()), 2)

    def __str__(self) -> str:
        parts = " | ".join(f"{k} {v:.1f}s" for k, v in self.stages.items())
        return f"{parts} | TOTAL {self.total:.1f}s"


def run_pipeline(
    jd_source: str | Path,
    resume_source: str | Path,
    run_id: str | None = None,
    skip_rewrites: bool = False,
    skip_summary: bool = False,
) -> tuple[AlignmentReport, StageTimings]:
    """Run JD + resume to a finished report (FR13).

    Returns the report and per-stage timings. Timings are returned rather than
    logged only, because NFR1 is a budget someone has to be able to check.
    """
    run_id = run_id or new_run_id()
    timings = StageTimings()
    log_event(run_id, "pipeline.start",
              {"jd": str(jd_source)[:200], "resume": str(resume_source)[:200]})

    # --- JD parsing -------------------------------------------------------
    started = time.time()
    parsed = parse_jd(jd_source, run_id=run_id)
    timings.record("jd_parse", time.time() - started)

    split = parsed.split()
    warnings = list(parsed.warnings)

    if not parsed.requirements:
        warnings.append("No requirements were extracted from the job description.")
        report = assemble_report(run_id, [], [], [], warnings)
        log_event(run_id, "pipeline.done", {"empty": True, "timings": timings.stages})
        return report, timings

    # --- Resume ingestion + indexing --------------------------------------
    started = time.time()
    resume_text = load_resume_text(resume_source)
    chunks = chunk_resume(resume_text)
    collection = index_resume(resume_text, chunks)
    timings.record("resume_index", time.time() - started)

    if not chunks:
        warnings.append("The resume produced no indexable content.")
        report = assemble_report(run_id, [], [], split.eligibility, warnings)
        return report, timings

    # --- Classification ---------------------------------------------------
    started = time.time()
    classifications = classify_requirements(
        split.classifiable, collection, run_id=run_id
    )
    timings.record("classify", time.time() - started)

    # --- Rewrites ---------------------------------------------------------
    rewrites = []
    if not skip_rewrites:
        started = time.time()
        rewrites = suggest_rewrites(classifications, collection, run_id=run_id)
        timings.record("rewrite", time.time() - started)

    # --- Report -----------------------------------------------------------
    started = time.time()
    report = assemble_report(
        run_id, classifications, rewrites, split.eligibility, warnings
    )
    if not skip_summary:
        report.summary = summarise(report)
    timings.record("report", time.time() - started)

    log_event(run_id, "pipeline.done", {
        "score": report.score,
        "matched": len(report.matched),
        "weak": len(report.weak),
        "gaps": len(report.gaps),
        "errored": len(report.errored),
        "eligibility": len(report.eligibility),
        "rewrites": len(report.rewrites),
        "timings": timings.stages,
        "total_seconds": timings.total,
    })
    logger.info("pipeline %s complete: %s", run_id, timings)

    return report, timings
