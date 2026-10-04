"""Dataset records. Offsets are Python string (code point) offsets, start inclusive, end exclusive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# `file_read` and `mcp` are reserved: accepted in datasets, not processed by the current system.
CHANNELS: tuple[str, ...] = ("prompt", "agents_md", "stdout", "stderr", "file_read", "mcp")

# Must equal promptguard.common.schema.CandidateType; test_system_contract checks this.
GOLD_TYPES: tuple[str, ...] = ("PASSWORD", "TOKEN", "ACCESS_KEY", "PRIVATE_KEY", "SECRET")


@dataclass(frozen=True)
class GoldSpan:
    item_id: str
    start: int
    end: int
    type: str


@dataclass(frozen=True)
class Item:
    item_id: str
    turn_id: str
    channel: str
    text: str


@dataclass(frozen=True)
class Session:
    session_id: str
    items: list[Item]
    gold: list[GoldSpan]
    meta: dict[str, Any] = field(default_factory=dict)

    def gold_for(self, item_id: str) -> list[GoldSpan]:
        return sorted((span for span in self.gold if span.item_id == item_id), key=lambda span: (span.start, span.end))
