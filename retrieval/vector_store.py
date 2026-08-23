"""Chroma vector store and retrieval (T022-T024, FR6).

One collection per resume *version*, named by a hash of its normalised text.
That isolation is what makes version diffing (FR24-FR27) work: two resume
versions live in separate collections, so retrieval for v1 can never leak a
chunk that only exists in v2, and re-indexing an unchanged resume is a no-op
that reuses the existing collection.

Embeddings are computed by `retrieval.embed` and passed in explicitly rather
than letting Chroma call an embedding function. Keeping one embedding path
means the vectors stored at index time and the vector used at query time are
produced by identical code — a mismatch there would silently degrade every
retrieval.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TYPE_CHECKING, Sequence

from config import settings
from retrieval.embed import embed_chunks, embed_query
from retrieval.lexical import BM25Index
from schemas import ResumeChunk, RetrievedChunk, Section

if TYPE_CHECKING:
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)

_client = None

# BM25 indexes, keyed by (collection name, chunk count).
_bm25_cache: dict[tuple[str, int], BM25Index] = {}
_bm25_lock = threading.Lock()

# Cosine, to match the L2-normalised vectors from `embed`. Ranking would be
# the same under L2 given normalisation, but stating it keeps the stored
# distance interpretable as `1 - similarity`.
_COLLECTION_METADATA = {"hnsw:space": "cosine"}


class VectorStoreError(RuntimeError):
    """Raised when the store cannot be reached or a write fails."""


def resume_collection_name(text: str, embedding_model: str | None = None) -> str:
    """Stable collection name for one resume version *and* embedding model.

    Derived from content, so re-indexing the same resume hits the same
    collection and a changed resume gets a fresh one automatically.

    The embedding model is part of the key because vectors from different
    models are not comparable, and often not even the same width. Keying on
    the resume alone means switching models leaves a stale collection that
    either errors ("expecting dimension 384, got 768") or -- far worse, if the
    widths happen to match -- silently returns nonsense rankings. Including
    the model makes a switch produce a fresh, correct collection instead.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    model = embedding_model or settings.embedding_model
    model_tag = hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]
    return f"resume_{digest}_{model_tag}"


def get_client():
    """Return the cached persistent Chroma client."""
    global _client
    if _client is None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            settings.chroma_path.mkdir(parents=True, exist_ok=True)
            _client = chromadb.PersistentClient(
                path=str(settings.chroma_path),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreError(
                f"could not open Chroma at {settings.chroma_path}: {exc}"
            ) from exc
    return _client


def get_or_create_collection(name: str) -> "Collection":
    try:
        return get_client().get_or_create_collection(
            name=name, metadata=_COLLECTION_METADATA
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"could not open collection {name!r}: {exc}") from exc


def upsert_chunks(
    collection: "Collection",
    chunks: Sequence[ResumeChunk],
) -> int:
    """Write chunks and their vectors into the collection (T023).

    Idempotent by `chunk_id`: upserting the same resume twice leaves the
    collection size unchanged, because chunk ids are content-derived (T019)
    and Chroma's upsert replaces by id.

    **Chunks already present are not re-embedded.** Idempotent used to mean
    "the same result", not "the same cost": embedding ran again every time and
    was simply overwritten. That is the dominant cost of a run -- 94s of a
    106s request on the deployed host -- and multi-JD comparison indexed the
    *same* resume once per JD, paying it twice for nothing.

    This is safe precisely because ids are content-derived: an id already in
    the collection denotes byte-identical text, so its stored vector is the
    one this call would have recomputed. Collections are keyed by embedding
    model too (`resume_collection_name`), so a model change cannot silently
    reuse incomparable vectors.

    Returns the number of chunks written, which is now the number *embedded*
    rather than the number supplied.
    """
    if not chunks:
        return 0

    fresh = _without_already_indexed(collection, chunks)
    if not fresh:
        logger.debug("all %d chunks already indexed; nothing to embed", len(chunks))
        return 0
    chunks = fresh

    ids, vectors = embed_chunks(chunks)
    try:
        collection.upsert(
            ids=ids,
            embeddings=vectors,
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {
                    "section": chunk.section.value,
                    "source_line_no": chunk.source_line_no,
                }
                for chunk in chunks
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"upsert failed: {exc}") from exc

    return len(ids)


def _without_already_indexed(
    collection: "Collection",
    chunks: Sequence[ResumeChunk],
) -> list[ResumeChunk]:
    """Drop chunks whose ids the collection already holds.

    A failure to read back existing ids is not fatal: fall back to embedding
    everything, which is the old behaviour. Being slow beats being wrong.
    """
    try:
        existing = set(collection.get(
            ids=[chunk.chunk_id for chunk in chunks], include=[]
        )["ids"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read existing ids, re-embedding all: %s", exc)
        return list(chunks)
    return [chunk for chunk in chunks if chunk.chunk_id not in existing]


def index_resume(text: str, chunks: Sequence[ResumeChunk]) -> "Collection":
    """Index one resume version and return its collection."""
    collection = get_or_create_collection(resume_collection_name(text))
    upsert_chunks(collection, chunks)
    return collection


def query_chunks(
    collection: "Collection",
    query_text: str,
    k: int | None = None,
    hybrid: bool = True,
    lexical_bonus: int = 2,
) -> list[RetrievedChunk]:
    """Return the top-k chunks most semantically similar to `query_text` (FR6).

    Results are ordered most-similar first. An empty list means the collection
    holds nothing — *not* that nothing matched. Retrieval always returns its
    best k; deciding that the best available evidence is still not good enough
    is the classifier's job (FR9), not a threshold here.
    """
    if k is None:
        k = settings.top_k
    if not query_text.strip():
        raise VectorStoreError("cannot retrieve for an empty requirement")

    try:
        count = collection.count()
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"could not read collection: {exc}") from exc
    if count == 0:
        return []

    # Over-fetch from each retriever so fusion has room to promote a chunk
    # that only one of them ranked well -- which is the entire point.
    depth = min(max(k * 3, k), count)

    try:
        raw = collection.query(
            query_embeddings=[embed_query(query_text)],
            n_results=depth,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:  # noqa: BLE001
        raise VectorStoreError(f"query failed: {exc}") from exc

    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    by_id: dict[str, RetrievedChunk] = {}
    for chunk_id, document, metadata, distance in zip(
        ids, documents, metadatas, distances
    ):
        metadata = metadata or {}
        by_id[chunk_id] = RetrievedChunk(
            chunk=ResumeChunk(
                chunk_id=chunk_id,
                text=document or "",
                section=Section(metadata.get("section", Section.OTHER.value)),
                source_line_no=int(metadata.get("source_line_no", 0) or 0),
            ),
            # Chroma returns cosine *distance*; invert to similarity so a
            # bigger number always means a closer match.
            similarity=round(1.0 - float(distance), 4),
        )

    dense_ranking = list(ids)
    dense_top = [by_id[i] for i in dense_ranking[:k]]

    if not hybrid:
        return dense_top

    lexical_ranking = _lexical_ranking(collection, query_text, depth, by_id)
    if not lexical_ranking:
        return dense_top

    # Lexical results are *appended*, never fused in.
    #
    # Reciprocal Rank Fusion was tried first and rejected on measurement: it
    # re-ranks, so a chunk BM25 scores highly can evict a correct dense hit.
    # Fusing rescued "Presentation skills" but dropped the Docker probe from
    # rank 4 to outside top-5; weighting the dense ranking more heavily just
    # reversed which one broke (8/8 probes, 4/7 targets vs 7/8 and 5/7).
    # There was no weight that kept both.
    #
    # Appending is strictly additive: every dense result survives, so a
    # lexical rescue can never cost a dense hit. The price is a slightly
    # larger context for the classifier, which is a much better trade than
    # silently losing evidence.
    already = {hit.chunk.chunk_id for hit in dense_top}
    extras = [
        by_id[chunk_id]
        for chunk_id in lexical_ranking
        if chunk_id not in already and chunk_id in by_id
    ][:lexical_bonus]

    return dense_top + extras


def _lexical_ranking(
    collection: "Collection",
    query_text: str,
    depth: int,
    by_id: dict[str, RetrievedChunk],
) -> list[str]:
    """BM25 ranking over the whole collection (T026a).

    Runs over *every* chunk, not just the dense hits -- a chunk the embedding
    ranked 38th is exactly the one lexical matching needs to rescue, so
    re-ranking the dense shortlist would miss the entire point.

    Chunks BM25 finds but the dense over-fetch did not are hydrated into
    `by_id` so fusion can promote them.
    """
    index = _get_bm25_index(collection)
    if index is None:
        return []

    hits = index.search(query_text, k=depth)
    if not hits:
        return []

    missing = [chunk_id for chunk_id, _ in hits if chunk_id not in by_id]
    if missing:
        try:
            fetched = collection.get(ids=missing, include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001 - lexical rescue is best-effort
            return [chunk_id for chunk_id, _ in hits if chunk_id in by_id]
        for chunk_id, document, metadata in zip(
            fetched.get("ids") or [],
            fetched.get("documents") or [],
            fetched.get("metadatas") or [],
        ):
            metadata = metadata or {}
            by_id[chunk_id] = RetrievedChunk(
                chunk=ResumeChunk(
                    chunk_id=chunk_id,
                    text=document or "",
                    section=Section(metadata.get("section", Section.OTHER.value)),
                    source_line_no=int(metadata.get("source_line_no", 0) or 0),
                ),
                # No cosine score exists for a lexical-only hit; the
                # retriever tag is what the prompt renders, not this number.
                similarity=0.0,
                retriever="lexical",
            )

    return [chunk_id for chunk_id, _ in hits if chunk_id in by_id]


def _get_bm25_index(collection: "Collection") -> BM25Index | None:
    """Build (and cache) a BM25 index over a collection's documents.

    Cached on (name, count) so it rebuilds when chunks are added, and derived
    from the collection itself rather than persisted separately -- one source
    of truth, no way for the two to drift.
    """
    try:
        count = collection.count()
    except Exception:  # noqa: BLE001
        return None
    if count == 0:
        return None

    key = (collection.name, count)
    with _bm25_lock:
        cached = _bm25_cache.get(key)
        if cached is not None:
            return cached

    try:
        everything = collection.get(include=["documents"])
    except Exception:  # noqa: BLE001
        return None

    ids = everything.get("ids") or []
    documents = everything.get("documents") or []
    if not ids:
        return None

    index = BM25Index.build(ids, [d or "" for d in documents])
    with _bm25_lock:
        _bm25_cache[key] = index
    return index
