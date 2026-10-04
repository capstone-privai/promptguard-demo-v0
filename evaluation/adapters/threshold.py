from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from promptguard.common.schema import Candidate, Prediction
from promptguard.decision.base import Predictor


class ThresholdPredictor:
    """Re-decide each action as MASK iff confidence >= threshold; confidence is kept as is."""

    def __init__(self, base: Predictor, threshold: float):
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be a number in [0, 1], got {threshold!r}")
        self.base = base
        self.threshold = float(threshold)

    def predict(self, candidates: Sequence[Candidate], task_context: dict[str, Any]) -> list[Prediction]:
        predictions = self.base.predict(candidates, task_context)
        by_id: dict[str, Prediction] = {}
        for prediction in predictions:
            if prediction.candidate_id in by_id:
                raise ValueError(f"duplicate prediction for {prediction.candidate_id}")
            by_id[prediction.candidate_id] = prediction
        expected = [candidate.candidate_id for candidate in candidates]
        if set(by_id) != set(expected) or len(predictions) != len(expected):
            raise ValueError("predictor must return exactly one prediction per candidate")
        return [
            replace(by_id[candidate_id], action="MASK" if by_id[candidate_id].confidence >= self.threshold else "KEEP")
            for candidate_id in expected
        ]
