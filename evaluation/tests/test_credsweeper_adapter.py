from __future__ import annotations

import unittest
from pathlib import Path

from evaluation.adapters.credsweeper_adapter import REPLACEMENT, CredSweeperAdapter, select_non_overlapping
from evaluation.run import evaluate
from evaluation.scorer.span_scoring import SpanStatus
from promptguard.pipeline import PROCESSED_CHANNELS

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


class CredSweeperAdapterTests(unittest.TestCase):
    def test_ml_off_and_on_pass_verification(self) -> None:
        for ml in (False, True):
            with self.subTest(ml=ml):
                result = evaluate(FIXTURE, CredSweeperAdapter(ml=ml))  # raises if any edit fails verification
                self.assertEqual(result.system["ml"], ml)
                self.assertEqual(result.metrics["counts"]["gold_total"], 12)
                self.assertGreater(result.metrics["latency_ms"]["n"], 0)

    def test_ml_off_masks_repository_example(self) -> None:
        result = evaluate(FIXTURE, CredSweeperAdapter(ml=False))
        output = result.outputs["s-0001/2"]
        self.assertIn(f"DB_PASSWORD={REPLACEMENT}\n", output.text)
        statuses = [gold.status for score in result.scores if score.item_id == "s-0001/2" for gold in score.gold_results]
        self.assertEqual(statuses, [SpanStatus.FULL, SpanStatus.FULL])
        self.assertEqual(result.outputs["s-0002/0"].edits, [])  # prompt channel is not processed

    def test_default_channels_match_system(self) -> None:
        self.assertEqual(CredSweeperAdapter().channels, tuple(PROCESSED_CHANNELS))

    def test_overlap_keeps_longest_then_earliest(self) -> None:
        self.assertEqual(select_non_overlapping([(0, 5), (2, 10), (12, 15), (13, 16), (20, 22), (20, 22)]),
                         [(2, 10), (12, 15), (20, 22)])


if __name__ == "__main__":
    unittest.main()
