#!/usr/bin/env python
"""Generate a DRAFT ground-truth .txt from a resume PDF (T007).

    ./.venv/bin/python scripts/draft_resume_text.py test_data/resumes/<file>.pdf

Writes `<file>.expected.txt` next to the PDF, plus `<file>.review.md` listing
every substitution made so a human can check them.

This is scaffolding, not the parser. The output is a *draft* the human
corrects; the corrected file then becomes the fixture that `resume_parser`
(T016) must reproduce. Deliberately conservative -- it only fixes artifacts
that were enumerated and confirmed against this specific PDF, and never
rewrites wording.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The cleaning rules live in the parser, not here. This script only reports
# what they changed -- if the two drifted apart, the fixture would stop being
# a test of the code that actually runs.
from parsing.resume_parser import (  # noqa: E402
    _GITHUB_ICON,
    _GITHUB_PAIR,
    _KERN_BEFORE_PUNCT,
    _KERN_CAP_LOWER,
    ICON_LABELS as _ICON_LABELS,
    extract_pdf_text as extract_raw,
    normalize_resume_text,
)


def clean(raw: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Return (cleaned_text, [(rule, before, after)]).

    The text comes from `normalize_resume_text`; this function only re-derives
    *what changed* so a human can review each substitution.
    """
    changes: list[tuple[str, str, str]] = []

    for char in sorted({c for c in raw if unicodedata.name(c, "").startswith("LATIN SMALL LIGATURE")}):
        changes.append(("ligature", char, unicodedata.normalize("NFKC", char)))

    staged = unicodedata.normalize("NFKC", raw)
    for icon, label in _ICON_LABELS.items():
        if icon in staged:
            changes.append(("icon-glyph", icon, label))
    if _GITHUB_PAIR.search(staged):
        count = len(_GITHUB_PAIR.findall(staged))
        changes.append(("icon-glyph", f"Github GitHub (x{count})", "GitHub"))

    staged = _GITHUB_PAIR.sub("GitHub", staged)
    for icon, label in _ICON_LABELS.items():
        staged = staged.replace(icon, label)
    if _GITHUB_ICON.search(staged):
        changes.append(("icon-glyph", "Github", "GitHub:"))
    staged = _GITHUB_ICON.sub("GitHub:", staged)

    # Kerning edits get listed individually -- they are the ones most worth a
    # human eye, since the rule could in principle join a real single-letter
    # word to the next one.
    for match in _KERN_CAP_LOWER.finditer(staged):
        changes.append(("kerning", match.group(0), match.group(1) + match.group(2)))
    staged = _KERN_CAP_LOWER.sub(r"\1\2", staged)
    for match in _KERN_BEFORE_PUNCT.finditer(staged):
        changes.append(("kerning", match.group(0), match.group(1) + match.group(2)))

    return normalize_resume_text(raw), changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft ground-truth text from a resume PDF.")
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    if not args.pdf.is_file():
        print(f"no such file: {args.pdf}", file=sys.stderr)
        return 1

    raw = extract_raw(args.pdf)
    text, changes = clean(raw)

    out_txt = args.pdf.with_suffix(".expected.txt")
    out_review = args.pdf.with_suffix(".review.md")
    out_txt.write_text(text, encoding="utf-8")

    grouped: dict[str, list[tuple[str, str]]] = {}
    for rule, before, after in changes:
        grouped.setdefault(rule, []).append((before, after))

    lines = [
        f"# Extraction review — `{args.pdf.name}`",
        "",
        "Draft ground truth: `" + out_txt.name + "`",
        "",
        f"- raw extracted: {len(raw)} chars, {len(raw.splitlines())} lines",
        f"- after cleanup: {len(text)} chars, {len(text.splitlines())} lines",
        "",
        "Check each substitution below, then correct the .txt by hand where",
        "needed. The corrected file is the fixture `resume_parser` (T016) must",
        "reproduce, so anything wrong here becomes a wrong test.",
        "",
    ]
    for rule, pairs in grouped.items():
        lines.append(f"## {rule} ({len(pairs)})")
        lines.append("")
        seen: set[tuple[str, str]] = set()
        for before, after in pairs:
            if (before, after) in seen:
                continue
            seen.add((before, after))
            lines.append(f"- `{before}` -> `{after}`")
        lines.append("")
    out_review.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {out_txt}")
    print(f"wrote {out_review}  ({len(changes)} substitutions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
