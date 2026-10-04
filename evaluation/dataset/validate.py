"""Collect every format error in a dataset instead of stopping at the first one."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.dataset.io import iter_records
from evaluation.dataset.schema import CHANNELS, GOLD_TYPES


@dataclass(frozen=True)
class ValidationIssue:
    session_id: str | None
    item_id: str | None
    message: str

    def __str__(self) -> str:
        return f"{self.session_id or '-'} / {self.item_id or '-'} / {self.message}"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def validate_session(record: Any, *, line: int | None = None) -> list[ValidationIssue]:
    """Check one parsed session record. Cross-session uniqueness is checked by validate_dataset."""
    where = f"line {line}: " if line is not None else ""
    if not isinstance(record, dict):
        return [ValidationIssue(None, None, f"{where}session must be a JSON object")]
    session_id = record.get("session_id") if _is_id(record.get("session_id")) else None
    issues: list[ValidationIssue] = []

    def issue(item_id: str | None, message: str) -> None:
        issues.append(ValidationIssue(session_id, item_id, where + message))

    if session_id is None:
        issue(None, "missing or invalid 'session_id' (non-empty string)")
    if "meta" in record and not isinstance(record["meta"], dict):
        issue(None, "'meta' must be an object")

    texts: dict[str, str] = {}
    items = record.get("items")
    if not isinstance(items, list) or not items:
        issue(None, "missing or invalid 'items' (non-empty list)")
        items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issue(None, f"items[{index}] must be an object")
            continue
        item_id = item.get("item_id") if _is_id(item.get("item_id")) else None
        if item_id is None:
            issue(None, f"items[{index}]: missing or invalid 'item_id' (non-empty string)")
        elif item_id in texts:
            issue(item_id, "duplicate item_id")
        if not isinstance(item.get("turn_id"), str):
            issue(item_id, "missing or invalid 'turn_id' (string)")
        if item.get("channel") not in CHANNELS:
            issue(item_id, f"invalid channel; expected one of {list(CHANNELS)}")
        if not isinstance(item.get("text"), str):
            issue(item_id, "missing or invalid 'text' (string)")
        elif item_id is not None and item_id not in texts:
            texts[item_id] = item["text"]

    gold = record.get("gold")
    if not isinstance(gold, list):
        issue(None, "missing or invalid 'gold' (list)")
        gold = []
    ranges: dict[str, list[tuple[int, int]]] = {}
    for index, span in enumerate(gold):
        if not isinstance(span, dict):
            issue(None, f"gold[{index}] must be an object")
            continue
        item_id = span.get("item_id") if _is_id(span.get("item_id")) else None
        label = f"gold[{index}]"
        if item_id is None:
            issue(None, f"{label}: missing or invalid 'item_id'")
        elif item_id not in texts:
            issue(item_id, f"{label}: refers to an item_id not in this session")
        if span.get("type") not in GOLD_TYPES:
            issue(item_id, f"{label}: invalid type; expected one of {list(GOLD_TYPES)}")
        start, end = span.get("start"), span.get("end")
        if not (_is_int(start) and _is_int(end)):
            issue(item_id, f"{label}: 'start' and 'end' must be integers")
            continue
        if item_id in texts:
            if not (0 <= start < end <= len(texts[item_id])):
                issue(item_id, f"{label}: span [{start}, {end}) is empty or outside text of length {len(texts[item_id])}")
                continue
            ranges.setdefault(item_id, []).append((start, end))
    for item_id, spans in ranges.items():
        spans.sort()
        for (left_start, left_end), (right_start, right_end) in zip(spans, spans[1:]):
            if left_end > right_start:
                issue(item_id, f"gold spans [{left_start}, {left_end}) and [{right_start}, {right_end}) overlap")
    return issues


def validate_dataset(path: str | Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    session_ids: set[str] = set()
    item_ids: dict[str, str] = {}
    sessions = 0
    try:
        records = list(iter_records(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [ValidationIssue(None, None, f"cannot read dataset as UTF-8: {type(exc).__name__}")]
    for line, raw in records:
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(ValidationIssue(None, None, f"line {line}: invalid JSON ({exc.msg} at column {exc.colno})"))
            continue
        sessions += 1
        issues.extend(validate_session(record, line=line))
        if not isinstance(record, dict):
            continue
        session_id = record.get("session_id")
        if _is_id(session_id):
            if session_id in session_ids:
                issues.append(ValidationIssue(session_id, None, f"line {line}: duplicate session_id"))
            session_ids.add(session_id)
        own: set[str] = set()
        for item in record.get("items") if isinstance(record.get("items"), list) else []:
            item_id = item.get("item_id") if isinstance(item, dict) else None
            if not _is_id(item_id) or item_id in own:
                continue  # in-session duplicates are reported by validate_session
            own.add(item_id)
            if item_id in item_ids:
                issues.append(ValidationIssue(session_id if _is_id(session_id) else None, item_id,
                                              f"line {line}: item_id already used in session {item_ids[item_id]}"))
            else:
                item_ids[item_id] = session_id if _is_id(session_id) else "-"
    if sessions == 0 and not issues:
        issues.append(ValidationIssue(None, None, "dataset contains no sessions"))
    return issues
