from __future__ import annotations

import unittest

from promptguard.common.location import check_span
from promptguard.decision.mock_predictor import MockPredictor
from promptguard.detector.rules import detect_candidates
from promptguard.redaction.engine import redact


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (
            "DB_HOST=10.20.30.15\n"
            "DB_USER=deploy\n"
            "DB_PASSWORD=PG_FAKE_PASSWORD_UNIT\n"
            "API_TOKEN=PG_FAKE_TOKEN_UNIT\n"
            "LOG_LEVEL=debug\n"
        )
        self.candidates = detect_candidates(
            self.text, session_id="s1", turn_id="t1", operation_id="o1", channel="stdout"
        )

    def test_candidate_shape_and_shared_location(self) -> None:
        self.assertEqual([item.type for item in self.candidates], ["PRIVATE_IP", "PASSWORD", "TOKEN"])
        for item in self.candidates:
            record = {
                "value": item.text,
                "span": item.span,
                "line": item.line,
                "context": item.context,
                "meta": item.meta,
            }
            self.assertEqual(check_span(self.text, record), [])
            self.assertEqual(self.text[item.span["start"] : item.span["end"]], item.text)

    def test_mock_decision_and_redaction(self) -> None:
        predictions = MockPredictor().predict(self.candidates, {"prompt": "synthetic task"})
        self.assertEqual([item.action for item in predictions], ["KEEP", "MASK", "MASK"])
        assigned: dict[tuple[str, str], str] = {}

        def allocate(candidate_type: str, digest: str) -> str:
            key = candidate_type, digest
            assigned.setdefault(key, f"[{candidate_type}_{sum(1 for t, _ in assigned if t == candidate_type) + 1}]")
            return assigned[key]

        safe = redact(self.text, self.candidates, predictions, allocate)
        self.assertIn("DB_HOST=10.20.30.15", safe)
        self.assertIn("DB_PASSWORD=[PASSWORD_1]", safe)
        self.assertIn("API_TOKEN=[TOKEN_1]", safe)
        self.assertNotIn("PG_FAKE_", safe)


if __name__ == "__main__":
    unittest.main()
