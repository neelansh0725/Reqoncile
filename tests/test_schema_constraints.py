"""The validators that carry the project's honesty claims (FR8, FR12, FR23).

Each test here corresponds to a sentence in the README. If one of these fails,
a claim in the README has become false.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas import (
    Classification,
    ClassificationVerdict,
    GapPrep,
    GapQuestion,
    MatchLabel,
    RankedJD,
)
from tests.conftest import G, M, W, make_classification, make_requirement


class TestEvidenceMatchesLabel:
    """README: 'A verdict must cite evidence (FR8)'."""

    def test_gap_with_evidence_is_rejected(self):
        # A gap means no retrieved chunk evidences the requirement. If one
        # does, the verdict is wrong, not the evidence.
        with pytest.raises(ValidationError, match="gap"):
            Classification(
                requirement=make_requirement("Docker"),
                label=G,
                justification="j",
                evidence_chunk_ids=["chunk-1"],
            )

    @pytest.mark.parametrize("label", [M, W])
    def test_matched_or_weak_without_evidence_is_rejected(self, label):
        with pytest.raises(ValidationError):
            Classification(
                requirement=make_requirement("Docker"),
                label=label,
                justification="j",
                evidence_chunk_ids=[],
            )

    def test_errored_must_carry_the_error(self):
        with pytest.raises(ValidationError, match="error"):
            Classification(
                requirement=make_requirement("Docker"),
                label=MatchLabel.ERRORED,
                justification="j",
            )


class TestErroredIsNotAModelVerdict:
    """README: 'A failed requirement is not a gap'."""

    def test_model_cannot_return_errored(self):
        # `errored` is a pipeline state. A model that returns it would be
        # claiming a failure it cannot know about.
        with pytest.raises(ValidationError):
            ClassificationVerdict(
                label="errored", justification="j", evidence_chunk_ids=[]
            )


class TestFR23NoSampleAnswers:
    """README: the interview-prep note describes an answer, never drafts one."""

    IMPERSONAL = (
        "Acknowledge you have not used Kubernetes in production, then describe "
        "the closest thing you have actually done."
    )

    def test_impersonal_note_is_accepted(self):
        q = GapQuestion(question="How would you approach it?",
                        answer_should_cover=self.IMPERSONAL)
        assert q.answer_should_cover.startswith("Acknowledge")

    @pytest.mark.parametrize("draft", [
        "I built a RAG pipeline at my last internship.",
        "I've worked with vector databases before.",
        "In my experience, chunking strategy matters most.",
        "We deployed it to production.",
        # The exact form llama3:8b actually produced (docs/interview_prep.md).
        "Highlight relevant skills. For example, 'In my previous role, I "
        "worked with data visualization tools to identify trends.'",
    ])
    def test_first_person_drafts_are_rejected(self, draft):
        with pytest.raises(ValidationError, match="first-person"):
            GapQuestion(question="q", answer_should_cover=draft)

    def test_second_person_is_not_tripped(self):
        # The correct register for this field. A guard that rejected it would
        # make the feature unusable.
        q = GapQuestion(
            question="Can you walk me through your experience?",
            answer_should_cover="You should explain what you understand and "
                                "where your knowledge stops.",
        )
        assert q.question

    @pytest.mark.parametrize("count", [1, 4])
    def test_question_count_is_bounded(self, count):
        # Fewer than two is not preparation; more than three is a study list.
        q = GapQuestion(question="q", answer_should_cover=self.IMPERSONAL)
        with pytest.raises(ValidationError):
            GapPrep(questions=[q] * count)


class TestRankedJD:
    def test_rank_must_be_positive(self):
        with pytest.raises(ValidationError):
            RankedJD(label="a", rank=0, reason="r")

    def test_ties_are_representable(self):
        # The feature exists because fine-grained rank is not resolvable.
        r = RankedJD(label="a", rank=1, reason="r", tied_with=["b"])
        assert r.tied_with == ["b"]


class TestRankingNoteDegeneration:
    """A runaway `overall_note` must not render, and must not take the
    ranking down with it. Observed live: 154 words of varied filler."""

    DEGENERATE = " ".join(
        ["Job 1 is a complete match with zero gaps, whereas Job 2 has gaps"]
        + "properly nicely well fine good ok yes sure alrightly indeed indeedly "
          "absolutely totally completely fully entirely overall ultimately "
          "eventually finally subsequently accordingly consequently therefore "
          "thus hence henceforth therefrom thereupon herein therein whereby "
          "wherein hereupon whither whence wherever however nevertheless "
          "nonetheless yet still instead otherwise alternately alternatively "
          "rather instead properly nicely well fine good ok yes sure".split()
    )

    def test_degenerate_note_is_dropped(self):
        from schemas import JDRanking
        assert JDRanking(overall_note=self.DEGENERATE).overall_note == ""

    def test_a_real_two_sentence_note_survives(self):
        from schemas import JDRanking
        note = ("Advantest is a much stronger fit due to substantial technical "
                "alignment. Osfin has critical gaps across core required "
                "competencies, mostly behavioural rather than technical.")
        assert JDRanking(overall_note=note).overall_note == note

    def test_the_ranking_survives_a_dropped_note(self):
        # The note is decorative; failing validation would discard a good
        # ranking over a bad sentence.
        from schemas import JDRanking
        r = JDRanking(ranked=[{"label": "a", "rank": 1, "reason": "r"}],
                      overall_note=self.DEGENERATE)
        assert len(r.ranked) == 1 and r.overall_note == ""
