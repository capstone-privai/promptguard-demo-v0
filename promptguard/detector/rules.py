"""CredSweeper ML-off adapter for in-memory runtime output scanning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from credsweeper import CredSweeper
from credsweeper.file_handler.string_content_provider import StringContentProvider

from promptguard.common.location import locate
from promptguard.common.schema import Candidate, CandidateType


_URI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+")


@dataclass(frozen=True)
class _Detection:
    rule: str
    candidate_type: CandidateType
    start: int
    end: int


@lru_cache(maxsize=1)
def _scanner():
    # Integer zero disables CredSweeper's ML validation. Built-in filters stay on.
    return CredSweeper(ml_threshold=0, use_filters=True, pool_count=1).scanner


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


def _candidate_type(rule: str) -> CandidateType:
    lowered = rule.lower()
    if "pem" in lowered or "private key" in lowered:
        return "PRIVATE_KEY"
    if "password" in lowered or "url credentials" in lowered or "authorization" in lowered:
        return "PASSWORD"
    if "token" in lowered:
        return "TOKEN"
    if "client id" in lowered or "access key" in lowered:
        return "ACCESS_KEY"
    return "SECRET"


def _priority(detection: _Detection) -> tuple[int, int, int]:
    rule = detection.rule.lower()
    specialized = 3 if "pem" in rule else 2 if "url credentials" in rule else 1
    return specialized, -(detection.end - detection.start), -detection.start


def _normalize(text: str, detections: list[_Detection]) -> list[_Detection]:
    """Prefer specialized rules and suppress generic URI false positives."""
    uri_ranges = [match.span() for match in _URI.finditer(text)]
    specialized_uri_ranges = [
        uri_range
        for uri_range in uri_ranges
        if any(
            detection.rule == "URL Credentials"
            and uri_range[0] <= detection.start < detection.end <= uri_range[1]
            for detection in detections
        )
    ]

    filtered: list[_Detection] = []
    for detection in detections:
        if detection.rule != "URL Credentials" and any(
            start <= detection.start < detection.end <= end for start, end in specialized_uri_ranges
        ):
            continue
        filtered.append(detection)

    selected: list[_Detection] = []
    for detection in sorted(filtered, key=_priority, reverse=True):
        if any(detection.start < prior.end and detection.end > prior.start for prior in selected):
            continue
        selected.append(detection)
    return sorted(selected, key=lambda item: (item.start, item.end))


def _scan(text: str) -> list[_Detection]:
    lines, offsets = _line_layout(text)
    if not lines:
        return []
    provider = StringContentProvider(lines, file_path="<tool-output>", file_type=".txt", info="runtime")
    found = _scanner().scan(provider)
    detections: list[_Detection] = []
    for credential in found:
        line_data = credential.line_data_list
        if not line_data:
            continue
        candidate_type = _candidate_type(credential.rule_name)
        if candidate_type == "PRIVATE_KEY" and len(line_data) > 1:
            first, last = line_data[0], line_data[-1]
            start = offsets[first.line_pos] + first.value_start
            end = offsets[last.line_pos] + last.value_end
            detections.append(_Detection(credential.rule_name, candidate_type, start, end))
            continue
        for item in line_data:
            if item.value is None or item.value_start < 0 or item.value_end <= item.value_start:
                continue
            start = offsets[item.line_pos] + item.value_start
            end = offsets[item.line_pos] + item.value_end
            detections.append(_Detection(credential.rule_name, candidate_type, start, end))
    return _normalize(text, detections)


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
    for index, detection in enumerate(_scan(text), 1):
        location = locate(text, detection.start, detection.end)
        candidates.append(
            Candidate(
                candidate_id=f"{channel}-c{index}",
                session_id=session_id,
                turn_id=turn_id,
                operation_id=operation_id,
                type=detection.candidate_type,
                text=location["value"],
                span=location["span"],
                line=location["line"],
                context=location["context"],
                meta={
                    "line_crop_offset": location["line_crop_offset"],
                    "detector": "CredSweeper",
                    "rule": detection.rule,
                    "ml_enabled": False,
                },
                source={"channel": "tool_output", "stream": channel, "tool_name": tool_name},
            )
        )
    return candidates
