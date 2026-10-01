"""Metadata-only JSONL logger. Callers must never pass prompt/command/output/value."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


_lock = threading.Lock()
_forbidden = {"prompt", "command", "output", "stdout", "stderr", "text", "value", "candidate_value"}


class AuditLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **metadata: Any) -> None:
        if _forbidden.intersection(metadata):
            raise ValueError("raw content is forbidden in audit metadata")
        record = {"ts": time.time(), "event": event, **metadata}
        with _lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
