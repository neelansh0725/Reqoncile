"""Shared fixtures.

Every test here is offline: no LLM call, no network, no quota. The point of
this suite is the *honesty constraints* — the validators and gates that carry
the project's claims. Those are pure logic, and pure logic is exactly what
should be pinned against regression.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reporting.generate_report import assemble_report  # noqa: E402
from schemas import (  # noqa: E402
    Category,
    Classification,
    MatchLabel,
    Necessity,
    Requirement,
)

M, W, G, E = MatchLabel.MATCHED, MatchLabel.WEAK, MatchLabel.GAP, MatchLabel.ERRORED


def make_requirement(name: str, **kwargs) -> Requirement:
    return Requirement(
        name=name,
        category=kwargs.get("category", Category.TECHNICAL),
        necessity=kwargs.get("necessity", Necessity.REQUIRED),
        source_text=kwargs.get("source_text", name),
    )


def make_classification(name: str, label: MatchLabel, **kwargs) -> Classification:
    """A valid Classification for `label`, satisfying the evidence rules."""
    if label is MatchLabel.ERRORED:
        kwargs.setdefault("error", "simulated failure")
    evidence = kwargs.get(
        "evidence_chunk_ids",
        [] if label in (MatchLabel.GAP, MatchLabel.ERRORED) else ["chunk-1"],
    )
    return Classification(
        requirement=make_requirement(name),
        label=label,
        justification=kwargs.get("justification", "because the resume says so"),
        evidence_chunk_ids=evidence,
        retrieved_scores=kwargs.get("retrieved_scores", {}),
        error=kwargs.get("error"),
    )


def make_report(run_id: str, labels: dict[str, MatchLabel]):
    """Assemble a report from {requirement_name: label}."""
    return assemble_report(
        run_id,
        [make_classification(n, l) for n, l in labels.items()],
        [], [], [],
    )


@pytest.fixture
def report_factory():
    return make_report
