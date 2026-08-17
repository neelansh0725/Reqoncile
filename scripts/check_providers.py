#!/usr/bin/env python
"""Preflight both model tiers before a long run.

    ./.venv/bin/python scripts/check_providers.py
    ./.venv/bin/python scripts/check_providers.py --live

Reports, per tier: which provider/model is configured, whether the credential
or daemon is reachable, and whether the configured model actually exists on
that account. With --live it makes one real structured call per tier, which is
the acceptance check for the LLM wrapper (TODO T004).

Exists because free-tier model IDs and availability move around -- guessing a
model name fails at call time, deep inside a run, rather than here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from config import PROVIDER_GOOGLE, PROVIDER_OLLAMA, settings  # noqa: E402
from llm_client import (  # noqa: E402
    GENERATION,
    REASONING,
    LLMCallError,
    LLMConfigurationError,
    complete_structured,
)

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "


class _Smoke(BaseModel):
    """Trivial schema for the live structured-output check."""

    color: str = Field(description="The colour named in the question.")
    count: int = Field(description="The number named in the question.")


def _list_google_models() -> tuple[list[str], str | None]:
    if not settings.google_api_key:
        return [], "GOOGLE_API_KEY not set"
    try:
        from google import genai

        client = genai.Client(api_key=settings.google_api_key)
        names = []
        for model in client.models.list():
            name = getattr(model, "name", "") or ""
            actions = getattr(model, "supported_actions", None) or []
            # Keep only models usable for chat completion.
            if not actions or "generateContent" in actions:
                names.append(name.removeprefix("models/"))
        return sorted(names), None
    except Exception as exc:  # noqa: BLE001 - preflight reports, never raises
        return [], f"{type(exc).__name__}: {exc}"


def _list_ollama_models() -> tuple[list[str], str | None]:
    try:
        import ollama

        client = ollama.Client(host=settings.ollama_base_url)
        response = client.list()
        models = getattr(response, "models", None) or response.get("models", [])
        names = []
        for entry in models:
            name = getattr(entry, "model", None) or (
                entry.get("model") if isinstance(entry, dict) else None
            )
            if name:
                names.append(name)
        return sorted(names), None
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def _model_matches(configured: str, available: list[str]) -> bool:
    """Ollama reports 'llama3:8b'; a bare 'llama3' should still match."""
    if configured in available:
        return True
    return any(a.split(":")[0] == configured.split(":")[0] for a in available)


def check_tier(tier_name: str) -> bool:
    tier = settings.tier(tier_name)
    print(f"\n[{tier.name}] provider={tier.provider} model={tier.model}")

    if tier.provider == PROVIDER_GOOGLE:
        available, error = _list_google_models()
        hint = "https://aistudio.google.com/apikey"
    elif tier.provider == PROVIDER_OLLAMA:
        available, error = _list_ollama_models()
        hint = f"is Ollama running at {settings.ollama_base_url}?"
    else:
        print(f"[{WARN}] no preflight for provider {tier.provider!r}; skipping")
        return True

    if error:
        print(f"[{BAD}] cannot reach provider: {error}")
        print(f"         -> {hint}")
        return False

    print(f"[{OK}] provider reachable, {len(available)} model(s) available")

    if _model_matches(tier.model, available):
        if tier.provider == PROVIDER_GOOGLE:
            # Being listed is NOT proof of being callable: withdrawn models
            # still appear in models.list() but 404 on generateContent, and a
            # model with no free quota lists fine then 429s. Only --live tells
            # you the truth.
            print(f"[{OK}] configured model {tier.model!r} is listed")
            print(f"[{WARN}] listing != callable -- confirm with --live")
        else:
            print(f"[{OK}] configured model {tier.model!r} is available")
        return True

    print(f"[{BAD}] configured model {tier.model!r} NOT found")
    if tier.provider == PROVIDER_OLLAMA:
        print(f"         -> ollama pull {tier.model}")
    preview = [m for m in available if "embed" not in m.lower()][:12]
    print("         available:", ", ".join(preview) or "(none)")
    return False


def live_check(tier_name: str) -> bool:
    print(f"\n[{tier_name}] live structured call...")
    try:
        result = complete_structured(
            _Smoke,
            user="I have 7 blue marbles. What colour are they, and how many?",
            system="Answer using the provided schema.",
            tier=tier_name,
        )
    except (LLMCallError, LLMConfigurationError) as exc:
        print(f"[{BAD}] {exc}")
        return False

    correct = result.color.strip().lower() == "blue" and result.count == 7
    marker = OK if correct else WARN
    print(f"[{marker}] returned validated {type(result).__name__}: {result.model_dump()}")
    if not correct:
        print("         (schema honoured but content wrong -- model is weak at extraction)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight Reqoncile model tiers.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Also make one real structured call per tier (T004 acceptance check).",
    )
    args = parser.parse_args()

    print("Reqoncile provider preflight")
    print("=" * 60)

    results = [check_tier(REASONING), check_tier(GENERATION)]

    if args.live:
        print("\n" + "=" * 60)
        results += [live_check(REASONING), live_check(GENERATION)]

    print("\n" + "=" * 60)
    if all(results):
        print("All checks passed.")
        return 0
    print("Some checks failed -- see above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
