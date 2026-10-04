"""Metric 1 aggregation. Inputs are scores and the dataset; never candidates or predictions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from evaluation.dataset.schema import CHANNELS, GOLD_TYPES, Session
from evaluation.scorer.span_scoring import ItemScore, SpanStatus


def count_lines(text: str) -> int:
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def f2_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision == 0 and recall == 0:
        return 0.0
    return 5 * precision * recall / (4 * precision + recall)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default method)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_summary(elapsed_ms: Mapping[str, float | None]) -> dict[str, float | int | None]:
    values = [value for value in elapsed_ms.values() if value is not None]
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
        "n": len(values),
    }


def aggregate(
    sessions: Sequence[Session],
    scores: Sequence[ItemScore],
    elapsed_ms: Mapping[str, float | None],
) -> dict[str, Any]:
    gold = [(score.channel, result) for score in scores for result in score.gold_results]
    edits = [result for score in scores for result in score.edit_results]
    lines_total = sum(count_lines(item.text) for session in sessions for item in session.items)

    statuses = [result.status for _channel, result in gold]
    full = statuses.count(SpanStatus.FULL)
    partial = statuses.count(SpanStatus.PARTIAL)
    missed = statuses.count(SpanStatus.MISSED)
    edits_tp = sum(1 for result in edits if result.overlaps_gold)
    edits_fp = len(edits) - edits_tp
    gold_chars = sum(result.end - result.start for _channel, result in gold)
    exposed_chars = sum(result.exposed_chars for _channel, result in gold)

    recall = ratio(full, len(gold))
    precision = ratio(edits_tp, len(edits))

    def recall_where(predicate) -> float | None:
        selected = [result for channel, result in gold if predicate(channel, result)]
        return ratio(sum(1 for result in selected if result.status is SpanStatus.FULL), len(selected))

    return {
        "recall": recall,
        "precision": precision,
        "f2": f2_score(precision, recall),
        "char_recall": ratio(gold_chars - exposed_chars, gold_chars),
        "partial_rate": ratio(partial, len(gold)),
        "missed_rate": ratio(missed, len(gold)),
        "fp_per_1k_lines": None if not lines_total else edits_fp / lines_total * 1000,
        "counts": {
            "gold_total": len(gold),
            "full": full,
            "partial": partial,
            "missed": missed,
            "edits_total": len(edits),
            "edits_tp": edits_tp,
            "edits_fp": edits_fp,
            "gold_chars_total": gold_chars,
            "exposed_chars_total": exposed_chars,
        },
        "latency_ms": latency_summary(elapsed_ms),
        "density_per_1k_lines": None if not lines_total else len(gold) / lines_total * 1000,
        "lines_total": lines_total,
        "composition": {
            "by_type": {kind: sum(1 for _c, result in gold if result.type == kind) for kind in GOLD_TYPES},
            "by_channel": {name: sum(1 for channel, _r in gold if channel == name) for name in CHANNELS},
        },
        "recall_by_type": {kind: recall_where(lambda _c, result, kind=kind: result.type == kind) for kind in GOLD_TYPES},
        "recall_by_channel": {name: recall_where(lambda channel, _r, name=name: channel == name) for name in CHANNELS},
        "sessions": len(sessions),
        "items": sum(len(session.items) for session in sessions),
    }
