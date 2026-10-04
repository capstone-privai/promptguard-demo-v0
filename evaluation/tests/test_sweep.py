from __future__ import annotations

import unittest
from pathlib import Path

from evaluation.adapters.promptguard_adapter import PromptGuardAdapter
from evaluation.dataset.io import load_sessions
from evaluation.report.sweep import curve_points, parse_range, pr_auc, precision_at_recall, run_thresholds, summarize
from promptguard.common.schema import Prediction

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


def _point(threshold: float, precision: float | None, recall: float | None) -> dict:
    return {"threshold": threshold, "precision": precision, "recall": recall, "f2": None, "fp_per_1k_lines": None}


class GradedPredictor:
    """Low confidence for the repeated `mysecret123`, high for everything else."""

    def predict(self, candidates, task_context):
        return [Prediction(c.candidate_id, "MASK", 0.3 if c.text == "mysecret123" else 0.8) for c in candidates]


class SweepTests(unittest.TestCase):
    def test_parse_range(self) -> None:
        self.assertEqual(parse_range("0:1:0.25"), [0.0, 0.25, 0.5, 0.75, 1.0])
        self.assertEqual(parse_range("0:1:0.1")[-1], 1.0)
        self.assertEqual(len(parse_range("0:1:0.1")), 11)
        for bad in ("0:1", "a:b:c", "0:1:0", "1:0:0.1", "0:inf:0.1"):
            with self.subTest(bad), self.assertRaises(ValueError):
                parse_range(bad)

    def test_pr_auc_is_stepwise_sum_from_zero_recall(self) -> None:
        points = [_point(0.9, 1.0, 0.2), _point(0.5, 0.8, 0.6), _point(0.1, 0.5, 1.0), _point(0.0, None, None)]
        self.assertAlmostEqual(pr_auc(points), 1.0 * 0.2 + 0.8 * 0.4 + 0.5 * 0.4)

    def test_equal_recall_keeps_best_precision(self) -> None:
        points = [_point(0.9, 1.0, 0.5), _point(0.7, 0.6, 0.5), _point(0.1, 0.5, 1.0)]
        self.assertAlmostEqual(pr_auc(points), 1.0 * 0.5 + 0.5 * 0.5)

    def test_precision_at_recall(self) -> None:
        points = [_point(0.9, 0.9, 0.9), _point(0.5, 0.8, 0.96), _point(0.3, 0.85, 0.97), _point(0.1, 0.5, 1.0)]
        result = precision_at_recall(points)
        self.assertEqual(result["0.95"], {"precision": 0.85, "threshold": 0.3, "recall": 0.97})
        self.assertEqual(result["0.99"], {"precision": 0.5, "threshold": 0.1, "recall": 1.0})
        self.assertIsNone(precision_at_recall(points[:1] + [_point(0.8, 0.95, 0.5)])["0.95"])

    def test_single_point_gives_none(self) -> None:
        same = [_point(t, 0.9, 1.0) for t in (0.0, 0.5, 1.0)]
        self.assertEqual(summarize(same), {"pr_auc": None, "precision_at_recall": {"0.95": None, "0.99": None}})

    def test_recall_falls_as_threshold_rises(self) -> None:
        sessions = load_sessions(FIXTURE)
        results = run_thresholds(sessions, [0.0, 0.5, 0.9],
                                 lambda threshold: PromptGuardAdapter(GradedPredictor(), threshold=threshold))
        recalls = [point["recall"] for point in curve_points(results)]
        self.assertEqual(recalls, sorted(recalls, reverse=True))
        self.assertGreater(recalls[0], recalls[1])
        self.assertEqual(recalls[2], 0.0)
        self.assertIsNotNone(summarize(curve_points(results))["pr_auc"])


if __name__ == "__main__":
    unittest.main()
