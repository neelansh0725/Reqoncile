"""Resume ingestion (FR4).

Extracts a text layer from a resume PDF and normalises the artifacts that PDF
text extraction reliably introduces. Owning the normalisation here — rather
than in the draft-generation script — is deliberate: the hand-verified fixture
in `test_data/resumes/*.expected.txt` was produced by exactly this code, so any
future change to the rules shows up immediately as a diff against text a human
signed off on.

The artifacts handled are not cosmetic. Each one breaks something downstream:

* **Ligatures.** `efficiently` arrives as `e` + `ﬃ` + `ciently`, a single
  codepoint. A retrieval query for "efficiency" will not match it.
* **Icon glyphs.** FontAwesome icons land in the text layer as their names
  (`Envelope`, `Phone-Alt`), which read as content words and pollute chunks.
* **Kerning splits.** The extractor leaks a space after some capitals:
  `T ypeScript`, `SHAP ,`. `TypeScript` is exactly the kind of token a JD
  requirement matches on, so a split one is invisible to retrieval.

Line structure is preserved as-is. Merged right-aligned columns
("SRM Institute ... Ghaziabad, India") and mid-sentence wraps are how the
document is laid out, not extraction errors, and chunking (T019) needs the
real line boundaries.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from config import settings
from schemas import ResumeChunk, Section

# FontAwesome icon glyphs. On a contact line they precede the value, so they
# become readable labels rather than being deleted -- otherwise four bare
# handles are left with no way to tell which is which.
ICON_LABELS: dict[str, str] = {
    "Phone-Alt": "Phone:",
    "Envelope": "Email:",
    "LINKEDIN": "LinkedIn:",
}

# 'Github' (lowercase h) is the icon; 'GitHub' is real link text. The pair
# "Github GitHub" is icon + label, so keep just the label.
_GITHUB_PAIR = re.compile(r"\bGithub\s+GitHub\b")
_GITHUB_ICON = re.compile(r"\bGithub\b")

# Kerning after a capital leaks a space: "T ypeScript", "SHAP ,".
_KERN_CAP_LOWER = re.compile(r"\b([A-Z]) ([a-z]{2,})")
_KERN_BEFORE_PUNCT = re.compile(r"([A-Za-z0-9]) ([,.;])")

_BLANK_RUN = re.compile(r"\n{3,}")

# Icon-name substitution is scoped to contact lines. 'Envelope' and 'Phone-Alt'
# are only glyph artifacts next to an actual email/phone/handle; 'Envelope' is
# also an ordinary English word, and a resume mentioning envelope manufacturing
# must not have it rewritten to 'Email:'. Kerning repair is not scoped -- a
# stray space after a capital is never meaningful.
_CONTACT_SIGNAL = re.compile(
    r"(@[\w.-]+\.\w+)|(\+\d[\d\s()-]{6,})|(linkedin|github)\.com|(?:^|\s)\+\d{2}-\d{6,}",
    re.IGNORECASE,
)

# Not all pasted text comes from a PDF, but most of it does (people copy out of
# their own resume PDF), so artifact repair defaults on for every input.
_MAX_PATHLIKE_LEN = 400


class ResumeParseError(RuntimeError):
    """Raised when a resume cannot be read at all.

    Distinct from a degraded parse: an unreadable or image-only PDF is a
    configuration/input problem the user must fix, not something to paper over
    with an empty document.
    """


def extract_pdf_text(path: Path) -> str:
    """Return the raw concatenated text layer of a PDF, one page per block."""
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError) as exc:
        raise ResumeParseError(f"could not open {path}: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 - any failure means unreadable
            raise ResumeParseError(
                f"{path} is password-protected; supply an unencrypted copy"
            ) from exc

    pages = [page.extract_text() or "" for page in reader.pages]
    raw = "\n".join(pages)

    if not raw.strip():
        raise ResumeParseError(
            f"{path} has no extractable text layer -- it is probably a scan or "
            "image-only export. Re-export it as a text PDF."
        )
    return raw


def _repair_line(line: str) -> str:
    """Apply artifact repair to one line, scoping icon names to contact lines."""
    if _CONTACT_SIGNAL.search(line):
        for icon, label in ICON_LABELS.items():
            line = line.replace(icon, label)
        line = _GITHUB_ICON.sub("GitHub:", line)
    line = _KERN_CAP_LOWER.sub(r"\1\2", line)
    return _KERN_BEFORE_PUNCT.sub(r"\1\2", line)


def normalize_resume_text(raw: str, repair_pdf_artifacts: bool = True) -> str:
    """Normalise resume text. Pure function, no I/O.

    Order matters: NFKC runs first so later rules see plain ASCII letters
    rather than ligature codepoints.

    Set `repair_pdf_artifacts=False` for text known not to originate from a
    PDF, to skip the kerning and icon-name rules entirely.
    """
    text = unicodedata.normalize("NFKC", raw)

    if repair_pdf_artifacts:
        # The "Github GitHub" pair is icon + label and is unambiguous
        # anywhere, so it is repaired before the line-scoped pass.
        text = _GITHUB_PAIR.sub("GitHub", text)
        text = "\n".join(_repair_line(line) for line in text.split("\n"))

    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_RUN.sub("\n\n", text).strip() + "\n"


def _looks_like_path(source: str) -> bool:
    """A pasted resume is neither short nor single-line; a path is both."""
    if len(source) > _MAX_PATHLIKE_LEN or "\n" in source:
        return False
    try:
        return Path(source).expanduser().is_file()
    except OSError:
        return False


def load_resume_text(
    source: str | Path,
    repair_pdf_artifacts: bool = True,
) -> str:
    """Load and normalise a resume from a PDF, a text file, or pasted text.

    Returns normalised text in every case (FR4) -- the caller downstream
    cannot tell which input path produced it, which is what lets the API
    accept an upload and a textarea through one code path.
    """
    if isinstance(source, Path) or _looks_like_path(str(source)):
        path = Path(source).expanduser()
        if not path.is_file():
            raise ResumeParseError(f"no such file: {path}")
        if path.suffix.lower() == ".pdf":
            raw = extract_pdf_text(path)
        else:
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise ResumeParseError(f"could not read {path}: {exc}") from exc
    else:
        raw = str(source)

    if not raw.strip():
        raise ResumeParseError("resume is empty")

    text = normalize_resume_text(raw, repair_pdf_artifacts=repair_pdf_artifacts)
    if not text.strip():
        raise ResumeParseError("resume is empty after normalisation")
    return text


# --------------------------------------------------------------------------
# Section detection (T018)
# --------------------------------------------------------------------------

# Keyword -> canonical section. Matched against a normalised heading line.
# Longer, more specific phrases first so "WORK EXPERIENCE" does not match on
# a shorter, wrong key.
_SECTION_KEYWORDS: tuple[tuple[str, Section], ...] = (
    ("PROFESSIONAL EXPERIENCE", Section.EXPERIENCE),
    ("WORK EXPERIENCE", Section.EXPERIENCE),
    ("WORK HISTORY", Section.EXPERIENCE),
    ("EMPLOYMENT", Section.EXPERIENCE),
    ("INTERNSHIP", Section.EXPERIENCE),
    ("EXPERIENCE", Section.EXPERIENCE),
    ("TECHNICAL SKILLS", Section.SKILLS),
    ("CORE COMPETENCIES", Section.SKILLS),
    ("CORE SUBJECTS", Section.SKILLS),
    ("SKILLS", Section.SKILLS),
    ("EDUCATION", Section.EDUCATION),
    ("ACADEMIC", Section.EDUCATION),
    ("PERSONAL PROJECTS", Section.PROJECTS),
    ("PROJECTS", Section.PROJECTS),
    ("CERTIFICATION", Section.CERTIFICATIONS),
    ("CERTIFICATES", Section.CERTIFICATIONS),
    ("LICENSES", Section.CERTIFICATIONS),
    ("ACHIEVEMENTS", Section.ACHIEVEMENTS),
    ("ACCOMPLISHMENTS", Section.ACHIEVEMENTS),
    ("AWARDS", Section.ACHIEVEMENTS),
    ("HONORS", Section.ACHIEVEMENTS),
    ("PUBLICATIONS", Section.ACHIEVEMENTS),
    ("EXTRACURRICULAR", Section.ACTIVITIES),
    ("VOLUNTEER", Section.ACTIVITIES),
    ("ACTIVITIES", Section.ACTIVITIES),
    ("INTERESTS", Section.ACTIVITIES),
    ("HOBBIES", Section.ACTIVITIES),
    ("LANGUAGES", Section.ACTIVITIES),
    ("SUMMARY", Section.SUMMARY),
    ("OBJECTIVE", Section.SUMMARY),
    ("PROFILE", Section.SUMMARY),
)

_MAX_HEADING_CHARS = 45
_BULLET_START = re.compile(r"^\s*[-–—•*]")


@dataclass(frozen=True)
class TaggedLine:
    """One resume line with its section (T018).

    `line_no` is 1-based and indexes the normalised text, which is what
    `source_line_no` on a chunk refers to (T019 / FR11 traceability).
    """

    line_no: int
    text: str
    section: Section
    is_heading: bool


def _match_heading(line: str) -> Section | None:
    """Return the section this line introduces, or None if it is content.

    Only lines matching a known heading keyword count. Deliberately strict:
    treating any short all-caps line as a heading would classify the
    candidate's own name ("NEELANSH SINGH") as a section break. The cost of
    strictness is that an unrecognised heading folds into the previous
    section, which is a much cheaper error.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS:
        return None
    if _BULLET_START.match(stripped):
        return None
    if stripped.endswith((".", ",", ";", ":")) and stripped.count(" ") > 4:
        return None
    # A section heading does not carry dates. Without this, a role line like
    # "Volunteer June 2025 - July 2025" matches the VOLUNTEER keyword, passes
    # the Title-Case check, and silently relabels the rest of an EXPERIENCE
    # entry as ACTIVITIES.
    if any(char.isdigit() for char in stripped):
        return None

    # Headings are set apart typographically -- all caps, or Title Case with
    # no lowercase connective prose.
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return None
    is_caps = all(c.isupper() for c in letters)
    if not is_caps and not stripped.istitle():
        return None

    normalised = re.sub(r"[^A-Z& ]", " ", stripped.upper())
    normalised = " ".join(normalised.split())
    for keyword, section in _SECTION_KEYWORDS:
        if keyword in normalised:
            return section
    return None


def detect_sections(text: str) -> list[TaggedLine]:
    """Tag every line of a normalised resume with its section (T018).

    Every line gets a label -- lines before the first recognised heading are
    HEADER (the name/contact block). Blank lines inherit the current section
    so line numbering stays aligned with the source text.
    """
    tagged: list[TaggedLine] = []
    current = Section.HEADER

    for index, line in enumerate(text.split("\n"), start=1):
        heading = _match_heading(line)
        if heading is not None:
            current = heading
            tagged.append(TaggedLine(index, line, current, is_heading=True))
        else:
            tagged.append(TaggedLine(index, line, current, is_heading=False))

    return tagged


# --------------------------------------------------------------------------
# Chunking (T019)
# --------------------------------------------------------------------------

# The header block is name, phone, email, and handles. None of it can match a
# JD requirement, so it is excluded rather than left to add noise to every
# retrieval.
_NON_RETRIEVABLE_SECTIONS = frozenset({Section.HEADER})

# A self-contained labelled line: "Programming: C++, Python", "Languages:
# English (fluent)". Each is its own topic, so they must not be merged into a
# neighbouring line -- a single blob of every skill would be retrieved for
# every skill query and rank ahead of the specific bullet that actually
# evidences the skill.
_LABELLED_LINE = re.compile(r"^[A-Z][\w /&+-]{1,24}:\s")

# Cap on how many consecutive non-bullet lines fold into one chunk. Two keeps
# the pairs that belong together -- employer + job title, project name + tech
# stack, institution + degree -- without swallowing a whole section.
_MAX_MERGED_LINES = 2


def _chunk_id(section: Section, text: str, taken: set[str]) -> str:
    """Content-derived id, disambiguated on collision.

    Position is deliberately not an input: an id like `experience-3` would
    change for every later bullet the moment one is inserted above it, which
    would break FR11 traceability across resume versions.
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    base = f"{section.value}-{digest}"
    if base not in taken:
        return base
    # Genuinely identical text in the same section (rare, but a repeated
    # bullet across two roles does happen).
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def chunk_resume(
    text: str,
    min_chars: int | None = None,
) -> list[ResumeChunk]:
    """Split a normalised resume into retrievable chunks (FR5).

    Grouping rules, applied within a section:

    * A bullet starts a chunk. Following non-bullet lines are treated as
      wrapped continuation and folded in -- the PDF breaks bullets mid-sentence
      ("...through systematic query profiling and log / review."), and half a
      sentence retrieves poorly.
    * Consecutive non-bullet lines merge into one chunk, which keeps an
      employer, job title and dates together as a single unit, and a project
      title together with its tech-stack line.
    * A blank line or a heading closes the current chunk.

    Chunks shorter than `min_chars` are dropped as too small to carry meaning.
    """
    if min_chars is None:
        min_chars = settings.chunk_min_chars

    chunks: list[ResumeChunk] = []
    taken: set[str] = set()

    buffer: list[str] = []
    buffer_line_no = 0
    buffer_section = Section.HEADER
    buffer_is_bullet = False

    def flush() -> None:
        nonlocal buffer, buffer_line_no, buffer_is_bullet
        if not buffer:
            return
        joined = " ".join(part.strip() for part in buffer if part.strip())
        joined = re.sub(r"\s{2,}", " ", joined).strip()
        buffer = []
        buffer_is_bullet = False
        if len(joined) < min_chars or buffer_section in _NON_RETRIEVABLE_SECTIONS:
            return
        identifier = _chunk_id(buffer_section, joined, taken)
        taken.add(identifier)
        chunks.append(
            ResumeChunk(
                chunk_id=identifier,
                text=joined,
                section=buffer_section,
                source_line_no=buffer_line_no,
            )
        )

    for tagged in detect_sections(text):
        stripped = tagged.text.strip()

        if tagged.is_heading or not stripped:
            flush()
            buffer_section = tagged.section
            continue

        is_bullet = bool(_BULLET_START.match(stripped))
        if is_bullet:
            flush()
            buffer_section = tagged.section
            buffer_line_no = tagged.line_no
            buffer_is_bullet = True
            buffer.append(_BULLET_START.sub("", stripped, count=1).strip())
            continue

        if buffer:
            # A PDF wraps a bullet mid-sentence, so the line before a genuine
            # continuation never ends in terminal punctuation. Without this a
            # finished bullet keeps absorbing whatever follows -- in practice
            # the *next* job's employer and title lines, corrupting both.
            if buffer[-1].rstrip().endswith((".", "!", "?")):
                flush()
            # A labelled line is self-contained, and a non-bullet run has a
            # cap. Neither applies while folding continuation into a bullet.
            elif not buffer_is_bullet and (
                _LABELLED_LINE.match(stripped) or len(buffer) >= _MAX_MERGED_LINES
            ):
                flush()

        if not buffer:
            buffer_section = tagged.section
            buffer_line_no = tagged.line_no
        buffer.append(stripped)

    flush()
    return chunks
