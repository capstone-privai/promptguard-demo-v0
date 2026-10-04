from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import NamedTuple

from promptguard.common.schema import Candidate, Prediction


PlaceholderAllocator = Callable[[str, str], str]


class Edit(NamedTuple):
    """One replacement, with start/end offsets into the original text."""

    start: int
    end: int
    replacement: str


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact(
    text: str,
    candidates: Sequence[Candidate],
    predictions: Sequence[Prediction],
    allocate: PlaceholderAllocator,
) -> tuple[str, list[Edit]]:
    """Return the redacted text and its edits, sorted by original start offset."""
    by_id = {prediction.candidate_id: prediction for prediction in predictions}
    edits: list[Edit] = []
    for candidate in candidates:
        prediction = by_id.get(candidate.candidate_id)
        if prediction is None:
            raise ValueError(f"missing prediction for {candidate.candidate_id}")
        if prediction.action == "MASK":
            placeholder = allocate(candidate.type, fingerprint(candidate.text))
            edits.append(Edit(candidate.span["start"], candidate.span["end"], placeholder))
        elif prediction.action != "KEEP":
            raise ValueError(f"unsupported action: {prediction.action}")
    edits.sort()
    output = text
    for start, end, replacement in reversed(edits):
        output = output[:start] + replacement + output[end:]
    return output, edits
