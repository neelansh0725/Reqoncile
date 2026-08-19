"""Run-id validation.

`run_id` is user-controlled input used to read a file. These tests pin the
constraint that it must match the exact format run ids actually take, and that
nothing malformed reaches a path.
"""

from __future__ import annotations

import pytest

from logging_utils import is_valid_run_id, new_run_id


class TestRunIdValidation:
    def test_a_freshly_minted_id_validates(self):
        assert is_valid_run_id(new_run_id())

    @pytest.mark.parametrize("bad", [
        "",
        None,
        "not-a-run-id",
        "run_20260816T211407",                 # missing suffix
        "run_20260816T211407_faef393",         # suffix too short
        "run_20260816T211407_faef3935extra",
        "../../etc/passwd",
        "run_20260816T211407_faef3935/../../etc/passwd",
        "../run_20260816T211407_faef3935",
    ])
    def test_malformed_ids_are_rejected(self, bad):
        assert not is_valid_run_id(bad)

    def test_trailing_newline_does_not_slip_through(self):
        # Regression: Python's `$` also matches before a trailing newline, so
        # `re.match(r"...$", value)` accepted this. `fullmatch` does not.
        assert not is_valid_run_id("run_20260816T211407_faef3935\n")

    def test_embedded_newline_is_rejected(self):
        assert not is_valid_run_id("run_20260816T211407_faef3935\nrm -rf /")
