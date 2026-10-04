from __future__ import annotations

import unittest

from evaluation.dataset.schema import Item, Session
from evaluation.report.aggregate import aggregate, count_lines, f2_score, percentile
from evaluation.scorer.span_scoring import EditResult, GoldResult, ItemScore, SpanStatus


def _gold(item_id: str, start: int, end: int, status: SpanStatus, exposed: int, kind: str = "PASSWORD") -> GoldResult:
    return GoldResult(item_id, start, end, kind, status, exposed)


class AggregateTests(unittest.TestCase):
    def setUp(self) -> None:
        # 4 items, 10 lines in total.
        self.sessions = [
            Session("s1", [Item("a", "t0", "stdout", "x\n" * 4), Item("b", "t0", "prompt", "one line")], []),
            Session("s2", [Item("c", "t0", "stderr", "y\n" * 3), Item("d", "t0", "stdout", "z\nz")], []),
        ]
        self.scores = [
            ItemScore("a", "stdout", [_gold("a", 0, 10, SpanStatus.FULL, 0), _gold("a", 20, 30, SpanStatus.PARTIAL, 4)],
                      [EditResult("a", 0, 10, True), EditResult("a", 20, 26, True), EditResult("a", 40, 45, False)]),
            ItemScore("b", "prompt", [_gold("b", 0, 5, SpanStatus.MISSED, 5, "TOKEN")], []),
            ItemScore("c", "stderr", [_gold("c", 0, 5, SpanStatus.FULL, 0, "TOKEN")], [EditResult("c", 0, 5, True)]),
            ItemScore("d", "stdout", [], [EditResult("d", 0, 1, False)]),
        ]
        self.elapsed = {"a": 2.0, "b": None, "c": 4.0, "d": 10.0}

    def test_metric_values(self) -> None:
        metrics = aggregate(self.sessions, self.scores, self.elapsed)
        self.assertEqual(metrics["lines_total"], 10)
        self.assertEqual(metrics["recall"], 2 / 4)
        self.assertEqual(metrics["precision"], 3 / 5)
        self.assertAlmostEqual(metrics["f2"], 5 * 0.6 * 0.5 / (4 * 0.6 + 0.5))
        self.assertEqual(metrics["char_recall"], (30 - 9) / 30)
        self.assertEqual(metrics["partial_rate"], 1 / 4)
        self.assertEqual(metrics["missed_rate"], 1 / 4)
        self.assertEqual(metrics["fp_per_1k_lines"], 2 / 10 * 1000)
        self.assertEqual(metrics["density_per_1k_lines"], 4 / 10 * 1000)
        self.assertEqual(metrics["counts"], {
            "gold_total": 4, "full": 2, "partial": 1, "missed": 1, "edits_total": 5, "edits_tp": 3,
            "edits_fp": 2, "gold_chars_total": 30, "exposed_chars_total": 9,
        })
        self.assertEqual(metrics["composition"]["by_type"]["PASSWORD"], 2)
        self.assertEqual(metrics["composition"]["by_channel"]["prompt"], 1)
        self.assertEqual(metrics["recall_by_type"]["PASSWORD"], 0.5)
        self.assertEqual(metrics["recall_by_type"]["TOKEN"], 0.5)
        self.assertIsNone(metrics["recall_by_type"]["PRIVATE_KEY"])
        self.assertEqual(metrics["recall_by_channel"]["prompt"], 0.0)
        self.assertEqual(metrics["recall_by_channel"]["stderr"], 1.0)
        self.assertIsNone(metrics["recall_by_channel"]["agents_md"])
        self.assertEqual((metrics["sessions"], metrics["items"]), (2, 4))

    def test_empty_gold_and_edits_give_none(self) -> None:
        sessions = [Session("s", [Item("a", "t0", "stdout", "")], [])]
        metrics = aggregate(sessions, [ItemScore("a", "stdout", [], [])], {"a": None})
        for key in ("recall", "precision", "f2", "char_recall", "partial_rate", "missed_rate",
                    "fp_per_1k_lines", "density_per_1k_lines"):
            self.assertIsNone(metrics[key], key)

    def test_f2_edge_cases(self) -> None:
        self.assertEqual(f2_score(0.0, 0.0), 0.0)
        self.assertIsNone(f2_score(None, 1.0))
        self.assertIsNone(f2_score(1.0, None))
        self.assertEqual(f2_score(1.0, 1.0), 1.0)

    def test_count_lines(self) -> None:
        self.assertEqual(count_lines(""), 0)
        self.assertEqual(count_lines("a"), 1)
        self.assertEqual(count_lines("a\n"), 1)
        self.assertEqual(count_lines("a\nb"), 2)
        self.assertEqual(count_lines("a\r\nb\r\n"), 2)
        self.assertEqual(count_lines("\n\n"), 2)

    def test_latency(self) -> None:
        latency = aggregate(self.sessions, self.scores, self.elapsed)["latency_ms"]
        self.assertEqual(latency["n"], 3)
        self.assertEqual(latency["p50"], 4.0)
        self.assertAlmostEqual(latency["p95"], 4.0 + (10.0 - 4.0) * 0.9)
        self.assertEqual(latency["max"], 10.0)
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 0.5), 2.5)
        none = aggregate(self.sessions, self.scores, {key: None for key in self.elapsed})["latency_ms"]
        self.assertEqual(none, {"p50": None, "p95": None, "max": None, "n": 0})


if __name__ == "__main__":
    unittest.main()
