"""Reference systems that pin the scorer: Oracle must score 1.0/1.0, Identity 0.0/None."""

from __future__ import annotations

from typing import Any

from evaluation.adapters.base import ItemOutput, passthrough
from evaluation.dataset.schema import Session
from evaluation.scorer.edits import Edit, apply_edits


class OracleAdapter:
    name = "oracle"

    def describe(self) -> dict[str, Any]:
        return {"system": self.name, "replacement": "[GOLD]"}

    def run_session(self, session: Session) -> dict[str, ItemOutput]:
        outputs: dict[str, ItemOutput] = {}
        for item in session.items:
            edits = [Edit(start=span.start, end=span.end, replacement="[GOLD]") for span in session.gold_for(item.item_id)]
            outputs[item.item_id] = ItemOutput(item.item_id, apply_edits(item.text, edits), edits)
        return outputs


class IdentityAdapter:
    name = "identity"

    def describe(self) -> dict[str, Any]:
        return {"system": self.name}

    def run_session(self, session: Session) -> dict[str, ItemOutput]:
        return {item.item_id: passthrough(item.item_id, item.text) for item in session.items}
