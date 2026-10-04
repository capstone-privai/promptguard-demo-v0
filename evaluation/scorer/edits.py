"""Edit records and verification.

This deliberately does not import promptguard's Edit: the scorer owns its input format so
that a system change cannot silently change scoring rules. Adapters convert field by field,
test_system_contract checks the field names, and verify() catches changes in meaning.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Edit:
    start: int  # offset into the original text, inclusive
    end: int  # offset into the original text, exclusive
    replacement: str


class EditError(ValueError):
    """The edit record itself is malformed."""


class VerificationError(ValueError):
    """The edit record does not reproduce the actual output."""


def _is_offset(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_edits(original: str, edits: Sequence[Edit]) -> list[Edit]:
    """Return the edits sorted by start; reject out-of-range, empty and overlapping edits."""
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    for edit in ordered:
        if not (_is_offset(edit.start) and _is_offset(edit.end)):
            raise EditError("edit offsets must be integers")
        if edit.start < 0 or edit.end > len(original) or edit.start >= edit.end:
            raise EditError(f"edit [{edit.start}, {edit.end}) is empty or outside text of length {len(original)}")
    for previous, current in zip(ordered, ordered[1:]):
        if previous.end > current.start:
            raise EditError(f"edits [{previous.start}, {previous.end}) and [{current.start}, {current.end}) overlap")
    return ordered


def apply_edits(original: str, edits: Sequence[Edit]) -> str:
    pieces: list[str] = []
    cursor = 0
    for edit in check_edits(original, edits):
        pieces.append(original[cursor : edit.start])
        pieces.append(edit.replacement)
        cursor = edit.end
    pieces.append(original[cursor:])
    return "".join(pieces)


def verify(original: str, output: str, edits: Sequence[Edit]) -> list[Edit]:
    """Return the sorted edits if applying them to `original` yields exactly `output`.

    The error message carries offsets and lengths only, never text, so secrets stay out of logs.
    """
    ordered = check_edits(original, edits)
    expected = apply_edits(original, ordered)
    if expected != output:
        position = next(
            (index for index, (left, right) in enumerate(zip(expected, output)) if left != right),
            min(len(expected), len(output)),
        )
        raise VerificationError(
            f"edits do not reproduce the output: first difference at offset {position} "
            f"(expected length {len(expected)}, actual length {len(output)})"
        )
    return ordered
