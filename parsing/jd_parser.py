"""JD ingestion and structured extraction (FR1-FR3).

Split in two on purpose:

* `load_jd_text` -- deterministic cleanup, no model involved. Cheap to test
  against every sample JD, and keeps prompt input stable so caching isn't
  defeated by incidental whitespace differences.
* `parse_jd` -- the LLM extraction step (FR2).

JDs arrive as bulleted lists, flowing prose, or a mix, often pasted out of a
PDF with page furniture attached (FR3). Cleanup normalises the shape without
trying to impose a template.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from llm_client import REASONING, complete_structured_or_raw
from logging_utils import log_event
from parsing.normalize import normalize_parsed_jd
from parsing.prompts import build_extraction_messages
from parsing.salvage import salvage_requirements
from schemas import ParsedJD

# Common bullet glyphs -> "- ", so prose and bulleted JDs reach the model in
# one shape.
_BULLET_CHARS = "•▪◦‣·∙●○–—*"
_BULLET_RE = re.compile(rf"^\s*[{re.escape(_BULLET_CHARS)}]\s+")

# Page furniture from PDF copy-paste: "Page 3 of 7", a lone page number, or a
# bare form-feed.
_PAGE_FURNITURE_RE = re.compile(
    r"^\s*(?:page\s+\d+\s*(?:of\s+\d+)?|\d{1,3}|[-–—_=*]{3,}|\f)\s*$",
    re.IGNORECASE,
)

_BLANK_RUN_RE = re.compile(r"\n{3,}")

# Treat a str as a path only if it is short enough to plausibly be one and
# actually exists -- a pasted JD is neither.
_MAX_PATHLIKE_LEN = 400


def _looks_like_path(source: str) -> bool:
    if len(source) > _MAX_PATHLIKE_LEN or "\n" in source:
        return False
    try:
        return Path(source).expanduser().is_file()
    except OSError:
        return False


def _drop_repeated_furniture(lines: list[str]) -> list[str]:
    """Drop short lines that repeat on most pages (running headers/footers).

    Only considers lines appearing 3+ times, so a legitimately repeated short
    requirement in a long JD is not silently removed.
    """
    counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 60:
            counts[stripped] = counts.get(stripped, 0) + 1

    repeated = {text for text, count in counts.items() if count >= 3}
    if not repeated:
        return lines
    return [line for line in lines if line.strip() not in repeated]


def load_jd_text(source: str | Path) -> str:
    """Load a JD from a file path or a raw string and normalise it.

    Returns clean text ready for extraction. Raises FileNotFoundError for a
    Path that does not exist, ValueError if the result is empty.
    """
    if isinstance(source, Path):
        raw = source.expanduser().read_text(encoding="utf-8", errors="replace")
    elif _looks_like_path(source):
        raw = Path(source).expanduser().read_text(encoding="utf-8", errors="replace")
    else:
        raw = source

    # NFKC folds smart quotes, ligatures, and full-width chars that PDF
    # extraction leaves behind.
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("​", "")

    lines = [line.rstrip() for line in text.split("\n")]
    lines = [line for line in lines if not _PAGE_FURNITURE_RE.match(line)]
    lines = _drop_repeated_furniture(lines)
    lines = [_BULLET_RE.sub("- ", line) for line in lines]
    lines = [re.sub(r"[ \t]{2,}", " ", line) for line in lines]

    text = _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()

    if not text:
        raise ValueError("job description is empty after normalisation")
    return text


def parse_jd(
    source: str | Path,
    run_id: str | None = None,
    tier: str = REASONING,
) -> ParsedJD:
    """Load, extract, and de-duplicate a JD's requirements (FR1-FR3).

    Runs on the `reasoning` tier: extraction quality is load-bearing for every
    downstream step, and small local models adhere to schemas poorly.

    Never raises on a bad extraction: a model failure yields an empty
    `ParsedJD` carrying a warning, so one unparseable JD cannot take down a
    multi-JD comparison run (NFR3).
    """
    jd_text = load_jd_text(source)
    system, user = build_extraction_messages(jd_text)

    if run_id:
        log_event(
            run_id,
            "jd_parse.start",
            {"source": str(source)[:200], "chars": len(jd_text)},
        )

    parsed, raw_text, error = complete_structured_or_raw(
        ParsedJD, user=user, system=system, tier=tier
    )

    if parsed is None:
        # Don't throw away a response that was mostly fine: recover whatever
        # validated and report the rest as warnings (T015 / NFR3).
        salvaged, salvage_warnings = salvage_requirements(raw_text)
        if run_id:
            log_event(
                run_id,
                "jd_parse.salvage",
                {
                    "error": error,
                    "raw_chars": len(raw_text),
                    "salvaged": len(salvaged),
                    "warnings": salvage_warnings,
                },
            )
        parsed = ParsedJD(
            requirements=salvaged,
            warnings=[f"JD extraction degraded: {error}", *salvage_warnings],
        )

    normalized = normalize_parsed_jd(parsed)

    if run_id:
        log_event(
            run_id,
            "jd_parse.done",
            {
                "extracted": len(parsed.requirements),
                "after_dedupe": len(normalized.requirements),
                "warnings": normalized.warnings,
                "requirements": normalized.requirements,
            },
        )

    return normalized
