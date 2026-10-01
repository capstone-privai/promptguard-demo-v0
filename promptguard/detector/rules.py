"""Small deterministic detector used only to connect the Demo v0 pipeline."""

from __future__ import annotations

import re
from collections.abc import Iterable

from promptguard.common.location import locate
from promptguard.common.schema import Candidate, CandidateType


_RULES: tuple[tuple[CandidateType, re.Pattern[str]], ...] = (
    ("PASSWORD", re.compile(r"(?im)\b(?:DB_)?PASSWORD\s*=\s*(?P<value>[^\s\r\n]+)")),
    ("TOKEN", re.compile(r"\bPG_FAKE_(?:TOKEN|API_KEY)_[A-Za-z0-9_-]+\b")),
    ("PRIVATE_IP", re.compile(r"(?<!\d)(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.(?:\d{1,3}\.)\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3})(?!\d)")),
)


def _matches(text: str) -> Iterable[tuple[CandidateType, int, int]]:
    found: list[tuple[CandidateType, int, int]] = []
    for candidate_type, pattern in _RULES:
        for match in pattern.finditer(text):
            if candidate_type == "PASSWORD":
                start, end = match.span("value")
            else:
                start, end = match.span()
            found.append((candidate_type, start, end))
    # Prefer the earlier span and avoid overlapping candidate records.
    occupied: list[tuple[int, int]] = []
    for candidate_type, start, end in sorted(found, key=lambda item: (item[1], -(item[2] - item[1]))):
        if any(start < prior_end and end > prior_start for prior_start, prior_end in occupied):
            continue
        occupied.append((start, end))
        yield candidate_type, start, end


def detect_candidates(
    text: str,
    *,
    session_id: str,
    turn_id: str,
    operation_id: str,
    channel: str,
    tool_name: str = "Bash",
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for index, (candidate_type, start, end) in enumerate(_matches(text), 1):
        location = locate(text, start, end)
        candidates.append(
            Candidate(
                candidate_id=f"{channel}-c{index}",
                session_id=session_id,
                turn_id=turn_id,
                operation_id=operation_id,
                type=candidate_type,
                text=location["value"],
                span=location["span"],
                line=location["line"],
                context=location["context"],
                meta={"line_crop_offset": location["line_crop_offset"]},
                source={"channel": "tool_output", "stream": channel, "tool_name": tool_name},
            )
        )
    return candidates
