"""The only interface a future team model must implement."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from promptguard.common.schema import Candidate, Prediction


class Predictor(Protocol):
    def predict(self, candidates: Sequence[Candidate], task_context: dict[str, Any]) -> list[Prediction]: ...
