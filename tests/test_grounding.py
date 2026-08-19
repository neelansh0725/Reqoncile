"""The grounding check (T044, R2).

README: 'The grounding check is code, not a prompt instruction. A safety
property enforced only by asking nicely is not a property.'

These tests pin what it catches — and, just as importantly, what it does not,
so the documented limitation stays true rather than drifting into a stronger
claim than the implementation supports.
"""

from __future__ import annotations

import pytest

from agent.grounding import check_grounding

ORIGINAL = (
    "Documented actionable business insights to support data-driven "
    "decision-making."
)


class TestCatchesFabrication:
    def test_invented_figures_are_flagged(self):
        # The single most damaging fabrication, and the one most likely to be
        # probed in an interview.
        assert check_grounding("Improved revenue by 35% across the region", ORIGINAL)

    @pytest.mark.parametrize("suggestion", [
        "Documented insights using Tableau to support decision-making",
        "Documented insights for Deloitte to support decision-making",
    ])
    def test_invented_entities_are_flagged(self, suggestion):
        assert check_grounding(suggestion, ORIGINAL)

    @pytest.mark.parametrize("suggestion", [
        "Led a team documenting business insights",
        "Documented business insights for enterprise-scale clients",
    ])
    def test_seniority_and_scale_claims_are_flagged(self, suggestion):
        assert check_grounding(suggestion, ORIGINAL)


class TestAcceptsGroundedRewrites:
    def test_the_sm3_rewrite_passes(self):
        # The exact suggestion traced end to end in docs/success_metrics.md.
        assert check_grounding(
            "Communicated actionable business insights to support "
            "data-driven decision-making",
            ORIGINAL,
            "Communicate findings clearly",
        ) == []

    def test_requirement_vocabulary_is_permitted(self):
        # Surfacing the job's terminology is the point of a rewrite.
        assert check_grounding(
            "Documented business insights, communicating findings clearly",
            ORIGINAL,
            "Communicate findings clearly",
        ) == []

    def test_hyphenated_compounds_are_split_before_comparison(self):
        # Regression: 'data-driven' must not read as two unsupported tokens.
        assert check_grounding(
            "Supported data driven decision making", ORIGINAL
        ) == []


class TestDocumentedBlindSpot:
    def test_semantic_inflation_in_new_words_is_not_caught(self):
        """README: 'It cannot catch inflation phrased entirely in new words.'

        This test asserts the limitation, not a bug. If it ever starts
        failing, the check got stronger and the README should be updated to
        claim more — which is the good direction, but it must be deliberate.
        """
        inflated = "Documented business insights that drove decision-making"
        assert check_grounding(inflated, ORIGINAL) == []
