"""Threshold sweeps and the summary metrics derived from them (PR-AUC, precision at fixed recall)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

from evaluation.adapters.base import SystemUnderTest
from evaluation.dataset.schema import Session
from evaluation.run import RunResult, evaluate_sessions

RECALL_TARGETS = (0.95, 0.99)


def parse_range(spec: str) -> list[float]:
    """Parse START:STOP:STEP into an inclusive list of thresholds, e.g. 0:1:0.25 → [0, .25, .5, .75, 1]."""
    try:
        start, stop, step = (float(part) for part in spec.split(":"))
    except ValueError:
        raise ValueError(f"sweep must be START:STOP:STEP, got {spec!r}") from None
    if not all(math.isfinite(value) for value in (start, stop, step)) or step <= 0 or start > stop:
        raise ValueError(f"sweep needs finite values, STEP > 0 and START <= STOP, got {spec!r}")
    count = math.floor((stop - start) / step + 1e-9) + 1
    return [round(start + index * step, 10) for index in range(count)]


def run_thresholds(
    sessions: list[Session],
    thresholds: Sequence[float | None],
    make_adapter: Callable[[float | None], SystemUnderTest],
) -> list[tuple[float | None, RunResult]]:
    """Run the whole dataset once per threshold. Detection reruns every time; optimize only if needed."""
    return [(threshold, evaluate_sessions(sessions, make_adapter(threshold))) for threshold in thresholds]


def curve_points(results: Sequence[tuple[float | None, RunResult]]) -> list[dict[str, Any]]:
    return [
        {
            "threshold": threshold,
            "precision": result.metrics["precision"],
            "recall": result.metrics["recall"],
            "f2": result.metrics["f2"],
            "fp_per_1k_lines": result.metrics["fp_per_1k_lines"],
        }
        for threshold, result in results
    ]


def _distinct_by_recall(points: Sequence[dict[str, Any]]) -> list[tuple[float, float]]:
    """(recall, best precision at that recall), ignoring points without precision or recall."""
    best: dict[float, float] = {}
    for point in points:
        precision, recall = point["precision"], point["recall"]
        if precision is None or recall is None:
            continue
        best[recall] = max(precision, best.get(recall, precision))
    return sorted(best.items())


def pr_auc(points: Sequence[dict[str, Any]]) -> float | None:
    """Step-wise area: sum of precision × recall increase, starting from recall 0.

    Points sharing a recall keep their highest precision. Fewer than two distinct points → None.
    """
    distinct = _distinct_by_recall(points)
    if len(distinct) < 2:
        return None
    area, previous = 0.0, 0.0
    for recall, precision in distinct:
        area += precision * (recall - previous)
        previous = recall
    return area


def precision_at_recall(points: Sequence[dict[str, Any]], targets: Sequence[float] = RECALL_TARGETS) -> dict[str, Any]:
    """Highest precision among points with recall >= target, and its threshold (higher wins ties)."""
    enough = len(_distinct_by_recall(points)) >= 2
    summary: dict[str, Any] = {}
    for target in targets:
        eligible = [p for p in points if p["precision"] is not None and p["recall"] is not None and p["recall"] >= target]
        if not enough or not eligible:
            summary[str(target)] = None
            continue
        best = max(eligible, key=lambda p: (p["precision"], p["threshold"] if p["threshold"] is not None else -1.0))
        summary[str(target)] = {"precision": best["precision"], "threshold": best["threshold"], "recall": best["recall"]}
    return summary


def summarize(points: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"pr_auc": pr_auc(points), "precision_at_recall": precision_at_recall(points)}
