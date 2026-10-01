from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence

from promptguard.common.schema import Candidate, Prediction


PlaceholderAllocator = Callable[[str, str], str]


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact(
    text: str,
    candidates: Sequence[Candidate],
    predictions: Sequence[Prediction],
    allocate: PlaceholderAllocator,
) -> str:
    by_id = {prediction.candidate_id: prediction for prediction in predictions}
    replacements: list[tuple[int, int, str]] = []
    for candidate in candidates:
        prediction = by_id.get(candidate.candidate_id)
        if prediction is None:
            raise ValueError(f"missing prediction for {candidate.candidate_id}")
        if prediction.action == "MASK":
            placeholder = allocate(candidate.type, fingerprint(candidate.text))
            replacements.append((candidate.span["start"], candidate.span["end"], placeholder))
        elif prediction.action != "KEEP":
            raise ValueError(f"unsupported action: {prediction.action}")
    output = text
    for start, end, replacement in sorted(replacements, reverse=True):
        output = output[:start] + replacement + output[end:]
    return output
