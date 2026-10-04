"""Baseline: CredSweeper alone, masking every detection. Does not go through promptguard.

Line/offset handling follows promptguard/detector/rules.py `_scan` (including multi-line PEM
spans) without importing it. Its URI `_normalize` post-processing is deliberately not
reproduced: that difference is part of what "CredSweeper alone vs PromptGuard" measures.
"""

from __future__ import annotations

import time
from typing import Any

import credsweeper
from credsweeper import CredSweeper
from credsweeper.file_handler.string_content_provider import StringContentProvider

from evaluation.adapters.base import ItemOutput, passthrough
from evaluation.dataset.schema import Session
from evaluation.scorer.edits import Edit, apply_edits

REPLACEMENT = "[SECRET]"
_WARMUP_TEXT = "DB_PASSWORD=warmup123\n"


def _line_layout(text: str) -> tuple[list[str], list[int]]:
    raw_lines = text.splitlines(keepends=True)
    if not raw_lines and text:
        raw_lines = [text]
    lines: list[str] = []
    offsets: list[int] = []
    cursor = 0
    for raw_line in raw_lines:
        offsets.append(cursor)
        lines.append(raw_line.rstrip("\r\n"))
        cursor += len(raw_line)
    return lines, offsets


def _is_private_key(rule: str) -> bool:
    lowered = rule.lower()
    return "pem" in lowered or "private key" in lowered


def select_non_overlapping(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Keep the longest span among overlaps, then the earliest; return them sorted by start."""
    selected: list[tuple[int, int]] = []
    for start, end in sorted(set(spans), key=lambda span: (-(span[1] - span[0]), span[0])):
        if not any(start < prior_end and prior_start < end for prior_start, prior_end in selected):
            selected.append((start, end))
    return sorted(selected)


class CredSweeperAdapter:
    name = "credsweeper"

    def __init__(self, ml: bool = False, channels: tuple[str, ...] = ("stdout", "stderr")):
        self.ml = ml
        self.channels = tuple(channels)
        # ml=False matches the demo detector; ml=True keeps CredSweeper's default ml_threshold (medium).
        self._sweeper = (CredSweeper(use_filters=True, pool_count=1) if ml
                         else CredSweeper(ml_threshold=0, use_filters=True, pool_count=1))
        self.detect(_WARMUP_TEXT)  # load rules (and the ML model) outside the recorded latencies

    def describe(self) -> dict[str, Any]:
        return {"system": self.name, "ml": self.ml, "credsweeper_version": credsweeper.__version__,
                "channels": list(self.channels)}

    def detect(self, text: str) -> list[tuple[int, int]]:
        lines, offsets = _line_layout(text)
        if not lines:
            return []
        provider = StringContentProvider(lines, file_path="<tool-output>", file_type=".txt", info="evaluation")
        manager = self._sweeper.credential_manager
        manager.clear_credentials()
        self._sweeper.scan([provider], None)
        self._sweeper.post_processing(None)  # ML validation when enabled; duplicate purge either way
        found = list(manager.get_credentials())  # the manager returns its own list; copy before clearing
        manager.clear_credentials()
        spans: list[tuple[int, int]] = []
        for credential in found:
            line_data = credential.line_data_list
            if not line_data:
                continue
            if _is_private_key(credential.rule_name) and len(line_data) > 1:
                first, last = line_data[0], line_data[-1]
                spans.append((offsets[first.line_pos] + first.value_start, offsets[last.line_pos] + last.value_end))
                continue
            for item in line_data:
                if item.value is None or item.value_start < 0 or item.value_end <= item.value_start:
                    continue
                spans.append((offsets[item.line_pos] + item.value_start, offsets[item.line_pos] + item.value_end))
        return select_non_overlapping(spans)

    def run_session(self, session: Session) -> dict[str, ItemOutput]:
        outputs: dict[str, ItemOutput] = {}
        for item in session.items:
            if item.channel not in self.channels:
                outputs[item.item_id] = passthrough(item.item_id, item.text)
                continue
            started = time.perf_counter()
            edits = [Edit(start=start, end=end, replacement=REPLACEMENT) for start, end in self.detect(item.text)]
            text = apply_edits(item.text, edits)
            elapsed_ms = (time.perf_counter() - started) * 1000
            outputs[item.item_id] = ItemOutput(item.item_id, text, edits, elapsed_ms)
        return outputs
