"""Salvage usable requirements from malformed or truncated model output (T015).

`with_structured_output` validates a whole object at once: one bad requirement
out of twenty throws all twenty away, and a response truncated at `max_tokens`
yields nothing at all. For a report generator that is the wrong trade -- 18
good requirements plus a warning beats an empty parse (NFR3).

Nothing here calls a model. Given raw text it returns whatever validates.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from schemas import Requirement


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Return every complete JSON object embedded in `text`, at any depth.

    Uses a stack of open-brace positions rather than a depth counter, because
    the case that matters most is a response truncated mid-array: the outer
    `{"requirements": [...]}` wrapper never closes, so a depth-0-only scan
    would discard the complete requirement objects nested inside it. Tracks
    string/escape state so a brace inside a quoted value cannot skew the scan.

    Objects that never closed are dropped; everything that did is kept.
    """
    objects: list[dict[str, Any]] = []
    stack: list[int] = []
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            stack.append(index)
        elif char == "}" and stack:
            start = stack.pop()
            try:
                objects.append(json.loads(text[start : index + 1]))
            except json.JSONDecodeError:
                pass

    return objects


def _coerce(payload: Any) -> list[dict[str, Any]]:
    """Pull candidate requirement dicts out of whatever shape came back."""
    if isinstance(payload, dict):
        for key in ("requirements", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        # A bare single requirement.
        if "name" in payload:
            return [payload]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def salvage_requirements(text: str) -> tuple[list[Requirement], list[str]]:
    """Best-effort recovery of requirements from raw model text.

    Returns (requirements, warnings). Never raises.
    """
    warnings: list[str] = []
    candidates: list[dict[str, Any]] = []

    # 1. Whole payload parses cleanly -- the common "schema drifted" case.
    try:
        candidates = _coerce(json.loads(text))
    except (json.JSONDecodeError, TypeError):
        # 2. Truncated or fenced. Recover the objects that did close, then
        #    keep only those shaped like requirements (a bare `{...}` wrapper
        #    object would otherwise be counted).
        recovered = extract_json_objects(text or "")
        nested = [obj for obj in recovered if "name" in obj]
        if not nested:
            for obj in recovered:
                nested.extend(_coerce(obj))
        candidates = nested
        if candidates:
            warnings.append(
                f"model output was not valid JSON; salvaged {len(candidates)} "
                "candidate requirement(s) from a partial response"
            )

    if not candidates:
        return [], ["model output contained no recoverable requirements"]

    requirements: list[Requirement] = []
    rejected = 0
    for candidate in candidates:
        try:
            requirements.append(Requirement.model_validate(candidate))
        except ValidationError:
            rejected += 1

    if rejected:
        warnings.append(
            f"dropped {rejected} malformed requirement(s) that failed validation"
        )

    return requirements, warnings
