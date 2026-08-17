#!/usr/bin/env python
"""Ingest a resume into the vector store, optionally querying it (T025).

    ./.venv/bin/python scripts/index_resume.py test_data/resumes/<file>.pdf
    ./.venv/bin/python scripts/index_resume.py <file>.pdf --query "distributed systems"
    ./.venv/bin/python scripts/index_resume.py <file>.pdf --show-chunks

One command takes a PDF all the way to a printed top-k result: load -> chunk
-> embed -> store -> query.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsing.resume_parser import chunk_resume, load_resume_text  # noqa: E402
from retrieval.vector_store import (  # noqa: E402
    index_resume,
    query_chunks,
    resume_collection_name,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a resume and query it.")
    parser.add_argument("resume", help="Path to a resume PDF or .txt")
    parser.add_argument("--query", "-q", action="append", default=[],
                        help="Run a retrieval query (repeatable).")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--show-chunks", action="store_true",
                        help="Print every chunk that was indexed.")
    args = parser.parse_args()

    text = load_resume_text(Path(args.resume))
    chunks = chunk_resume(text)
    collection = index_resume(text, chunks)

    print(f"resume     : {args.resume}")
    print(f"collection : {resume_collection_name(text)}")
    print(f"chunks     : {len(chunks)} indexed, {collection.count()} in store")

    if args.show_chunks:
        print()
        for chunk in chunks:
            print(f"  {chunk.chunk_id:24} L{chunk.source_line_no:03d} "
                  f"[{chunk.section.value:12}] {chunk.text[:70]}")

    for query in args.query:
        print(f"\n--- query: {query!r}")
        for rank, hit in enumerate(query_chunks(collection, query, args.top_k), 1):
            print(f"  {rank}. {hit.similarity:+.3f} [{hit.chunk.section.value:11}] "
                  f"L{hit.chunk.source_line_no:03d} {hit.chunk.text[:64]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
