"""Values the evaluation side spells out on its own must match the system."""

from __future__ import annotations

import dataclasses
import typing
import unittest
from pathlib import Path

from evaluation.adapters.promptguard_adapter import PromptGuardAdapter
from evaluation.dataset.io import load_sessions
from evaluation.dataset.schema import GOLD_TYPES
from evaluation.scorer.edits import Edit
from promptguard.common.schema import CandidateType
from promptguard.pipeline import PROCESSED_CHANNELS
from promptguard.redaction.engine import Edit as SystemEdit

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


class SystemContractTests(unittest.TestCase):
    def test_gold_types_match_candidate_types(self) -> None:
        self.assertEqual(set(GOLD_TYPES), set(typing.get_args(CandidateType)))

    def test_edit_fields_match(self) -> None:
        self.assertEqual([field.name for field in dataclasses.fields(Edit)], list(SystemEdit._fields))

    def test_converted_edits_equal_system_edits(self) -> None:
        adapter = PromptGuardAdapter("mock", debug=True)
        checked = 0
        for session in load_sessions(FIXTURE):
            outputs = adapter.run_session(session)
            for item in session.items:
                if item.channel not in PROCESSED_CHANNELS:
                    continue
                output = outputs[item.item_id]
                system = [(edit["start"], edit["end"], edit["replacement"]) for edit in output.debug["system_edits"]]
                self.assertEqual([(edit.start, edit.end, edit.replacement) for edit in output.edits], system)
                checked += len(system)
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
