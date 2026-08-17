"""Single entry point for every LLM call in Reqoncile.

Nothing else in the codebase constructs a model client. Callers name a **tier**
("reasoning" or "generation"), never a provider or a model string:

    complete_structured(Classification, user=..., tier="reasoning")
    complete(user=..., tier="generation")

That indirection is the whole point. The provider behind each tier is config
(see `config.py`), so the free-tier split -- Gemini for classification, local
Ollama for rewrites -- can be re-pointed at anything without touching a caller.

Provider differences the registry absorbs:

* credential handling -- Gemini needs an API key, Ollama needs a reachable
  local daemon and no key at all;
* sampling -- Gemini and Ollama accept `temperature`; recent Anthropic models
  reject it with a 400, so that provider is marked `supports_sampling=False`;
* failure shape -- all of them surface as `LLMCallError` so per-item error
  isolation (NFR3) has one exception type to catch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OLLAMA,
    TierConfig,
    settings,
)

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

REASONING = "reasoning"
GENERATION = "generation"


class LLMConfigurationError(RuntimeError):
    """Provider cannot be built: missing key, unreachable daemon, bad kwargs.

    Deliberately distinct from `LLMCallError` -- a misconfigured environment
    should fail loudly rather than degrade into an empty report.
    """


class LLMCallError(RuntimeError):
    """A call failed after retries. Callers isolating per-item failures
    (NFR3) catch this."""


@dataclass(frozen=True)
class ProviderSpec:
    build: Callable[[TierConfig, int], BaseChatModel]
    supports_sampling: bool
    # Human-readable setup hint, shown when the provider cannot be built.
    setup_hint: str


def _build_google(tier: TierConfig, max_tokens: int) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = settings.google_api_key
    if not api_key:
        raise LLMConfigurationError(
            f"tier {tier.name!r} uses Google Gemini but GOOGLE_API_KEY is not "
            "set. Get a free key at https://aistudio.google.com/apikey, then "
            "copy .env.example to .env and add it."
        )
    return ChatGoogleGenerativeAI(
        model=tier.model,
        google_api_key=api_key,
        temperature=tier.temperature,
        max_output_tokens=max_tokens,
        timeout=settings.llm_timeout_s,
        # 0, deliberately. The client's own retry fires immediately and does
        # NOT pass through our pace limiter, so a single limited call could
        # become several real requests and blow a 5/min quota. Retries are
        # owned by `_invoke_paced` below, which re-acquires the limiter each
        # attempt.
        max_retries=0,
    )


def _build_ollama(tier: TierConfig, max_tokens: int) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=tier.model,
        base_url=settings.ollama_base_url,
        temperature=tier.temperature,
        num_predict=max_tokens,
        client_kwargs={"timeout": settings.llm_timeout_s},
    )


def _build_anthropic(tier: TierConfig, max_tokens: int) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    api_key = settings.anthropic_api_key
    if not api_key:
        raise LLMConfigurationError(
            f"tier {tier.name!r} uses Anthropic but ANTHROPIC_API_KEY is not set."
        )
    # No temperature/top_p/top_k: rejected with a 400 on current models.
    return ChatAnthropic(
        model=tier.model,
        api_key=api_key,
        max_tokens=max_tokens,
        timeout=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
    )


_PROVIDERS: dict[str, ProviderSpec] = {
    PROVIDER_GOOGLE: ProviderSpec(
        build=_build_google,
        supports_sampling=True,
        setup_hint="Set GOOGLE_API_KEY (free key: https://aistudio.google.com/apikey).",
    ),
    PROVIDER_OLLAMA: ProviderSpec(
        build=_build_ollama,
        supports_sampling=True,
        setup_hint=(
            "Install Ollama (https://ollama.com/download), start it, then "
            "`ollama pull <model>`."
        ),
    ),
    PROVIDER_ANTHROPIC: ProviderSpec(
        build=_build_anthropic,
        supports_sampling=False,
        setup_hint="Set ANTHROPIC_API_KEY.",
    ),
}

_model_cache: dict[tuple[str, str, int], BaseChatModel] = {}


class _RateLimiter:
    """Sliding-window pace limiter, shared across threads.

    The Gemini free tier *rejects* over-quota requests rather than queueing
    them, so an unpaced fan-out converts requirements into 429s instead of
    simply running slower. Pacing client-side turns a hard failure into wall
    time, which is the trade we want: a slow complete report beats a fast
    report full of "could not assess".
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a request may be made. Returns seconds waited."""
        if self.per_minute <= 0:
            return 0.0
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self.per_minute:
                    self._calls.append(now)
                    return waited
                # +0.05 so we wake just after the oldest call ages out.
                sleep_for = 60.0 - (now - self._calls[0]) + 0.05
            time.sleep(sleep_for)
            waited += sleep_for


_rate_limiters: dict[str, _RateLimiter] = {}
_rate_limiter_lock = threading.Lock()


def get_rate_limiter(tier: str) -> _RateLimiter:
    """One limiter per model -- quotas are per model, not per project."""
    tier_config = settings.tier(tier)
    # Local providers have no server-side quota to respect.
    per_minute = (
        0 if tier_config.provider == PROVIDER_OLLAMA
        else settings.llm_requests_per_minute
    )
    key = f"{tier_config.provider}/{tier_config.model}"
    with _rate_limiter_lock:
        limiter = _rate_limiters.get(key)
        if limiter is None or limiter.per_minute != per_minute:
            limiter = _RateLimiter(per_minute)
            _rate_limiters[key] = limiter
        return limiter


def get_provider_spec(tier_name: str) -> ProviderSpec:
    tier = settings.tier(tier_name)
    spec = _PROVIDERS.get(tier.provider)
    if spec is None:
        raise LLMConfigurationError(
            f"tier {tier.name!r}: no builder for provider {tier.provider!r}"
        )
    return spec


def get_chat_model(
    tier: str = REASONING,
    max_tokens: int | None = None,
) -> BaseChatModel:
    """Return a cached chat model for a tier.

    Cached because building one per call is wasteful under the concurrent
    classification fan-out (T034).
    """
    tier_config = settings.tier(tier)
    max_tokens = max_tokens or settings.llm_max_tokens
    cache_key = (tier_config.provider, tier_config.model, max_tokens)

    if cache_key not in _model_cache:
        spec = get_provider_spec(tier)
        try:
            _model_cache[cache_key] = spec.build(tier_config, max_tokens)
        except LLMConfigurationError:
            raise
        except Exception as exc:
            raise LLMConfigurationError(
                f"could not build {tier_config.provider!r} client for tier "
                f"{tier_config.name!r} (model {tier_config.model!r}): {exc}\n"
                f"{spec.setup_hint}"
            ) from exc

    return _model_cache[cache_key]


def is_rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower()


# Exception types that mean "the connection failed", never "the request was
# wrong". Every one of these can succeed on a retry with an unchanged request,
# which is exactly what makes retrying them safe:
#
#   ConnectionError  -- ConnectionResetError (peer dropped mid-response),
#                       ConnectionAbortedError, BrokenPipeError,
#                       ConnectionRefusedError. The bytes never arrived; the
#                       server never formed an opinion about the request.
#   TimeoutError     -- socket and TLS read timeouts ("The read operation
#                       timed out"). The request may or may not have been
#                       processed, but no usable response came back.
#
# httpx's transport family is added below when available: ConnectError,
# ReadTimeout, WriteTimeout, PoolTimeout, NetworkError and RemoteProtocolError
# are the same class of fault one layer up.
_TRANSPORT_FAULTS: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)

try:  # httpx is present via the provider SDKs, but do not hard-depend on it.
    import httpx as _httpx

    # TransportError only -- deliberately NOT HTTPStatusError. A 400, 401 or
    # 403 is the server telling us the request itself is wrong; retrying it
    # cannot change the outcome and would burn three quota slots to learn the
    # same thing three times.
    _TRANSPORT_FAULTS = _TRANSPORT_FAULTS + (_httpx.TransportError,)
except Exception:  # noqa: BLE001
    pass


def transport_fault(exc: BaseException) -> str | None:
    """Name the transport fault in `exc`'s cause chain, or None.

    Walks `__cause__`/`__context__` because provider SDKs wrap socket errors
    in their own exception types -- the reset arrives as the *cause* of a
    library error, not as the error itself.

    This is an **allowlist**: anything not positively identified as a
    transport fault is not retried. That is the point. A malformed request,
    an auth failure or a validation error falls through to fail-fast without
    having to be enumerated, so a new kind of permanent error can never be
    retried by accident.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _TRANSPORT_FAULTS):
            return type(current).__name__
        current = current.__cause__ or current.__context__
    return None


def _invoke_paced(runnable: Any, messages: list[Any], tier: str, **kwargs: Any) -> Any:
    """Invoke through the pace limiter, retrying rate-limit rejections.

    Every attempt -- including retries -- takes a slot from the limiter, so the
    request rate we actually emit is the rate we promised. Backoff is
    exponential; the limiter itself supplies most of the delay.
    """
    limiter = get_rate_limiter(tier)
    attempts = max(1, settings.llm_max_retries)
    last: Exception | None = None

    for attempt in range(attempts):
        limiter.acquire()
        try:
            return runnable.invoke(messages, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            fault = transport_fault(exc)
            quota = is_rate_limited(exc)
            if not (quota or fault) or attempt == attempts - 1:
                # Not retryable, or out of attempts. Permanent failures
                # (bad request, auth, validation) land here on attempt 1.
                raise
            backoff = 2.0 * (2 ** attempt)
            logger.warning(
                "%s on %s (attempt %d/%d); backing off %.0fs",
                "rate limited" if quota else f"transport fault ({fault})",
                _describe(tier), attempt + 1, attempts, backoff,
            )
            time.sleep(backoff)

    raise last if last else RuntimeError("unreachable")


def _build_messages(system: str | None, user: str) -> list[Any]:
    messages: list[Any] = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=user))
    return messages


def _check_kwargs(tier: str, kwargs: dict[str, Any]) -> None:
    """Reject sampling kwargs on providers that 400 on them."""
    spec = get_provider_spec(tier)
    if spec.supports_sampling:
        return
    forbidden = {"temperature", "top_p", "top_k"} & kwargs.keys()
    if forbidden:
        tier_config = settings.tier(tier)
        raise LLMConfigurationError(
            f"{sorted(forbidden)} are rejected by provider "
            f"{tier_config.provider!r}. Steer with the prompt instead."
        )


def _describe(tier: str) -> str:
    tier_config = settings.tier(tier)
    return f"{tier_config.provider}/{tier_config.model} (tier={tier_config.name})"


def complete(
    user: str,
    system: str | None = None,
    tier: str = GENERATION,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> str:
    """Plain text completion. Used for the report summary (FR13)."""
    _check_kwargs(tier, kwargs)
    chat = get_chat_model(tier=tier, max_tokens=max_tokens)
    try:
        response = _invoke_paced(chat, _build_messages(system, user), tier, **kwargs)
    except Exception as exc:
        raise LLMCallError(f"text completion via {_describe(tier)} failed: {exc}") from exc

    # `.text` is a property on current langchain-core; older versions expose
    # it as a method. Prefer the property, fall back rather than warn.
    text = getattr(response, "text", None)
    if callable(text):
        text = text()
    if text is None:
        text = response.content
    if not isinstance(text, str) or not text.strip():
        raise LLMCallError(f"{_describe(tier)} returned no text content")
    return text


def complete_structured(
    schema: type[SchemaT],
    user: str,
    system: str | None = None,
    tier: str = REASONING,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> SchemaT:
    """Completion validated against a Pydantic schema.

    The workhorse: JD extraction (FR2) and per-requirement classification
    (FR7-FR9) both need a validated object rather than parsed prose.

    Note the tier default is `reasoning`. Small local models are markedly less
    reliable at schema adherence, so structured calls should stay on the
    hosted tier unless a specific schema has been tested locally.
    """
    _check_kwargs(tier, kwargs)
    chat = get_chat_model(tier=tier, max_tokens=max_tokens)
    try:
        structured = chat.with_structured_output(schema)
        result = _invoke_paced(structured, _build_messages(system, user), tier, **kwargs)
    except Exception as exc:
        raise LLMCallError(
            f"structured completion for {schema.__name__} via "
            f"{_describe(tier)} failed: {exc}"
        ) from exc

    if not isinstance(result, schema):
        raise LLMCallError(
            f"{_describe(tier)} returned {type(result).__name__}, "
            f"expected {schema.__name__}"
        )
    return result


def complete_structured_or_raw(
    schema: type[SchemaT],
    user: str,
    system: str | None = None,
    tier: str = REASONING,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> tuple[SchemaT | None, str, str | None]:
    """Like `complete_structured`, but hands back the raw text on failure.

    Returns `(parsed, raw_text, error)`. When validation fails, `parsed` is
    None and `raw_text` carries whatever the model actually emitted, so the
    caller can salvage the parts that were well-formed (T015) instead of
    losing the whole response.

    Still raises `LLMConfigurationError` -- a missing credential is not
    something to salvage around.
    """
    _check_kwargs(tier, kwargs)
    chat = get_chat_model(tier=tier, max_tokens=max_tokens)

    try:
        structured = chat.with_structured_output(schema, include_raw=True)
        envelope = _invoke_paced(structured, _build_messages(system, user), tier, **kwargs)
    except Exception as exc:
        return None, "", f"call to {_describe(tier)} failed: {exc}"

    if not isinstance(envelope, dict):
        # include_raw unsupported by this integration; treat as parsed.
        return (envelope if isinstance(envelope, schema) else None), "", None

    parsed = envelope.get("parsed")
    error = envelope.get("parsing_error")
    raw_message = envelope.get("raw")

    raw_text = ""
    if raw_message is not None:
        content = getattr(raw_message, "content", raw_message)
        if isinstance(content, str):
            raw_text = content
        elif isinstance(content, list):
            # Some providers return content as a list of typed blocks.
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    parts.append(block.get("text") or json.dumps(block))
            raw_text = "\n".join(parts)
        # Tool-call args are where structured output usually lands.
        for call in getattr(raw_message, "tool_calls", None) or []:
            args = call.get("args") if isinstance(call, dict) else None
            if args:
                raw_text = "\n".join(filter(None, [raw_text, json.dumps(args)]))

    if isinstance(parsed, schema):
        return parsed, raw_text, None
    return None, raw_text, str(error) if error else "model output failed validation"
