"""Runtime candidate and prediction contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


CandidateType = Literal["PASSWORD", "TOKEN", "ACCESS_KEY", "PRIVATE_KEY", "SECRET"]
Action = Literal["KEEP", "MASK"]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    session_id: str
    turn_id: str
    operation_id: str
    type: CandidateType
    text: str
    span: dict[str, int]
    line: dict[str, Any]
    context: dict[str, Any]
    meta: dict[str, Any]
    source: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Prediction:
    candidate_id: str
    action: Action
    confidence: float  # P(candidate should be MASKed); see decision/base.py

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
