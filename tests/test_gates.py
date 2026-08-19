"""The label gates (FR10, FR12, FR21).

Weak matches get rewritten because the experience is there and under-sold.
Gaps get prepared for because it is not there and no rewrite would be honest.
Crossing those wires is the failure FR12 exists to prevent.
"""

from __future__ import annotations

import pytest

from agent.interview_prep import PrepNotApplicable, prepare_for_gap, prepare_for_gaps
from agent.rewriter import RewriteNotApplicable, suggest_rewrite
from tests.conftest import E, G, M, W, make_classification


class TestInterviewPrepGate:
    @pytest.mark.parametrize("label", [M, W, E])
    def test_non_gaps_are_refused(self, label):
        with pytest.raises(PrepNotApplicable):
            prepare_for_gap(make_classification("Kubernetes", label))

    def test_bulk_helper_filters_instead_of_raising(self):
        # Callers pass a whole report; a non-gap there is ordinary input, not
        # a programming error.
        out = prepare_for_gaps([
            make_classification("a", M), make_classification("b", W),
        ])
        assert out.prepared == []
        assert out.question_count == 0


class TestRewriteGate:
    @pytest.mark.parametrize("label", [M, G, E])
    def test_non_weak_is_refused(self, label):
        # README: 'Gaps are never rewritten (FR12)'. A rewrite for a gap would
        # be inventing experience.
        with pytest.raises(RewriteNotApplicable):
            suggest_rewrite(make_classification("Kubernetes", label), collection=None)
