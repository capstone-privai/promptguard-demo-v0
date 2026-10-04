from __future__ import annotations

import unittest

from evaluation.dataset.schema import GoldSpan
from evaluation.scorer.edits import Edit, VerificationError, apply_edits
from evaluation.scorer.span_scoring import SpanStatus, score_item


def _score(text: str, edits: list[Edit], gold: list[tuple[int, int]]):
    spans = [GoldSpan("i", start, end, "TOKEN") for start, end in gold]
    return score_item("i", "stdout", text, apply_edits(text, edits), edits, spans)


class SpanScoringTests(unittest.TestCase):
    LONG = "API_TOKEN=eiwoevndksfleifwjdskfdnslvmeiwl\nLOG=debug"

    def test_full_partial_missed(self) -> None:
        self.assertEqual(self.LONG[10:41], "eiwoevndksfleifwjdskfdnslvmeiwl")
        full = _score(self.LONG, [Edit(10, 41, "[API_1]")], [(10, 41)]).gold_results[0]
        self.assertEqual((full.status, full.exposed_chars), (SpanStatus.FULL, 0))
        partial = _score(self.LONG, [Edit(10, 31, "[API_1]")], [(10, 41)]).gold_results[0]
        self.assertEqual((partial.status, partial.exposed_chars), (SpanStatus.PARTIAL, 10))
        missed = _score(self.LONG, [], [(10, 41)]).gold_results[0]
        self.assertEqual((missed.status, missed.exposed_chars), (SpanStatus.MISSED, 31))

    def test_extra_edit_outside_gold_is_not_overlapping(self) -> None:
        debug = self.LONG.index("debug")
        score = _score(self.LONG, [Edit(10, 41, "[API_1]"), Edit(debug, debug + 5, "[X_1]")], [(10, 41)])
        self.assertEqual(score.gold_results[0].status, SpanStatus.FULL)
        self.assertEqual([result.overlaps_gold for result in score.edit_results], [True, False])

    def test_replacement_content_is_ignored(self) -> None:
        text = "API_TOKEN=zq7API9x1mk\nLOG=debug"
        score = _score(text, [Edit(10, 21, "[API_1]")], [(10, 21)])
        self.assertEqual(score.gold_results[0].status, SpanStatus.FULL)

    def test_wider_edit_is_full_and_overlapping(self) -> None:
        score = _score(self.LONG, [Edit(0, 41, "[LINE]")], [(10, 41)])
        self.assertEqual(score.gold_results[0].status, SpanStatus.FULL)
        self.assertEqual([result.overlaps_gold for result in score.edit_results], [True])

    def test_split_adjacent_edits_cover_gold(self) -> None:
        score = _score(self.LONG, [Edit(10, 25, "[A]"), Edit(25, 41, "[B]")], [(10, 41)])
        self.assertEqual(score.gold_results[0].status, SpanStatus.FULL)
        self.assertEqual([result.overlaps_gold for result in score.edit_results], [True, True])

    def test_one_edit_covers_two_adjacent_gold_spans(self) -> None:
        score = _score(self.LONG, [Edit(10, 41, "[A]")], [(10, 25), (25, 41)])
        self.assertEqual([result.status for result in score.gold_results], [SpanStatus.FULL, SpanStatus.FULL])
        self.assertEqual([result.overlaps_gold for result in score.edit_results], [True])

    def test_unicode_offsets_are_code_points(self) -> None:
        text = "설정 🔑 비밀번호=Δpässwörd9 끝"
        start = text.index("Δ")
        end = start + len("Δpässwörd9")
        score = _score(text, [Edit(start, end, "[P]")], [(start, end)])
        self.assertEqual(score.gold_results[0].status, SpanStatus.FULL)
        partial = _score(text, [Edit(start + 1, end, "[P]")], [(start, end)]).gold_results[0]
        self.assertEqual((partial.status, partial.exposed_chars), (SpanStatus.PARTIAL, 1))

    def test_crlf_offsets(self) -> None:
        text = "A=1\r\nDB_PASSWORD=qwerty7788\r\nB=2\r\n"
        start = text.index("qwerty7788")
        score = _score(text, [Edit(start, start + 10, "[P]")], [(start, start + 10)])
        self.assertEqual(score.gold_results[0].status, SpanStatus.FULL)

    def test_verification_runs_first(self) -> None:
        with self.assertRaises(VerificationError):
            score_item("i", "stdout", "key=abc", "key=abc", [Edit(4, 7, "[K]")], [GoldSpan("i", 4, 7, "SECRET")])


if __name__ == "__main__":
    unittest.main()
