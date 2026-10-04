from __future__ import annotations

import unittest

from evaluation.adapters.threshold import ThresholdPredictor
from promptguard.common.schema import Candidate, Prediction


def _candidate(candidate_id: str) -> Candidate:
    return Candidate(candidate_id, "s", "t", "o", "PASSWORD", "x", {"start": 0, "end": 1}, {}, {}, {}, {})


class FixedPredictor:
    def __init__(self, confidences: dict[str, float], extra: list[Prediction] | None = None):
        self.confidences = confidences
        self.extra = extra or []

    def predict(self, candidates, task_context):
        return [Prediction(c.candidate_id, "MASK", self.confidences[c.candidate_id]) for c in candidates] + self.extra


class ThresholdPredictorTests(unittest.TestCase):
    def test_boundary_is_mask_and_confidence_is_kept(self) -> None:
        candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
        predictor = ThresholdPredictor(FixedPredictor({"a": 0.5, "b": 0.4999, "c": 0.9}), 0.5)
        predictions = predictor.predict(candidates, {})
        self.assertEqual([(p.candidate_id, p.action, p.confidence) for p in predictions],
                         [("a", "MASK", 0.5), ("b", "KEEP", 0.4999), ("c", "MASK", 0.9)])

    def test_prediction_count_mismatch_raises(self) -> None:
        candidates = [_candidate("a")]
        with self.assertRaises(ValueError):
            ThresholdPredictor(FixedPredictor({"a": 1.0}, extra=[Prediction("a", "MASK", 1.0)]), 0.5).predict(candidates, {})
        with self.assertRaises(ValueError):
            ThresholdPredictor(FixedPredictor({"a": 1.0}, extra=[Prediction("z", "MASK", 1.0)]), 0.5).predict(candidates, {})

    def test_threshold_out_of_range_raises(self) -> None:
        for threshold in (-0.1, 1.1, float("nan"), True):
            with self.subTest(threshold), self.assertRaises(ValueError):
                ThresholdPredictor(FixedPredictor({}), threshold)


if __name__ == "__main__":
    unittest.main()
