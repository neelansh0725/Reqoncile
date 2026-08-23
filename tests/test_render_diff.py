"""`render_diff_markdown` must actually run.

It shipped broken: `out += [...]` inside the nested `block()` made `out` local
to that scope, so the preceding `out.extend(...)` raised UnboundLocalError.
Every diff request that reached the renderer returned a 500.

Nothing caught it because nothing called it. The API calls it, and
`scripts/diff_versions.py` calls it only behind `--markdown`, which none of
the T088 validation runs used. These tests exercise every branch.
"""

from __future__ import annotations

import pytest

from agent.differ import diff_reports, render_diff_markdown
from tests.conftest import E, G, M, W, make_report


def render(before: dict, after: dict) -> str:
    return render_diff_markdown(diff_reports(make_report("a", before),
                                             make_report("b", after)))


class TestEveryBranchRenders:
    def test_improved_regressed_unchanged_together(self):
        md = render({"up": G, "down": M, "same": M},
                    {"up": M, "down": G, "same": M})
        assert "# Resume version diff" in md
        for heading in ("## Stronger (1)", "## Weaker (1)", "## Unchanged (1)"):
            assert heading in md
        assert "- **up** — gap → matched" in md
        assert "- **down** — matched → gap" in md

    def test_indeterminate_block_renders(self):
        md = render({"x": M, "y": M}, {"x": E, "y": M})
        assert "## Not comparable (1)" in md
        assert "- **x** — matched → errored" in md

    def test_warnings_render(self):
        md = render({"only_before": M}, {"only_after": M})
        assert "> **Note**" in md
        assert "only one version" in md

    def test_empty_blocks_are_omitted_not_rendered_empty(self):
        md = render({"same": M}, {"same": M})
        assert "## Stronger" not in md and "## Weaker" not in md
        assert "## Unchanged (1)" in md

    def test_the_summary_line_leads(self):
        md = render({"up": G}, {"up": M})
        body = md.splitlines()
        assert body[0] == "# Resume version diff"
        assert any(line.startswith("**Net improvement") for line in body[:5])

    @pytest.mark.parametrize("before,after", [
        ({"a": G}, {"a": M}),
        ({"a": M}, {"a": G}),
        ({"a": M}, {"a": M}),
        ({"a": M}, {"a": E}),
        ({"a": M}, {"b": M}),
    ])
    def test_never_raises(self, before, after):
        # The regression itself: the renderer must not throw on any shape.
        assert isinstance(render(before, after), str)
