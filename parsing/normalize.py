"""Requirement normalisation and de-duplication (T012).

LLM extraction reliably emits the same skill twice when a JD mentions it in
two bullets ("Python" in the requirements list, "Python programming" under
responsibilities). Left alone that double-counts the skill in the match score
and produces two near-identical rows in the report.

Pure string rules, no model call -- this must be cheap and deterministic.
"""

from __future__ import annotations

import re

from schemas import Necessity, ParsedJD, Requirement

# Filler that varies between mentions of the same skill without changing it.
_FILLER_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "with", "using", "strong",
        "solid", "good", "excellent", "deep", "hands", "on", "hands-on",
        "working", "proven", "demonstrated", "practical", "programming",
        "coding", "development", "skills", "skill", "experience", "knowledge",
        "proficiency", "proficient", "familiarity", "familiar", "expertise",
        "understanding", "ability", "background", "exposure", "competency",
    }
)

_PUNCT_RE = re.compile(r"[^\w\s+#.]+")
_WS_RE = re.compile(r"\s+")

# Necessity precedence: if a JD states a skill as required anywhere, it is
# required, however casually it is mentioned elsewhere.
_NECESSITY_RANK = {Necessity.REQUIRED: 2, Necessity.PREFERRED: 1}


def canonical_key(name: str) -> str:
    """Collapse a requirement name to a comparison key.

    "Strong Python programming skills" and "Python" both key to "python".
    """
    lowered = name.casefold().replace("-", " ")
    lowered = _PUNCT_RE.sub(" ", lowered)
    tokens = [t for t in _WS_RE.split(lowered) if t and t not in _FILLER_WORDS]
    if not tokens:
        # Name was entirely filler -- fall back to the raw form so it is
        # merged only with an identical name, never with everything else.
        return _WS_RE.sub(" ", lowered).strip()
    return " ".join(tokens)


def _merge(existing: Requirement, incoming: Requirement) -> Requirement:
    """Fold `incoming` into `existing`, keeping the stronger signal."""
    # Prefer the shorter name -- "Python" over "Python programming skills".
    name = min((existing.name, incoming.name), key=len)

    necessity = max(
        (existing.necessity, incoming.necessity),
        key=lambda n: _NECESSITY_RANK[n],
    )

    # Keep the source line of the mention that won on necessity, so the quoted
    # text actually supports the required/preferred call.
    if _NECESSITY_RANK[incoming.necessity] > _NECESSITY_RANK[existing.necessity]:
        source_text, category = incoming.source_text, incoming.category
    else:
        source_text, category = existing.source_text, existing.category

    return Requirement(
        name=name,
        category=category,
        necessity=necessity,
        source_text=source_text,
    )


def normalize_requirements(
    requirements: list[Requirement],
) -> tuple[list[Requirement], list[str]]:
    """De-duplicate by canonical key, preserving first-seen order.

    Returns (requirements, warnings).
    """
    merged: dict[str, Requirement] = {}
    warnings: list[str] = []

    for requirement in requirements:
        key = canonical_key(requirement.name)
        if not key:
            warnings.append(f"dropped unnameable requirement: {requirement.name!r}")
            continue

        if key in merged:
            before = merged[key]
            merged[key] = _merge(before, requirement)
            if before.necessity is not merged[key].necessity:
                warnings.append(
                    f"{merged[key].name!r} appeared as both preferred and "
                    "required; kept required"
                )
        else:
            merged[key] = requirement

    return list(merged.values()), warnings


def normalize_parsed_jd(parsed: ParsedJD) -> ParsedJD:
    """Apply de-duplication to a whole extraction, carrying warnings through."""
    requirements, warnings = normalize_requirements(parsed.requirements)
    return ParsedJD(
        requirements=requirements,
        warnings=[*parsed.warnings, *warnings],
    )
