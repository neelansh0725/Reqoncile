"""Version diffing (FR26-FR27).

The claim under test: the diff never asserts movement it did not observe, and
never prints a score delta that would not mean what it appears to.
"""

from __future__ import annotations

from agent.differ import diff_reports
from schemas import ChangeDirection
from tests.conftest import E, G, M, W, make_report


def directions(diff):
    return {c.requirement: c.direction for c in diff.changes}


class TestDirection:
    def test_movement_is_classified_on_the_gap_weak_matched_scale(self):
        diff = diff_reports(
            make_report("a", {"up1": G, "up2": W, "down": M, "same": M}),
            make_report("b", {"up1": W, "up2": M, "down": G, "same": M}),
        )
        d = directions(diff)
        assert d["up1"] is ChangeDirection.IMPROVED
        assert d["up2"] is ChangeDirection.IMPROVED
        assert d["down"] is ChangeDirection.REGRESSED
        assert d["same"] is ChangeDirection.UNCHANGED

    def test_errored_is_indeterminate_not_unchanged(self):
        # Claiming "no change" for something one side never assessed is the
        # same over-claim as calling an unassessed requirement a gap.
        diff = diff_reports(
            make_report("a", {"x": M}), make_report("b", {"x": E}),
        )
        assert directions(diff)["x"] is ChangeDirection.INDETERMINATE
        assert len(diff.unchanged) == 0

    def test_errored_requirement_is_not_silently_dropped(self):
        # Regression guard: `errored` lives outside report.classifications, so
        # an implementation reading only that list loses the requirement and
        # then blames a JD-parse mismatch for its absence.
        diff = diff_reports(
            make_report("a", {"x": M, "y": M}), make_report("b", {"x": E, "y": M}),
        )
        assert "x" in directions(diff)
        assert not any("JD parse" in w for w in diff.warnings)


class TestScoreDeltaHonesty:
    def test_delta_reported_when_both_versions_scored_the_same_set(self):
        diff = diff_reports(
            make_report("a", {"x": G, "y": W, "z": M}),
            make_report("b", {"x": W, "y": M, "z": M}),
        )
        assert diff.before_score is not None and diff.after_score is not None
        assert "Score" in diff.summary

    def test_delta_withheld_when_denominators_differ(self):
        # "Net improvement, score down 8 points" reads as a scoring bug. It is
        # denominator drift, and the honest move is to not print it.
        diff = diff_reports(
            make_report("a", {"x": G, "y": M}), make_report("b", {"x": W, "y": E}),
        )
        assert diff.before_score is None and diff.after_score is None
        assert "Score" not in diff.summary
        assert any("not compared" in w for w in diff.warnings)

    def test_name_mismatch_is_warned_not_hidden(self):
        # Requirements are matched by name, which is only sound under a shared
        # JD parse (D3/D4). A mismatch means that assumption was violated.
        diff = diff_reports(
            make_report("a", {"Docker": G}), make_report("b", {"Dockerised": M}),
        )
        assert diff.changes == []
        assert any("only one version" in w for w in diff.warnings)


class TestSummaryLine:
    def test_pure_improvement(self):
        s = diff_reports(make_report("a", {"x": G}), make_report("b", {"x": M})).summary
        assert s.startswith("Net improvement: 1 requirement stronger")

    def test_pure_regression(self):
        s = diff_reports(make_report("a", {"x": M}), make_report("b", {"x": G})).summary
        assert s.startswith("Net regression: 1 requirement weaker")

    def test_equal_movement_both_ways_is_not_no_change(self):
        # The resume traded one requirement for another. That is worth seeing.
        s = diff_reports(
            make_report("a", {"x": M, "y": G}), make_report("b", {"x": G, "y": M}),
        ).summary
        assert s.startswith("Mixed:") and "no net gain" in s

    def test_no_movement(self):
        s = diff_reports(
            make_report("a", {"x": M, "y": G}), make_report("b", {"x": M, "y": G}),
        ).summary
        assert s.startswith("No change: all 2 requirements")

    def test_nothing_in_common(self):
        s = diff_reports(make_report("a", {"x": M}), make_report("b", {"y": M})).summary
        assert "No requirements in common" in s


class TestOrdering:
    def test_movement_sorts_above_unchanged(self):
        diff = diff_reports(
            make_report("a", {"aaa": M, "zzz": G}),
            make_report("b", {"aaa": M, "zzz": M}),
        )
        # The point of the view is what changed.
        assert diff.changes[0].requirement == "zzz"
