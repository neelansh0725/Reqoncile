"""Local embedding pipeline (T020-T021, FR5).

Runs `sentence-transformers` on the machine — no API, no cost, no rate limit.
That matters here beyond price: the Gemini free tier's per-minute cap is the
binding constraint on the rest of the pipeline (see `docs/providers.md`), so
keeping embeddings local means resume indexing never competes with
classification for quota.

The model is loaded lazily and cached for the process. Loading is expensive
(hundreds of ms plus a one-time download), and the classification fan-out
touches retrieval once per requirement, so a per-call load would dominate the
end-to-end budget (NFR1).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Sequence

from config import settings
from schemas import ResumeChunk

if TYPE_CHECKING:  # keep the heavy import out of module import time
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model_cache: dict[str, "SentenceTransformer"] = {}
_load_lock = threading.Lock()

# Vectors are L2-normalised at encode time, so cosine similarity reduces to a
# dot product and ranking is identical under either metric. This makes the
# retrieval ranking independent of how the vector store is configured.
_NORMALIZE = True


class EmbeddingError(RuntimeError):
    """Raised when the embedding model cannot be loaded or applied."""


def get_embedding_model(model_name: str | None = None) -> "SentenceTransformer":
    """Return the cached embedding model, loading it on first use.

    Double-checked locking: retrieval may be called concurrently once
    classification fans out (T034), and two threads racing to load the same
    model would double the memory and the startup cost.
    """
    name = model_name or settings.embedding_model

    model = _model_cache.get(name)
    if model is not None:
        return model

    with _load_lock:
        model = _model_cache.get(name)
        if model is not None:
            return model

        logger.info("loading embedding model %s", name)
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(name)
        except Exception as exc:  # noqa: BLE001 - surface a usable message
            raise EmbeddingError(
                f"could not load embedding model {name!r}: {exc}\n"
                "First use downloads it (~90MB); check network access, or set "
                "REQONCILE_EMBEDDING_MODEL to a model already on disk."
            ) from exc

        _model_cache[name] = model
        return model


def embedding_dimension(model_name: str | None = None) -> int:
    """Vector width for the configured model. Used when creating a collection."""
    model = get_embedding_model(model_name)
    # Renamed in sentence-transformers 5.x; keep the old name as a fallback so
    # a pinned-back install still works.
    getter = getattr(model, "get_embedding_dimension", None) or getattr(
        model, "get_sentence_embedding_dimension"
    )
    return int(getter())


def embed_texts(
    texts: Sequence[str],
    model_name: str | None = None,
    batch_size: int = 32,
) -> list[list[float]]:
    """Embed a sequence of strings in one batched pass (T021).

    Batched rather than per-text: a resume produces a few dozen chunks, and
    encoding them together is several times faster than one call each.
    """
    if not texts:
        return []
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise EmbeddingError("cannot embed empty or non-string text")

    model = get_embedding_model(model_name)
    try:
        vectors = model.encode(
            list(texts),
            batch_size=batch_size,
            normalize_embeddings=_NORMALIZE,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingError(f"embedding failed: {exc}") from exc

    return [vector.tolist() for vector in vectors]


def embed_chunks(
    chunks: Sequence[ResumeChunk],
    model_name: str | None = None,
    batch_size: int = 32,
) -> tuple[list[str], list[list[float]]]:
    """Embed resume chunks, returning ids aligned index-for-index to vectors.

    Returning the ids alongside — rather than a bare vector list — makes the
    alignment explicit at the call site. A silent off-by-one here would
    attach every rewrite suggestion to the wrong resume line (FR11).
    """
    if not chunks:
        return [], []

    ids = [chunk.chunk_id for chunk in chunks]
    vectors = embed_texts([chunk.text for chunk in chunks], model_name, batch_size)

    if len(ids) != len(vectors):
        raise EmbeddingError(
            f"embedding count mismatch: {len(ids)} chunks -> {len(vectors)} vectors"
        )
    return ids, vectors


def embed_query(text: str, model_name: str | None = None) -> list[float]:
    """Embed a single requirement string for retrieval (FR6)."""
    return embed_texts([text], model_name)[0]
