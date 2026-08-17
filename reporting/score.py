"""Match scoring (T045, FR13).

Pure function, no model call. The score is arithmetic over the classifier's
verdicts, so it is reproducible and explainable — if a candidate asks why the
number is 62, the breakdown answers it exactly.

Three things are deliberately excluded from the calculation:

* **Eligibility requirements** (T015a). They never reach the classifier, so
  they have no Matched/Weak/Gap verdict to score. Counting a city name or a
  graduation year as a "gap" would drag the number down for reasons that have
  nothing to do with fit. They are reported as a checklist instead.
* **Errored requirements** (T032). We failed to assess them. Scoring them as
  gaps would assert a finding the system never made.
* **The similarity scores.** Retrieval confidence is not evidence of a match
  (see `test_data/retrieval_notes.md`); only the verdict counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from schemas import Classification, MatchLabel, Necessity

# How much a requirement contributes to the denominator. A missing preferred
# requirement should sting, not dominate -- the PRD asks only that required
# outweigh preferred, so the ratio is a judgement call, exposed here rather
# than buried in the arithmetic.
NECESSITY_WEIGHT: dict[Necessity, float] = {
    Necessity.REQUIRED: 1.0,
    Necessity.PREFERRED: 0.4,
}

# Credit earned per verdict. A weak match earns half: the experience is real
# (that is what separates weak from gap), but a reader scanning the resume
# would miss it, so it is not yet worth full marks -- and the rewrite
# suggestion is precisely the route to the other half.
LABEL_CREDIT: dict[MatchLabel, float] = {
    MatchLabel.MATCHED: 1.0,
    MatchLabel.WEAK: 0.5,
    MatchLabel.GAP: 0.0,
}


@dataclass(frozen=True)
class ScoreBreakdown:
    """The score plus everything needed to explain it."""

    score: float                    # 0-100
    earned: float
    possible: float
    counts: dict[str, int]          # label -> n, over scored requirements
    scored: int                     # requirements that contributed
    excluded_errored: int           # assessed nothing, so excluded

    @property
    def is_meaningful(self) -> bool:
        """False when nothing could be scored -- 0.0 would be misleading."""
        return self.possible > 0.0


def score_classifications(
    classifications: Sequence[Classification],
) -> ScoreBreakdown:
    """Weighted match score over classified requirements (FR13).

    Score = earned / possible * 100, where each requirement contributes its
    necessity weight to `possible` and that weight times its label credit to
    `earned`.
    """
    earned = 0.0
    possible = 0.0
    counts: dict[str, int] = {}
    scored = 0
    errored = 0

    for classification in classifications:
        if classification.label is MatchLabel.ERRORED:
            errored += 1
            continue

        weight = NECESSITY_WEIGHT[classification.requirement.necessity]
        credit = LABEL_CREDIT[classification.label]

        possible += weight
        earned += weight * credit
        scored += 1
        counts[classification.label.value] = (
            counts.get(classification.label.value, 0) + 1
        )

    score = (earned / possible * 100.0) if possible > 0 else 0.0

    return ScoreBreakdown(
        score=round(score, 1),
        earned=round(earned, 3),
        possible=round(possible, 3),
        counts=counts,
        scored=scored,
        excluded_errored=errored,
    )


def explain_score(breakdown: ScoreBreakdown) -> str:
    """One-line, human-checkable statement of how the score was reached."""
    if not breakdown.is_meaningful:
        return "No requirements could be scored."

    parts = [
        f"{breakdown.counts.get('matched', 0)} matched",
        f"{breakdown.counts.get('weak', 0)} weak (half credit)",
        f"{breakdown.counts.get('gap', 0)} gaps",
    ]
    line = (
        f"{breakdown.score:.0f}% — {', '.join(parts)} across "
        f"{breakdown.scored} scored requirements "
        f"({breakdown.earned:g} of {breakdown.possible:g} weighted points)."
    )
    if breakdown.excluded_errored:
        line += (
            f" {breakdown.excluded_errored} requirement(s) could not be "
            "assessed and are excluded from the score."
        )
    return line
