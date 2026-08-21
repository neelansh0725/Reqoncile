"""API request validation.

Only the boundaries: what the API refuses before any model is called. No test
here runs a pipeline, so none of them cost quota.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import MAX_JDS, app


@pytest.fixture(scope="module")
def client():
    # `with` runs the lifespan, which loads the embedding model once.
    with TestClient(app) as c:
        yield c


class TestSurface:
    def test_every_documented_endpoint_exists(self):
        paths = {r.path for r in app.routes if hasattr(r, "methods")}
        assert {"/health", "/analyze", "/compare", "/diff",
                "/interview-prep/{run_id}", "/trace/{run_id}",
                "/upload-resume"} <= paths


class TestCompareValidation:
    JD = {"label": "a", "jd_text": "Python required"}

    @pytest.mark.parametrize("jds", [1, MAX_JDS + 1])
    def test_jd_count_bounds(self, client, jds):
        body = {"jds": [{"label": str(i), "jd_text": "x"} for i in range(jds)],
                "resume_text": "resume"}
        assert client.post("/compare", json=body).status_code == 422

    def test_duplicate_labels(self, client):
        body = {"jds": [self.JD, self.JD], "resume_text": "resume"}
        assert client.post("/compare", json=body).status_code == 422

    @pytest.mark.parametrize("field,value", [
        ("resume_text", "   "), ("resume_text", ""),
    ])
    def test_blank_fields(self, client, field, value):
        body = {"jds": [self.JD, {"label": "b", "jd_text": "y"}],
                "resume_text": "resume"}
        body[field] = value
        assert client.post("/compare", json=body).status_code == 422


class TestDiffValidation:
    def test_identical_versions_are_refused(self, client):
        # There is nothing to diff, and a run would cost two full pipelines.
        body = {"jd_text": "jd", "resume_before": "same", "resume_after": "same "}
        assert client.post("/diff", json=body).status_code == 422

    def test_missing_version_is_refused(self, client):
        assert client.post(
            "/diff", json={"jd_text": "jd", "resume_before": "a"}
        ).status_code == 422


class TestInterviewPrepPathSafety:
    """`run_id` reaches a file read, so the path must not be escapable."""

    @pytest.mark.parametrize("run_id,expected", [
        ("not-a-run-id", 422),
        ("run_20260816T211407_faef3935%0A", 422),      # trailing newline
        ("run_19990101T000000_deadbeef", 404),          # well-formed, absent
    ])
    def test_run_id_must_match_the_exact_format(self, client, run_id, expected):
        assert client.post(f"/interview-prep/{run_id}").status_code == expected

    @pytest.mark.parametrize("attack", [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
    ])
    def test_traversal_never_reaches_the_handler(self, client, attack):
        # Either the route does not match or the pattern rejects it; what
        # matters is that no 200 and no file read results.
        assert client.post(f"/interview-prep/{attack}").status_code in (404, 422)

    def test_limit_is_bounded(self, client):
        # Local generation is ~20s per gap; an unbounded limit hangs the call.
        rid = "run_19990101T000000_deadbeef"
        assert client.post(f"/interview-prep/{rid}?limit=99").status_code == 422
        assert client.post(f"/interview-prep/{rid}?limit=0").status_code == 422


class TestFrontendEnvHasNoSecrets:
    """Vite inlines every `VITE_*` variable into the client bundle as plain
    text, so anything declared in `frontend/.env.example` is public.

    Verified directly at the time of writing: building with
    `GOOGLE_API_KEY=<canary>` in the environment produced a bundle containing
    no trace of it, because Vite only inlines the `VITE_` prefix. This test
    guards the other half — that nobody adds a non-prefixed secret to the
    frontend env file and assumes the same protection applies.
    """

    def test_only_vite_prefixed_names_are_declared(self):
        from pathlib import Path

        env = Path(__file__).resolve().parent.parent / "frontend" / ".env.example"
        assert env.exists(), "frontend/.env.example is what keeps Vercel's " \
                             "import scan off the repo-root backend secrets"

        declared = [
            line.split("=", 1)[0].strip()
            for line in env.read_text().splitlines()
            if "=" in line and not line.strip().startswith("#")
        ]
        assert declared, "expected at least one declared variable"
        offenders = [n for n in declared if not n.startswith("VITE_")]
        assert not offenders, (
            f"non-VITE_ names in frontend/.env.example: {offenders}. "
            "These are not inlined by Vite, so putting a secret here creates a "
            "false sense of scoping — and Vercel will offer it during import."
        )
