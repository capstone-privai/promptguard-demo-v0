from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from evaluation.dataset.schema import Session
from evaluation.scorer.edits import Edit


@dataclass(frozen=True)
class ItemOutput:
    item_id: str
    text: str  # what the model would receive
    edits: list[Edit]  # original-text coordinates; the scorer verifies them against `text`
    elapsed_ms: float | None = None  # processing time; None for channels the system does not process
    debug: dict[str, Any] | None = None  # only with --debug; may contain raw secrets


class SystemUnderTest(Protocol):
    name: str

    def describe(self) -> dict[str, Any]:
        """Configuration recorded in run_meta.json."""
        ...

    def run_session(self, session: Session) -> dict[str, ItemOutput]:
        """Return an output for every item in the session, keyed by item_id.

        Unprocessed channels return the original text with no edits. Edits must be reported
        as applied, never reconstructed from the output text.
        """
        ...


def passthrough(item_id: str, text: str) -> ItemOutput:
    return ItemOutput(item_id=item_id, text=text, edits=[])
