"""Deterministic Demo v0 policy; replace this module with real inference later."""

from __future__ import annotations

from typing import Any, Sequence

from promptguard.common.schema import Candidate, Prediction


class MockPredictor:
    def predict(self, candidates: Sequence[Candidate], task_context: dict[str, Any]) -> list[Prediction]:
        del task_context  # Interface-compatible; Demo v0 deliberately ignores relevance.
        return [
            Prediction(
                candidate_id=candidate.candidate_id,
                action="MASK" if candidate.type in {"PASSWORD", "TOKEN"} else "KEEP",
                confidence=1.0,
            )
            for candidate in candidates
        ]
