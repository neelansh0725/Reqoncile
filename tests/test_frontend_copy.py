"""Guards on user-visible frontend copy.

These are lint-shaped rather than behavioural, and they exist because the
same mistakes kept reappearing by hand: em-dashes drifting back into copy, and
operator telemetry leaking into product surfaces.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
SOURCES = sorted(SRC.glob("*.jsx"))


def lines(path: Path):
    """Numbered source lines, comments excluded.

    Only user-visible copy is under test. Comments legitimately quote the very
    patterns these guards ban, as counter-examples.
    """
    out, in_block = [], False
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        stripped = raw.strip()
        if in_block:
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("/*"):
            in_block = "*/" not in stripped
            continue
        if stripped.startswith(("//", "*", "{/*")):
            continue
        out.append((n, raw))
    return out


class TestNoDashesInCopy:
    """Em-dash and en-dash are banned in UI copy.

    Partly house style, mostly that they are the strongest tell of unedited
    generated text, and this project's credibility rests on looking
    deliberate.
    """

    @pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
    def test_no_em_or_en_dash(self, path):
        offenders = [f"{path.name}:{n}: {ln.strip()[:80]}"
                     for n, ln in lines(path) if "—" in ln or "–" in ln]
        assert not offenders, "use a comma, colon, or full stop:\n  " + "\n  ".join(offenders)


class TestNoOperatorTelemetryInUI:
    """Model ids, tier names and per-stage timings are operator detail.

    They were rendered in the masthead and under the score, where they read as
    debug output left switched on.
    """

    BANNED = ("reasoning_tier", "generation_tier", "jd_parse", "resume_index")

    @pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
    def test_no_internal_stage_names_rendered(self, path):
        offenders = [f"{path.name}:{n}: {ln.strip()[:80]}"
                     for n, ln in lines(path)
                     for token in self.BANNED if token in ln]
        assert not offenders, "operator detail in product copy:\n  " + "\n  ".join(offenders)


class TestEllipsisCharacter:
    """`…` not `...` (Web Interface Guidelines, typography)."""

    @pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
    def test_no_three_dot_ellipsis_in_strings(self, path):
        offenders = [f"{path.name}:{n}: {ln.strip()[:80]}"
                     for n, ln in lines(path)
                     if re.search(r'"[^"]*\.\.\.[^"]*"', ln)]
        assert not offenders, "use the ellipsis character:\n  " + "\n  ".join(offenders)


class TestLoadingPlaceholderClaimsNoStage:
    """The skeleton must not invent progress.

    The client cannot know which pipeline stage is running: stage timings come
    back only in the final response, and no run id exists to poll before then.
    Any stage label would be fabricated, which is precisely what this project
    argues against everywhere else.
    """

    def test_skeleton_does_not_name_a_stage(self):
        text = (SRC / "components.jsx").read_text()
        start = text.index("export function ReportSkeleton")
        body = text[start:text.index("export function ScoreHeader")]
        # Comments explain why these are absent; strip them before checking.
        body = re.sub(r"//.*", "", body)
        for claim in ("Indexing", "Classifying", "Retrieving", "Parsing", "Embedding"):
            assert claim.lower() not in body.lower(), (
                f"skeleton claims stage {claim!r}, which the client cannot know"
            )


class TestHiddenAttributeIsNotDefeated:
    """`hidden` is a UA `display: none` and loses to any class `display` rule.

    The collapsed input form relies on it. Without an explicit `[hidden]`
    rule, `.inputs { display: grid }` outranks it and the "collapsed" form
    stays fully visible.
    """

    def test_stylesheet_defends_the_hidden_attribute(self):
        css = (SRC / "styles.css").read_text()
        assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none", css), (
            "add `[hidden] { display: none !important; }` or the hidden "
            "attribute is inert wherever a class sets display"
        )
