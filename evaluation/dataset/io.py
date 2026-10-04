"""Load a JSONL dataset (one session per line). Validate with validate.validate_dataset first."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evaluation.dataset.schema import GoldSpan, Item, Session


def session_from_record(record: dict[str, Any]) -> Session:
    return Session(
        session_id=record["session_id"],
        items=[Item(item["item_id"], item["turn_id"], item["channel"], item["text"]) for item in record["items"]],
        gold=[GoldSpan(span["item_id"], span["start"], span["end"], span["type"]) for span in record["gold"]],
        meta=dict(record.get("meta") or {}),
    )


def iter_records(path: str | Path):
    """Yield (line_number, raw_line) for non-blank lines."""
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                yield number, line


def load_sessions(path: str | Path) -> list[Session]:
    return [session_from_record(json.loads(line)) for _number, line in iter_records(path)]


def dataset_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
