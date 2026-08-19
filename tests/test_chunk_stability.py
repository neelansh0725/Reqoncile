"""Content-derived chunk IDs (T019, FR11).

README: rewrites trace to one resume line, and version diffing can tell a
moved bullet from a rewritten one. Both rest on chunk ids being derived from
the chunk's own text rather than its position.
"""

from __future__ import annotations

from parsing.resume_parser import chunk_resume

RESUME = """\
EXPERIENCE
Data Analyst Intern
- Optimized SQL queries to improve database performance.
- Built dashboards consumed by the operations team.

PROJECTS
Credit Risk System
- Designed a FastAPI application supporting real-time scoring.

SKILLS
Programming: C++, JavaScript, Python, HTML5, CSS3, SQL
"""

REORDERED = """\
PROJECTS
Credit Risk System
- Designed a FastAPI application supporting real-time scoring.

EXPERIENCE
Data Analyst Intern
- Optimized SQL queries to improve database performance.
- Built dashboards consumed by the operations team.

SKILLS
Programming: C++, JavaScript, Python, HTML5, CSS3, SQL
"""


def ids(text):
    return {c.chunk_id for c in chunk_resume(text)}


class TestStability:
    def test_ids_are_identical_across_runs(self):
        assert ids(RESUME) == ids(RESUME)

    def test_ids_survive_reordering_the_document(self):
        # A positional id would change every id after the moved block, which
        # would make every rewrite citation stale and make a diff read as if
        # the whole resume had been rewritten.
        common = ids(RESUME) & ids(REORDERED)
        assert len(common) == len(ids(RESUME))

    def test_editing_one_line_changes_only_that_id(self):
        edited = RESUME.replace(
            "Built dashboards consumed by the operations team.",
            "Built Power BI dashboards consumed by the operations team.",
        )
        before, after = ids(RESUME), ids(edited)
        assert len(before - after) == 1
        assert len(after - before) == 1

    def test_ids_carry_their_section(self):
        chunks = chunk_resume(RESUME)
        # The section prefix is what lets a reader tell a skills-list claim
        # from a demonstrated one at a glance in a trace.
        assert any(c.chunk_id.startswith("skills-") for c in chunks)
        assert any(c.chunk_id.startswith("experience-") for c in chunks)


class TestMinimumChunkSize:
    """Chunks below `chunk_min_chars` are dropped as too small to carry meaning.

    Deliberate, and worth pinning: a line shorter than the threshold is
    invisible to retrieval entirely, so a very terse skills line cannot be
    matched against any requirement.
    """

    def test_a_short_line_produces_no_chunk(self):
        assert chunk_resume("SKILLS\nProgramming: Python, SQL\n") == []

    def test_the_same_line_expanded_does_produce_one(self):
        chunks = chunk_resume(
            "SKILLS\nProgramming: C++, JavaScript, Python, HTML5, CSS3, SQL\n"
        )
        assert len(chunks) == 1
