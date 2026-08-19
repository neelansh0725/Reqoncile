"""Central configuration for Reqoncile.

Every default is chosen so the module imports and runs with no environment
set. Provider credentials are read lazily, at call time, not at import.

Model selection is organised into two **tiers** rather than one model per
task, so the cost/quality split is a two-line config change:

* `reasoning`  -- the classification step (FR7-FR9) and JD extraction (FR2).
  Structured output quality is load-bearing here. Hosted (Gemini free tier).
* `generation` -- rewrite suggestions (FR10) and interview-prep questions
  (FR21-FR23). These rephrase content that is already retrieved and grounded,
  so a smaller local model is adequate. Local (Ollama), permanently free.

Swapping a tier to a different provider means changing that tier's
`*_PROVIDER` and `*_MODEL` env vars; no code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")

# Providers the LLM client knows how to build.
PROVIDER_GOOGLE = "google"
PROVIDER_OLLAMA = "ollama"
PROVIDER_ANTHROPIC = "anthropic"
SUPPORTED_PROVIDERS = (PROVIDER_GOOGLE, PROVIDER_OLLAMA, PROVIDER_ANTHROPIC)


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class TierConfig:
    """One model tier: which provider, which model, how it is sampled."""

    name: str
    provider: str
    model: str
    temperature: float

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"tier {self.name!r}: unknown provider {self.provider!r}; "
                f"expected one of {', '.join(SUPPORTED_PROVIDERS)}"
            )


@dataclass(frozen=True)
class Settings:
    reasoning: TierConfig
    generation: TierConfig

    llm_timeout_s: float
    llm_max_retries: int
    llm_max_concurrency: int
    llm_max_tokens: int
    # Client-side pace limit, requests per minute per model. The Gemini free
    # tier rejects excess requests outright rather than queueing them, so
    # without this a fan-out burns requirements as 429s instead of running
    # slower. 0 disables (local providers have no limit).
    llm_requests_per_minute: int

    ollama_base_url: str

    embedding_model: str
    top_k: int
    chunk_min_chars: int

    chroma_path: Path
    log_path: Path
    usage_path: Path
    test_data_dir: Path

    def tier(self, name: str) -> TierConfig:
        try:
            value = getattr(self, name)
        except AttributeError:
            value = None
        if not isinstance(value, TierConfig):
            raise ValueError(
                f"unknown tier {name!r}; expected 'reasoning' or 'generation'"
            )
        return value

    @property
    def google_api_key(self) -> str | None:
        """Read live so tests can patch the env.

        GOOGLE_API_KEY is what langchain-google-genai looks for; GEMINI_API_KEY
        is accepted too since AI Studio labels it that way in places.
        """
        return (
            os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or None
        )

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY") or None


settings = Settings(
    # Hosted free tier. Chosen on measured quota, not preference -- see
    # docs/providers.md. The full Flash models are capped at *20 requests per
    # day*, which one JD run exhausts, so they are unusable here regardless of
    # quality. The -flash-lite models carry 15 req/min and a far larger daily
    # allowance, and scored 75% on the labelled eval set (T036).
    reasoning=TierConfig(
        name="reasoning",
        provider=_env_str("REQONCILE_REASONING_PROVIDER", PROVIDER_GOOGLE),
        model=_env_str("REQONCILE_REASONING_MODEL", "gemini-3.5-flash-lite"),
        # Deterministic: classification and structured extraction should not
        # vary run to run, which also makes the eval harness (T036) meaningful.
        temperature=_env_float("REQONCILE_REASONING_TEMPERATURE", 0.0),
    ),
    # Local, permanently free. Only ever rephrases text already retrieved from
    # the resume, so a 7-8B model is a reasonable fit.
    generation=TierConfig(
        name="generation",
        provider=_env_str("REQONCILE_GENERATION_PROVIDER", PROVIDER_OLLAMA),
        model=_env_str("REQONCILE_GENERATION_MODEL", "llama3:8b"),
        # Low but non-zero: rewrites read less stilted, and the no-fabrication
        # constraint is enforced by the grounding check (T043), not by sampling.
        temperature=_env_float("REQONCILE_GENERATION_TEMPERATURE", 0.2),
    ),
    llm_timeout_s=_env_float("REQONCILE_LLM_TIMEOUT_S", 90.0),
    llm_max_retries=_env_int("REQONCILE_LLM_MAX_RETRIES", 3),
    # Free-tier Gemini enforces a requests-per-minute cap. This is the main
    # lever if classification starts hitting 429s -- see docs/providers.md.
    llm_max_concurrency=_env_int("REQONCILE_LLM_MAX_CONCURRENCY", 4),
    llm_max_tokens=_env_int("REQONCILE_LLM_MAX_TOKENS", 4096),
    # Measured: gemini-3.5-flash-lite allows 15 req/min. Full Flash models
    # allow 5/min AND only 20/day -- see docs/providers.md.
    llm_requests_per_minute=_env_int("REQONCILE_LLM_RPM", 15),
    ollama_base_url=_env_str("OLLAMA_BASE_URL", "http://localhost:11434"),
    # T038 measured MiniLM-L6, mpnet-base and bge-base against 7
    # human-identified evidence chunks: strict top-5 recall is 4/7 for all
    # three. bge only appears better under a lenient hit criterion; it trades
    # one case for another rather than winning. With quality equal, the
    # smallest and fastest-loading model wins. The real fix for the remaining
    # 3 misses is lexical retrieval (T026a), not a bigger dense model.
    embedding_model=_env_str(
        "REQONCILE_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    ),
    top_k=_env_int("REQONCILE_TOP_K", 5),
    chunk_min_chars=_env_int("REQONCILE_CHUNK_MIN_CHARS", 25),
    chroma_path=_env_path("REQONCILE_CHROMA_PATH", PROJECT_ROOT / ".chroma"),
    log_path=_env_path("REQONCILE_LOG_PATH", PROJECT_ROOT / "logs" / "runs.jsonl"),
    usage_path=_env_path("REQONCILE_USAGE_PATH", PROJECT_ROOT / "logs" / "usage.jsonl"),
    test_data_dir=_env_path("REQONCILE_TEST_DATA_DIR", PROJECT_ROOT / "test_data"),
)
