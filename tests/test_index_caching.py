"""Re-indexing the same resume must not re-embed it.

Embedding dominates a run -- 94s of a 106s request on the deployed host -- and
multi-JD comparison indexes the *same* resume once per JD. Paying that twice
made /compare unusable on a free-tier box.

These tests use a stub collection so they stay offline: the behaviour under
test is which chunks get handed to the embedder, not what the embedder returns.
"""

from __future__ import annotations

import pytest

import retrieval.vector_store as vs
from schemas import ResumeChunk, Section


def chunk(cid: str, text: str = "some resume line with enough characters") -> ResumeChunk:
    return ResumeChunk(chunk_id=cid, text=text, section=Section.EXPERIENCE,
                       source_line_no=1)


class StubCollection:
    """Minimal stand-in for a Chroma collection."""

    def __init__(self, existing=(), raises=False):
        self.existing = set(existing)
        self.raises = raises
        self.upserted = []

    def get(self, ids, include=None):
        if self.raises:
            raise RuntimeError("collection unavailable")
        return {"ids": [i for i in ids if i in self.existing]}

    def upsert(self, ids, embeddings, documents, metadatas):
        self.upserted.extend(ids)


@pytest.fixture
def embedded(monkeypatch):
    """Record exactly which chunks reach the embedder."""
    calls: list[list[str]] = []

    def fake_embed(chunks, *a, **k):
        ids = [c.chunk_id for c in chunks]
        calls.append(ids)
        return ids, [[0.0] * 4 for _ in ids]

    monkeypatch.setattr(vs, "embed_chunks", fake_embed)
    return calls


class TestSkipsAlreadyIndexed:
    def test_nothing_is_embedded_when_every_chunk_is_present(self, embedded):
        chunks = [chunk("a"), chunk("b")]
        col = StubCollection(existing={"a", "b"})
        assert vs.upsert_chunks(col, chunks) == 0
        assert embedded == [], "re-embedded chunks the collection already held"
        assert col.upserted == []

    def test_only_the_new_chunks_are_embedded(self, embedded):
        chunks = [chunk("a"), chunk("b"), chunk("c")]
        col = StubCollection(existing={"a"})
        assert vs.upsert_chunks(col, chunks) == 2
        assert embedded == [["b", "c"]]
        assert col.upserted == ["b", "c"]

    def test_a_cold_collection_embeds_everything(self, embedded):
        chunks = [chunk("a"), chunk("b")]
        col = StubCollection()
        assert vs.upsert_chunks(col, chunks) == 2
        assert embedded == [["a", "b"]]

    def test_empty_input_is_a_no_op(self, embedded):
        assert vs.upsert_chunks(StubCollection(), []) == 0
        assert embedded == []


class TestFailureFallsBackToCorrectness:
    def test_unreadable_collection_re_embeds_rather_than_skipping(self, embedded):
        """Being slow beats being wrong.

        If existing ids cannot be read we must not assume "already there" --
        that would leave the collection missing vectors and silently degrade
        retrieval. Fall back to the old behaviour instead.
        """
        chunks = [chunk("a"), chunk("b")]
        col = StubCollection(existing={"a", "b"}, raises=True)
        assert vs.upsert_chunks(col, chunks) == 2
        assert embedded == [["a", "b"]]
