"""Automated grounding check for rewrite suggestions (T043, R2).

The rewrite prompt (T040) forbids adding facts. This module verifies it, on
the principle that a safety property enforced only by a prompt is not a
property at all — especially on a local 7-8B model, which follows negative
constraints less reliably than the hosted tier.

Three checks, ordered by how damaging the failure is:

1. **Invented figures.** "improved load time" becoming "improved load time by
   40%" is the single most likely and most costly fabrication: it is specific,
   plausible, and immediately falsifiable in an interview.
2. **Invented named entities.** A tool, framework or platform in the rewrite
   that appears nowhere in the source bullet.
3. **Invented scale or seniority.** "led", "owned", "production",
   "large-scale" — claims about the candidate's role or the system's size
   that the source does not support.

A flag marks a suggestion for review; it does not silently discard it. The
check is a heuristic and can be wrong in both directions, so the decision it
supports is "show this to the human", not "delete this".
"""

from __future__ import annotations

import re

# Figures of any kind, including percentages, decimals and thousands
# separators. "5-task" and "3x" count -- an invented multiplier is a fabricated
# metric.
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*\s*%?")

# Capitalised token not at the start of a sentence: candidate proper noun.
_CAPITALISED_RE = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][A-Za-z0-9+#.\-]{1,})\b")

# Claims about role or scale the source must support explicitly.
_SCALE_TERMS = frozenset({
    "led", "leading", "owned", "owning", "managed", "managing", "mentored",
    "mentoring", "supervised", "headed", "directed", "spearheaded",
    "production", "enterprise", "large-scale", "largescale", "company-wide",
    "organisation-wide", "organization-wide", "mission-critical",
    "high-traffic", "high-volume", "cross-functional", "senior", "principal",
})

# Words that are capitalised for reasons other than being an entity.
_CAPITALISED_ALLOWED = frozenset({"I", "A"})

_WORD_RE = re.compile(r"[A-Za-z0-9+#.\-]+")


def _vocabulary(*sources: str) -> set[str]:
    """Lowercased token set of everything the rewrite is allowed to draw on."""
    vocabulary: set[str] = set()
    for source in sources:
        for token in _WORD_RE.findall(source.lower()):
            vocabulary.add(token)
            vocabulary.add(token.rstrip(".,;:"))
    return vocabulary


def check_grounding(
    suggested_text: str,
    original_text: str,
    requirement_name: str = "",
) -> list[str]:
    """Return a flag per unsupported addition. Empty means clean.

    `requirement_name` is part of the permitted vocabulary on purpose: the
    whole point of a rewrite is to surface the job's terminology, so naming
    the requirement is the intended behaviour, not a fabrication.
    """
    flags: list[str] = []
    allowed = _vocabulary(original_text, requirement_name)

    source_numbers = set(_NUMBER_RE.findall(original_text.replace(" %", "%")))
    source_numbers = {n.strip() for n in source_numbers}
    for number in _NUMBER_RE.findall(suggested_text.replace(" %", "%")):
        number = number.strip()
        if number not in source_numbers:
            flags.append(
                f"introduces the figure {number!r}, which does not appear in "
                "the source bullet"
            )

    for token in _CAPITALISED_RE.findall(suggested_text):
        if token in _CAPITALISED_ALLOWED:
            continue
        if token.lower().rstrip(".,;:") not in allowed:
            flags.append(
                f"introduces {token!r}, which does not appear in the source "
                "bullet or the requirement"
            )

    # Check hyphen-split parts as well as whole tokens: "production-scale" is
    # a single token to the word regex, so a bare "production" entry would
    # otherwise miss it -- and compounds are exactly how scale claims arrive.
    lowered_suggestion: set[str] = set()
    for token in _WORD_RE.findall(suggested_text.lower()):
        lowered_suggestion.add(token)
        lowered_suggestion.update(part for part in token.split("-") if part)

    for term in sorted(_SCALE_TERMS & lowered_suggestion):
        if term not in allowed:
            flags.append(
                f"claims {term!r}, a statement about scale or seniority the "
                "source bullet does not support"
            )

    # Deduplicate while preserving order -- the same token can trip two rules.
    seen: set[str] = set()
    unique: list[str] = []
    for flag in flags:
        if flag not in seen:
            seen.add(flag)
            unique.append(flag)
    return unique
