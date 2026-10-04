from __future__ import annotations

import unittest
from pathlib import Path

from evaluation.adapters.reference import IdentityAdapter, OracleAdapter
from evaluation.run import evaluate

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


class ReferenceAdapterTests(unittest.TestCase):
    def test_oracle_is_perfect(self) -> None:
        metrics = evaluate(FIXTURE, OracleAdapter()).metrics
        for key in ("recall", "precision", "f2", "char_recall"):
            self.assertEqual(metrics[key], 1.0, key)
        self.assertEqual(metrics["fp_per_1k_lines"], 0.0)
        self.assertEqual(metrics["missed_rate"], 0.0)
        self.assertEqual(metrics["counts"]["edits_total"], metrics["counts"]["gold_total"])

    def test_identity_masks_nothing(self) -> None:
        metrics = evaluate(FIXTURE, IdentityAdapter()).metrics
        self.assertEqual(metrics["recall"], 0.0)
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["f2"])
        self.assertEqual(metrics["missed_rate"], 1.0)
        self.assertEqual(metrics["char_recall"], 0.0)

    def test_reference_systems_have_no_latency(self) -> None:
        for adapter in (OracleAdapter(), IdentityAdapter()):
            latency = evaluate(FIXTURE, adapter).metrics["latency_ms"]
            self.assertEqual(latency, {"p50": None, "p95": None, "max": None, "n": 0})


if __name__ == "__main__":
    unittest.main()
