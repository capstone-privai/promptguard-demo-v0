from __future__ import annotations

import unittest
from pathlib import Path

from evaluation.adapters.promptguard_adapter import PromptGuardAdapter
from evaluation.dataset.io import load_sessions
from evaluation.run import evaluate_sessions
from evaluation.scorer.span_scoring import SpanStatus
from promptguard.common.schema import Prediction
from promptguard.pipeline import PROCESSED_CHANNELS

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


class RecordingPredictor:
    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def predict(self, candidates, task_context):
        self.contexts.append(dict(task_context))
        return [Prediction(candidate.candidate_id, "MASK", 1.0) for candidate in candidates]


class PromptGuardAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sessions = load_sessions(FIXTURE)
        cls.result = evaluate_sessions(cls.sessions, PromptGuardAdapter("mock"))  # verifies every item's edits
        cls.items = {item.item_id: item for session in cls.sessions for item in session.items}
        cls.status = {(score.item_id, gold.start): gold.status for score in cls.result.scores for gold in score.gold_results}

    def test_unprocessed_channels_pass_through_and_miss(self) -> None:
        for item_id, item in self.items.items():
            if item.channel in ("prompt", "agents_md"):
                output = self.result.outputs[item_id]
                self.assertEqual((output.text, output.edits, output.elapsed_ms), (item.text, [], None))
        self.assertEqual(self.status[("s-0002/0", self.items["s-0002/0"].text.index("hunter2pass"))], SpanStatus.MISSED)
        self.assertEqual(self.status[("s-0007/1", self.items["s-0007/1"].text.index("kangaroo42"))], SpanStatus.MISSED)

    def test_repository_examples_are_fully_masked(self) -> None:
        text = self.items["s-0001/2"].text
        self.assertEqual(self.status[("s-0001/2", text.index("mysecret123"))], SpanStatus.FULL)
        self.assertEqual(self.status[("s-0001/2", text.index("secret123@"))], SpanStatus.FULL)
        self.assertIn("postgresql://admin:[PASSWORD_2]@prod-db.internal:5432/payments", self.result.outputs["s-0001/2"].text)

    def test_placeholders_are_session_scoped(self) -> None:
        outputs = self.result.outputs
        self.assertEqual(outputs["s-0004/1"].text, "DB_PASSWORD=[PASSWORD_1]\n")
        self.assertEqual(outputs["s-0004/2"].text, "error: auth failed for DB_PASSWORD=[PASSWORD_1]\n")
        self.assertEqual(outputs["s-0004/3"].text, "BACKUP_PASSWORD=[PASSWORD_2]\n")
        self.assertEqual(outputs["s-0005/1"].text, "DB_PASSWORD=[PASSWORD_1]\n")
        self.assertEqual(outputs["s-0008/3"].text, "DB_PASSWORD=[PASSWORD_1]\n")

    def test_prompt_items_switch_task_context(self) -> None:
        predictor = RecordingPredictor()
        adapter = PromptGuardAdapter(predictor)
        predictor.contexts.clear()  # drop the warm-up call
        adapter.run_session(self.sessions[7])  # s-0008: prompt, stdout, prompt, stdout
        self.assertEqual(predictor.contexts, [
            {"prompt": "List the config files.", "turn_id": "t0"},
            {"prompt": "Now show config/db.env.", "turn_id": "t1"},
        ])
        adapter.run_session(self.sessions[2])  # s-0003 starts fresh, then sees its own prompt
        self.assertEqual(predictor.contexts[-1]["prompt"], "Why does npm install print warnings?")

    def test_empty_task_context_before_first_prompt(self) -> None:
        from evaluation.dataset.schema import Item, Session

        predictor = RecordingPredictor()
        adapter = PromptGuardAdapter(predictor)
        predictor.contexts.clear()
        adapter.run_session(Session("x", [Item("x/0", "t0", "stdout", "DB_PASSWORD=mysecret123\n")], []))
        self.assertEqual(predictor.contexts, [{"prompt": "", "turn_id": ""}])

    def test_latency_only_for_processed_items(self) -> None:
        for item_id, item in self.items.items():
            elapsed = self.result.outputs[item_id].elapsed_ms
            if item.channel in PROCESSED_CHANNELS:
                self.assertIsInstance(elapsed, float)
            else:
                self.assertIsNone(elapsed)
        self.assertGreater(self.result.metrics["latency_ms"]["n"], 0)

    def test_processed_channels_follow_system(self) -> None:
        self.assertEqual(PromptGuardAdapter("mock").describe()["processed_channels"], list(PROCESSED_CHANNELS))

    def test_unknown_predictor_raises(self) -> None:
        with self.assertRaises(ValueError):
            PromptGuardAdapter("does-not-exist")


if __name__ == "__main__":
    unittest.main()
