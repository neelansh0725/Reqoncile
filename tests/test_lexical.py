"""BM25 tokenisation, including the D6 concurrency regression."""

from __future__ import annotations

import concurrent.futures as cf
import re
from pathlib import Path

from retrieval.lexical import stem, tokenize


class TestStemming:
    def test_collapses_the_pair_a_hand_rolled_stemmer_could_not(self):
        # The reason snowballstemmer is a dependency at all.
        assert stem("orchestration") == stem("orchestrated")

    def test_does_not_over_stem_distinct_technical_terms(self):
        assert stem("java") != stem("javascript")
        assert stem("docker") != stem("dock")

    def test_stopwords_and_single_chars_are_dropped(self):
        assert "experience" not in tokenize("experience with a X")


class TestD6ThreadSafety:
    """D6: one shared Snowball instance corrupted under concurrent use.

    Classification fans out across threads and every requirement tokenises,
    so this path is genuinely concurrent. The bug surfaced as an IndexError
    from inside the stemmer and errored a real requirement mid-run.

    **This test needs a large, varied vocabulary to be worth anything.** An
    earlier version used 15 distinct words and passed even with the bug
    deliberately reintroduced — it was false confidence. The corpus below is
    the tracked sample JDs (~1100 distinct tokens), which was verified to
    fail with the bug restored and pass with the fix in place.
    """

    @staticmethod
    def _corpus() -> list[str]:
        jd_dir = Path(__file__).resolve().parent.parent / "test_data" / "sample_jds"
        text = "\n".join(
            p.read_text(errors="ignore") for p in sorted(jd_dir.glob("*.txt"))
        )
        return sorted({t for t in re.findall(r"[a-z]+", text.lower()) if len(t) > 1})

    def test_corpus_is_varied_enough_to_be_a_real_test(self):
        # Guards the guard: if the sample JDs shrink, the concurrency test
        # below silently stops exercising the bug.
        assert len(self._corpus()) > 800

    def test_concurrent_stemming_does_not_corrupt_shared_state(self):
        words = self._corpus()

        def hammer(_):
            failures = 0
            for _ in range(10):
                for word in words:
                    try:
                        stem(word)
                    except Exception:
                        failures += 1
            return failures

        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(hammer, range(8))) == 0

    def test_concurrent_results_match_single_threaded_results(self):
        words = self._corpus()
        expected = [stem(w) for w in words]
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for got in pool.map(lambda _: [stem(w) for w in words], range(4)):
                assert got == expected
