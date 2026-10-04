"""Wire dataset → adapter → scorer → aggregation. Shared by the CLI and threshold sweeps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.adapters.base import ItemOutput, SystemUnderTest
from evaluation.dataset.io import load_sessions
from evaluation.dataset.schema import Session
from evaluation.dataset.validate import ValidationIssue, validate_dataset
from evaluation.report.aggregate import aggregate
from evaluation.scorer.edits import EditError, VerificationError
from evaluation.scorer.span_scoring import ItemScore, score_item


class DatasetInvalidError(Exception):
    def __init__(self, issues: list[ValidationIssue]):
        super().__init__(f"dataset has {len(issues)} validation issue(s)")
        self.issues = issues


class ScoringError(Exception):
    """An adapter's output could not be scored. No partial metrics are produced."""

    def __init__(self, session_id: str, item_id: str | None, reason: str):
        super().__init__(f"session={session_id} item={item_id or '-'}: {reason}")
        self.session_id = session_id
        self.item_id = item_id
        self.reason = reason


@dataclass(frozen=True)
class RunResult:
    system: dict[str, Any]
    sessions: list[Session]
    outputs: dict[str, ItemOutput]
    scores: list[ItemScore]
    metrics: dict[str, Any]


def load_dataset(path: str | Path) -> list[Session]:
    issues = validate_dataset(path)
    if issues:
        raise DatasetInvalidError(issues)
    return load_sessions(path)


def evaluate_sessions(sessions: list[Session], adapter: SystemUnderTest) -> RunResult:
    outputs: dict[str, ItemOutput] = {}
    scores: list[ItemScore] = []
    for session in sessions:
        produced = adapter.run_session(session)
        expected = [item.item_id for item in session.items]
        if set(produced) != set(expected):
            stray = sorted(set(produced) ^ set(expected))
            raise ScoringError(session.session_id, stray[0], "adapter output does not cover exactly the session's items")
        for item in session.items:
            output = produced[item.item_id]
            try:
                scores.append(score_item(item.item_id, item.channel, item.text, output.text, output.edits,
                                         session.gold_for(item.item_id)))
            except (EditError, VerificationError) as exc:
                raise ScoringError(session.session_id, item.item_id, str(exc)) from exc
            outputs[item.item_id] = output
    elapsed = {item_id: output.elapsed_ms for item_id, output in outputs.items()}
    return RunResult(adapter.describe(), sessions, outputs, scores, aggregate(sessions, scores, elapsed))


def evaluate(dataset_path: str | Path, adapter: SystemUnderTest) -> RunResult:
    return evaluate_sessions(load_dataset(dataset_path), adapter)
