"""Score one item: gold span coverage and edit/gold overlap, in original-text coordinates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from evaluation.dataset.schema import GoldSpan
from evaluation.scorer.edits import Edit, verify


class SpanStatus(str, Enum):
    FULL = "full"  # every character masked
    PARTIAL = "partial"  # some characters masked
    MISSED = "missed"  # no character masked


@dataclass(frozen=True)
class GoldResult:
    item_id: str
    start: int
    end: int
    type: str
    status: SpanStatus
    exposed_chars: int  # characters left unmasked


@dataclass(frozen=True)
class EditResult:
    item_id: str
    start: int
    end: int
    overlaps_gold: bool


@dataclass(frozen=True)
class ItemScore:
    item_id: str
    channel: str
    gold_results: list[GoldResult]
    edit_results: list[EditResult]


def _union(edits: Sequence[Edit]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for edit in edits:  # sorted by start
        if merged and edit.start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], edit.end))
        else:
            merged.append((edit.start, edit.end))
    return merged


def _covered(start: int, end: int, merged: Sequence[tuple[int, int]]) -> int:
    return sum(max(0, min(end, right) - max(start, left)) for left, right in merged)


def score_item(
    item_id: str,
    channel: str,
    original: str,
    output: str,
    edits: Sequence[Edit],
    gold: Sequence[GoldSpan],
) -> ItemScore:
    """Verify the edits against the output, then judge each gold span and each edit.

    Replacement text is never inspected, so a placeholder that happens to share characters
    with the secret cannot affect the result.
    """
    ordered = verify(original, output, edits)
    merged = _union(ordered)
    gold_results: list[GoldResult] = []
    for span in sorted(gold, key=lambda span: (span.start, span.end)):
        length = span.end - span.start
        covered = _covered(span.start, span.end, merged)
        status = SpanStatus.FULL if covered == length else SpanStatus.MISSED if covered == 0 else SpanStatus.PARTIAL
        gold_results.append(GoldResult(item_id, span.start, span.end, span.type, status, length - covered))
    edit_results = [
        EditResult(item_id, edit.start, edit.end, any(edit.start < span.end and span.start < edit.end for span in gold))
        for edit in ordered
    ]
    return ItemScore(item_id, channel, gold_results, edit_results)
