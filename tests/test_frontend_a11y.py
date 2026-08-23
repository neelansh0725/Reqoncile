"""Accessibility invariants in the frontend source.

Source-level and lint-shaped. They cannot replace using the thing with a
screen reader, and they are not meant to: they pin the specific regressions
found in the UI audit so those particular mistakes cannot come back silently.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
APP = (SRC / "App.jsx").read_text()
COMPONENTS = (SRC / "components.jsx").read_text()


class TestEveryTextareaIsLabelled:
    """A placeholder is not a label. It vanishes on the first keystroke and is
    not announced as one."""

    def test_the_matcher_sees_every_textarea(self):
        """Guards the guard.

        The first version used `[^>]*?`, which cannot span the `>` inside
        `onChange={(e) => ...}`, so it silently matched no multi-line textarea
        at all and passed with the labels deleted.
        """
        found = len(re.findall(r"<textarea\b.*?/>", APP, re.S))
        declared = APP.count("<textarea")
        assert found == declared > 0, (
            f"matcher found {found} of {declared} textareas"
        )

    def test_no_textarea_relies_on_a_placeholder_alone(self):
        unlabelled = []
        for match in re.finditer(r"<textarea\b.*?/>", APP, re.S):
            tag = match.group(0)
            if "aria-label" in tag or re.search(r'\bid="', tag):
                continue
            unlabelled.append(" ".join(tag.split())[:90])
        assert not unlabelled, (
            "textarea with neither aria-label nor an id for htmlFor:\n  "
            + "\n  ".join(unlabelled)
        )


class TestTabPatternIsComplete:
    """Announcing tabs commits to behaving like tabs.

    Roles alone gave a tablist with no arrow keys, no roving tabindex and no
    controlled panel: it announced one thing and did another.
    """

    def test_tabs_control_a_panel(self):
        assert 'role="tab"' in APP
        assert 'aria-controls="mode-panel"' in APP
        assert 'role="tabpanel"' in APP
        assert "aria-labelledby" in APP

    def test_tabs_have_roving_tabindex(self):
        assert "tabIndex={mode === id ? 0 : -1}" in APP

    def test_tabs_handle_arrow_keys(self):
        assert "onKeyDown={onTabKeyDown}" in APP
        for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
            assert key in APP, f"tab pattern does not handle {key}"


class TestResultsAreAnnounced:
    """A run takes minutes. Silence at the end is a failure state for anyone
    not watching the screen."""

    def test_a_polite_live_region_exists(self):
        assert 'aria-live="polite"' in APP
        assert 'role="status"' in APP

    def test_it_announces_completion_not_just_progress(self):
        assert "Analysis complete" in APP


class TestDisclosureButtonsCarryContext:
    """Five buttons all reading "why?" are indistinguishable in a screen
    reader's element list."""

    def test_why_button_has_a_specific_accessible_name(self):
        assert "aria-label={" in COMPONENTS
        assert "was classified as" in COMPONENTS


class TestEligibilityCheckboxesAreReal:
    """A focusable control that discards its own state is worse than no
    control: it invites input and silently drops it."""

    def test_checkbox_is_controlled(self):
        assert "checked={confirmed.has(r.name)}" in COMPONENTS
        assert "onChange=" in COMPONENTS
