"""The only interface a future team model must implement."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from promptguard.common.schema import Candidate, Prediction


class Predictor(Protocol):
    """Return exactly one Prediction per candidate, with the same candidate_id.

    `Prediction.confidence` is the probability, in [0, 1], that the candidate should be
    MASKed — regardless of which action was chosen. A KEEP prediction therefore carries a
    low confidence, and a MASK prediction a high one. Evaluation sweeps a threshold over
    this value to draw precision/recall curves, so it must stay calibrated in this sense.
    """

    def predict(self, candidates: Sequence[Candidate], task_context: dict[str, Any]) -> list[Prediction]: ...
