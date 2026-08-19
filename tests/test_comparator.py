"""Multi-JD comparison bounds and ranking hygiene (FR17-FR20)."""

from __future__ import annotations

import pytest

from agent.comparator import MAX_JDS, compare_jds, rank_reports
from tests.conftest import M, make_report


class TestInputBounds:
    @pytest.mark.parametrize("count", [0, 1, MAX_JDS + 1])
    def test_jd_count_is_bounded(self, count):
        # Each JD costs one hosted call per requirement against a daily cap.
        with pytest.raises(ValueError, match="compare 2 to"):
            compare_jds(["jd"] * count, "resume")

    def test_duplicate_labels_are_refused(self):
        # Labels are the join key between reports and ranking entries.
        with pytest.raises(ValueError, match="unique"):
            compare_jds(["dir_a/same.txt", "dir_b/same.txt"], "resume")


class TestRankingRequiresSomethingToRank:
    def test_fewer_than_two_scoreable_jds_returns_a_warning_not_a_ranking(self):
        ranking, _, warnings = rank_reports([("only", make_report("a", {"x": M}))])
        assert ranking == []
        assert any("at least two" in w for w in warnings)

    def test_unscoreable_jds_do_not_produce_a_rank(self):
        # A JD with nothing classifiable has no score. Ranking it anyway would
        # invent a comparison.
        empty = make_report("b", {})
        ranking, _, warnings = rank_reports([
            ("real", make_report("a", {"x": M})), ("empty", empty),
        ])
        assert ranking == []
        assert any("at least two" in w for w in warnings)
