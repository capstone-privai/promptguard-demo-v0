"""Canonical span, line, and context calculations shared by dataset and runtime.

Offsets are Python string (Unicode code point) offsets into the original text.  Text is
never normalized and only ``\n`` is treated as a line separator, so CRLF retains the
``\r`` in line text and Unicode line-separator characters do not change line numbers.
"""

from __future__ import annotations

from typing import Any


def split_lines(chunk: str) -> list[dict[str, Any]]:
    """Return 1-based line records, splitting only on LF and retaining CR."""
    records: list[dict[str, Any]] = []
    start = 0
    number = 1
    while True:
        newline = chunk.find("\n", start)
        end = len(chunk) if newline < 0 else newline
        records.append({"number": number, "start": start, "end": end, "text": chunk[start:end]})
        if newline < 0:
            return records
        start = newline + 1
        number += 1


def _nonempty_pieces(text: str) -> list[str]:
    return [piece for piece in text.split("\n") if piece != ""]


def locate(chunk: str, start: int, end: int, *, chars_each_side: int = 1000) -> dict[str, Any]:
    """Build a location for a non-empty candidate at ``chunk[start:end]``."""
    if not (0 <= start < end <= len(chunk)):
        raise ValueError("candidate span must be a non-empty range inside chunk")
    return _from_span(chunk, start, end, chars_each_side)


def build_location(chunk: str, start: int, end: int, *, chars_each_side: int = 1000) -> dict[str, Any]:
    """Build a candidate location, or a line-granularity location when start == end.

    For line-granularity records, ``start`` and ``end`` are 1-based line numbers.
    This mirrors the dataset helper's established contract.
    """
    if start != end:
        return locate(chunk, start, end, chars_each_side=chars_each_side)
    lines = split_lines(chunk)
    if not (1 <= start <= len(lines)):
        raise ValueError("line number outside chunk")
    record = lines[start - 1]
    text = record["text"]
    cropped = len(text) > chars_each_side * 2
    shown = text[: chars_each_side * 2] if cropped else text
    before = [] if cropped else [line["text"] for line in lines[max(0, start - 1 - chars_each_side) : start - 1]]
    after = [] if cropped else [line["text"] for line in lines[start : min(len(lines), start + chars_each_side)]]
    return {
        "value": None,
        "span": None,
        "line": {"first": start, "last": start, "text": shown, "value_start": None, "value_end": None},
        "context": {
            "before": before,
            "after": after,
            "before_truncated": start > 1 and (cropped or len(before) < start - 1),
            "after_truncated": start < len(lines) and (cropped or len(after) < len(lines) - start),
        },
        "line_crop_offset": 0,
    }


def _from_span(chunk: str, start: int, end: int, chars_each_side: int) -> dict[str, Any]:
    lines = split_lines(chunk)
    first_index = next(i for i, line in enumerate(lines) if line["start"] <= start <= line["end"])
    last_pos = max(start, end - 1)
    last_index = next(i for i, line in enumerate(lines) if line["start"] <= last_pos <= line["end"])
    logical_start = lines[first_index]["start"]
    logical_end = lines[last_index]["end"]
    crop_start = max(logical_start, start - chars_each_side)
    crop_end = min(logical_end, end + chars_each_side)
    line_text = chunk[crop_start:crop_end]

    window_start = max(0, start - chars_each_side)
    window_end = min(len(chunk), end + chars_each_side)
    before_region = chunk[window_start:crop_start]
    after_region = chunk[crop_end:window_end]
    before = _nonempty_pieces(before_region.rstrip("\n"))
    after = _nonempty_pieces(after_region.lstrip("\n"))
    return {
        "value": chunk[start:end],
        "span": {"start": start, "end": end},
        "line": {
            "first": first_index + 1,
            "last": last_index + 1,
            "text": line_text,
            "value_start": start - crop_start,
            "value_end": end - crop_start,
        },
        "context": {
            "before": before,
            "after": after,
            "before_truncated": window_start > 0,
            "after_truncated": window_end < len(chunk),
        },
        "line_crop_offset": crop_start - logical_start,
    }


def window_text(record: dict[str, Any]) -> str:
    """Reconstruct the visible context window for a record."""
    parts = [*record["context"].get("before", []), record["line"]["text"], *record["context"].get("after", [])]
    return "\n".join(parts)


def check_span(chunk: str, record: dict[str, Any]) -> list[str]:
    """Return human-readable validation errors without mutating the record."""
    errors: list[str] = []
    span = record.get("span")
    value = record.get("value")
    if span is not None:
        start, end = span.get("start"), span.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or chunk[start:end] != value:
            errors.append("chunk[span] != value")
        line = record.get("line", {})
        vs, ve = line.get("value_start"), line.get("value_end")
        if not isinstance(vs, int) or not isinstance(ve, int) or line.get("text", "")[vs:ve] != value:
            errors.append("line[value_span] != value")
    visible = window_text(record)
    if visible and visible not in chunk:
        errors.append("context가 원문의 연속 구간과 다름")
    return errors
