"""Hosted-call accounting.

Written after a real failure: `scripts/eval_classifier.py` classifies without
going through the pipeline, so a quota check that counted pipeline *stages*
reported 0 calls immediately after 60 real ones. Accounting now happens at the
call boundary, which fixes the whole class rather than that one script.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import llm_client
from logging_utils import read_usage, record_usage


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point the ledger at a temp file.

    `Settings` is a frozen dataclass, so the module-level binding is swapped
    for a replaced copy rather than mutated.
    """
    path = tmp_path / "usage.jsonl"
    import logging_utils
    monkeypatch.setattr(
        logging_utils, "settings",
        dataclasses.replace(logging_utils.settings, usage_path=path),
    )
    return path


class TestLedger:
    def test_roundtrip(self, ledger):
        record_usage("google", "m", "reasoning", "ok", usage_path=ledger)
        rows = read_usage(usage_path=ledger)
        assert len(rows) == 1
        assert rows[0]["provider"] == "google" and rows[0]["outcome"] == "ok"

    def test_day_filter_is_utc(self, ledger):
        record_usage("google", "m", "reasoning", "ok", usage_path=ledger)
        today = json.loads(ledger.read_text().splitlines()[0])["timestamp"][:10]
        assert len(read_usage(day=today, usage_path=ledger)) == 1
        assert read_usage(day="1999-01-01", usage_path=ledger) == []

    def test_missing_ledger_is_not_an_error(self, tmp_path):
        assert read_usage(usage_path=tmp_path / "absent.jsonl") == []

    def test_corrupt_line_is_skipped_not_fatal(self, ledger):
        record_usage("google", "m", "reasoning", "ok", usage_path=ledger)
        with ledger.open("a") as fh:
            fh.write("not json\n")
        assert len(read_usage(usage_path=ledger)) == 1

    def test_logging_failure_never_raises(self, tmp_path):
        # A broken ledger must not take a run down with it (NFR3).
        record_usage("g", "m", "t", "ok", usage_path=tmp_path / "no" / "such" / "x")


class TestRetriesAreCounted:
    """A retried request consumes quota whether or not it succeeded.

    The old stage-counting check recorded one `classify.done` per requirement,
    so a requirement that retried twice looked like one call and was actually
    three. That undercount is what this pins.
    """

    class _FlakyRunnable:
        def __init__(self, failures):
            self.failures, self.calls = failures, 0

        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls <= self.failures:
                raise ConnectionError("connection reset")
            return "ok"

    def test_each_attempt_is_recorded(self, ledger, monkeypatch):
        monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)
        runnable = self._FlakyRunnable(failures=2)

        assert llm_client._invoke_paced(runnable, [], llm_client.REASONING) == "ok"

        rows = read_usage(usage_path=ledger)
        assert runnable.calls == 3
        # Two transport faults plus the success: three quota-consuming requests.
        assert len(rows) == 3
        assert [r["outcome"] for r in rows] == [
            "transport_fault", "transport_fault", "ok",
        ]

    def test_a_permanent_failure_is_recorded_once(self, ledger, monkeypatch):
        monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)

        class Broken:
            def invoke(self, messages, **kwargs):
                raise ValueError("malformed request")

        with pytest.raises(Exception):
            llm_client._invoke_paced(Broken(), [], llm_client.REASONING)

        rows = read_usage(usage_path=ledger)
        # Fails fast rather than burning three quota calls -- the constraint
        # D1's fix was explicitly scoped to preserve.
        assert len(rows) == 1 and rows[0]["outcome"] == "error"
