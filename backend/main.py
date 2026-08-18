"""FastAPI backend (T053-T057, FR15).

Thin by design: every endpoint is a wrapper over `pipeline.run_pipeline` or a
parsing helper. No analysis logic lives here, so the CLI and the API cannot
drift apart.

Two decisions worth knowing:

* **The embedding model is loaded at startup**, not on first request. It costs
  ~8.8s once (see `docs/latency.md`); paying it during boot rather than inside
  the first user's request is the whole reason the API exists rather than
  shelling out to the CLI.
* **A partially-failed analysis still returns 200.** If some requirements
  could not be assessed, the report says so in `errored` and `warnings`
  (NFR3). Turning that into a 500 would throw away a report that is mostly
  correct and useful.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi import Path as FastPath
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from llm_client import LLMConfigurationError
from logging_utils import RUN_ID_PATTERN, is_valid_run_id, read_run
from parsing.resume_parser import ResumeParseError, load_resume_text
from pipeline import run_pipeline
from agent.comparator import MAX_JDS, compare_jds
from reporting.generate_report import (
    render_comparison_markdown,
    render_markdown,
)
from retrieval.embed import EmbeddingError, get_embedding_model
from schemas import AlignmentReport, ComparisonResult

logger = logging.getLogger(__name__)

# Generous but finite. A JD is a few KB; a resume rarely exceeds ~50KB of
# text. These exist to reject accidents, not to be tight.
MAX_JD_CHARS = 60_000
MAX_RESUME_CHARS = 200_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = time.time()
    try:
        get_embedding_model()
        logger.info("embedding model ready in %.1fs", time.time() - started)
    except EmbeddingError as exc:
        # Not fatal: /health should still answer so an operator can see why.
        logger.error("embedding model failed to load: %s", exc)
    yield


app = FastAPI(
    title="Reqoncile",
    description="Resume-to-job-description alignment reports.",
    version="1.0.0",
    lifespan=lifespan,
)

# The Vite dev server. Single-user local tool, so no auth (TechStack sec. 9).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    jd_text: str = Field(..., min_length=1, max_length=MAX_JD_CHARS)
    resume_text: str = Field(..., min_length=1, max_length=MAX_RESUME_CHARS)
    include_rewrites: bool = True
    include_summary: bool = True

    @field_validator("jd_text", "resume_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class CompareJD(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    jd_text: str = Field(..., min_length=1, max_length=MAX_JD_CHARS)

    @field_validator("label", "jd_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class CompareRequest(BaseModel):
    """Several JDs against one resume (FR17-FR20).

    Capped at MAX_JDS: each JD costs one hosted call per requirement, and the
    free tier is the binding constraint (`docs/providers.md`). Rewrites are off
    by default -- see `compare_jds`.
    """

    jds: list[CompareJD] = Field(..., min_length=2, max_length=MAX_JDS)
    resume_text: str = Field(..., min_length=1, max_length=MAX_RESUME_CHARS)
    include_rewrites: bool = False

    @field_validator("resume_text")
    @classmethod
    def _resume_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("jds")
    @classmethod
    def _unique_labels(cls, value: list[CompareJD]) -> list[CompareJD]:
        labels = [jd.label.strip() for jd in value]
        if len(set(labels)) != len(labels):
            raise ValueError("JD labels must be unique")
        return value


class CompareResponse(BaseModel):
    """Full per-JD reports plus the ranking over them.

    The reports are returned in full, not just their scores: the ranking is a
    judgement, and a caller must be able to see the findings it rests on.
    """

    result: ComparisonResult
    labels: dict[str, str] = Field(
        ..., description="run_id -> label, to join reports to ranking entries."
    )
    markdown: str
    total_seconds: float


class AnalyzeResponse(BaseModel):
    """Structured report *and* rendered text, satisfying FR14 in one call."""

    report: AlignmentReport
    markdown: str
    timings: dict[str, float]
    total_seconds: float


class UploadResumeResponse(BaseModel):
    text: str
    characters: int
    lines: int


class HealthResponse(BaseModel):
    status: str
    embedding_model_loaded: bool
    reasoning_tier: str
    generation_tier: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    from config import settings

    try:
        get_embedding_model()
        loaded = True
    except EmbeddingError:
        loaded = False

    return HealthResponse(
        status="ok" if loaded else "degraded",
        embedding_model_loaded=loaded,
        reasoning_tier=f"{settings.reasoning.provider}/{settings.reasoning.model}",
        generation_tier=f"{settings.generation.provider}/{settings.generation.model}",
    )


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Run a JD + resume to a full report (FR15).

    Returns 200 with a partial report when some requirements fail to classify;
    the caller sees them under `report.errored` and `report.warnings`.
    """
    try:
        report, timings = run_pipeline(
            request.jd_text,
            request.resume_text,
            skip_rewrites=not request.include_rewrites,
            skip_summary=not request.include_summary,
        )
    except LLMConfigurationError as exc:
        # Setup problem, not a bad request: the operator must fix a key.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("analysis failed")
        raise HTTPException(
            status_code=500, detail=f"analysis failed: {exc}"
        ) from exc

    return AnalyzeResponse(
        report=report,
        markdown=render_markdown(report),
        timings=timings.stages,
        total_seconds=timings.total,
    )


@app.post("/compare", response_model=CompareResponse)
def compare(request: CompareRequest) -> CompareResponse:
    """Rank several JDs against one resume (FR17-FR20).

    Like `/analyze`, a partial result is a 200: a JD that yields nothing
    classifiable is returned unranked with a warning, not an error.
    """
    started = time.time()
    try:
        result = compare_jds(
            [jd.jd_text for jd in request.jds],
            request.resume_text,
            labels=[jd.label.strip() for jd in request.jds],
            skip_rewrites=not request.include_rewrites,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("comparison failed")
        raise HTTPException(
            status_code=500, detail=f"comparison failed: {exc}"
        ) from exc

    labels = {
        report.run_id: jd.label.strip()
        for report, jd in zip(result.reports, request.jds)
    }
    return CompareResponse(
        result=result,
        labels=labels,
        markdown=render_comparison_markdown(result, labels),
        total_seconds=time.time() - started,
    )


class TraceStep(BaseModel):
    """One requirement's reasoning trace (FR16)."""

    requirement: str
    final_label: str
    justification: str
    retrieved: list[dict] = Field(default_factory=list)
    model_evidence: list[str] = Field(default_factory=list)
    rejected_evidence: list[str] = Field(default_factory=list)
    repaired: str | None = None


class TraceResponse(BaseModel):
    run_id: str
    steps: list[TraceStep]


@app.get("/trace/{run_id}", response_model=TraceResponse)
def trace(
    run_id: str = FastPath(
        ...,
        pattern=RUN_ID_PATTERN,
        description="Run id as minted by logging_utils.new_run_id().",
        examples=["run_20260816T211407_faef3935"],
    ),
) -> TraceResponse:
    """Return the classifier's reasoning trace for a run (FR16).

    Reads the JSONL written during classification (T033) rather than holding
    traces in memory: the log is already the durable record, and serving from
    it means what the UI shows is exactly what was written, with no second
    representation to drift.

    The retrieved excerpts are the point. `/analyze` returns similarity scores
    but not the chunk text, so a trace cannot be reconstructed from a report
    alone — which is what this endpoint is for.
    """
    # Belt and braces: the path pattern above already rejects anything
    # malformed with a 422, but validating here too means a non-HTTP caller
    # cannot bypass it.
    if not is_valid_run_id(run_id):
        raise HTTPException(status_code=400, detail=f"malformed run id {run_id!r}")

    events = read_run(run_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"no trace for run {run_id!r}")

    steps = [
        TraceStep(
            requirement=payload.get("requirement", "?"),
            final_label=payload.get("final_label", "?"),
            justification=payload.get("justification", ""),
            retrieved=payload.get("retrieved", []),
            model_evidence=payload.get("model_evidence", []),
            rejected_evidence=payload.get("rejected_evidence", []),
            repaired=payload.get("repaired"),
        )
        for event in events
        if event.get("stage") == "classify.done"
        for payload in [event.get("payload", {})]
    ]
    return TraceResponse(run_id=run_id, steps=steps)


@app.post("/upload-resume", response_model=UploadResumeResponse)
async def upload_resume(file: UploadFile = File(...)) -> UploadResumeResponse:
    """Extract text from an uploaded resume PDF (FR4).

    Returns the extracted text for the client to show and then post back to
    /analyze, rather than analysing here -- the user should be able to see and
    correct what was extracted before it is used.
    """
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file is {len(raw)} bytes; limit is {MAX_UPLOAD_BYTES}",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    suffix = (file.filename or "resume.pdf").rsplit(".", 1)[-1].lower()
    if suffix not in {"pdf", "txt", "md"}:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type {suffix!r}; upload a PDF or text file",
        )

    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as handle:
        handle.write(raw)
        temp_path = Path(handle.name)
    try:
        text = load_resume_text(temp_path)
    except ResumeParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    return UploadResumeResponse(
        text=text, characters=len(text), lines=len(text.splitlines())
    )
