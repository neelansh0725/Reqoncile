"""Append-only JSONL run logger.

This is the substrate for FR16 (reasoning trace): the classifier writes its
retrieved chunks, prompt, raw model output, and final label here under one
`run_id`, and the UI reads a slice of it back. One JSON object per line, so a
run can be reconstructed with a grep.

Concurrency matters -- classification fans out across requirements (T034), so
several threads append during a single run. Writes are guarded by a process
lock and opened in append mode; each record is written as a single `write()`
of one line, which the OS keeps intact for the small records we emit.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings

_write_lock = threading.Lock()


# The exact shape `new_run_id` produces: run_YYYYMMDDTHHMMSS_<8 hex>.
# Defined beside the generator so the two cannot drift, and exported so the
# API can reject anything else before it reaches a lookup.
RUN_ID_PATTERN = r"^run_\d{8}T\d{6}_[0-9a-f]{8}$"
RUN_ID_RE = re.compile(RUN_ID_PATTERN)


def new_run_id() -> str:
    """Short, sortable-enough id for one end-to-end pipeline run."""
    return f"run_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"


def is_valid_run_id(value: str) -> bool:
    """True only for ids this module could have minted.

    `read_run` currently opens one fixed log file and matches `run_id` as a
    field, so a malformed id is a miss rather than a traversal. This exists so
    that stays true: if the log is ever sharded per run (an obvious
    optimisation once the file grows), an unvalidated id would become a path
    component, and the check would have to be remembered at that moment
    instead of already being here.
    """
    # `fullmatch`, not `match`. Python's `$` also matches immediately before a
    # trailing newline, so `re.match(r"...$", "run_...\n")` succeeds -- a test
    # caught exactly that. `fullmatch` requires the whole string, newline
    # included, to be consumed by the pattern.
    return bool(RUN_ID_RE.fullmatch(value or ""))


def _default(obj: Any) -> Any:
    """Make the usual suspects serialisable: Pydantic models, Paths, sets."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return repr(obj)


def log_event(
    run_id: str,
    stage: str,
    payload: dict[str, Any] | None = None,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one event. Never raises -- logging must not break a run.

    `stage` is the coarse pipeline step ("jd_parse", "classify", "rewrite").
    """
    record = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "payload": payload or {},
    }
    path = log_path or settings.log_path

    try:
        line = json.dumps(record, default=_default, ensure_ascii=False) + "\n"
    except (TypeError, ValueError):
        line = json.dumps(
            {
                "run_id": run_id,
                "timestamp": record["timestamp"],
                "stage": stage,
                "payload": {"_serialisation_error": repr(payload)[:2000]},
            }
        ) + "\n"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            # O_APPEND so concurrent writers never overwrite each other.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
    except OSError:
        # A broken log must not take the run down with it (NFR3).
        pass


def read_run(run_id: str, log_path: Path | None = None) -> list[dict[str, Any]]:
    """Return every event for one run, in write order.

    Used by the reasoning-trace view (FR16) and the eval harness.
    """
    path = log_path or settings.log_path
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a torn final line
            if record.get("run_id") == run_id:
                events.append(record)
    return events
