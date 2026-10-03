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
            "DB_PASSWORD=mysecret123\n"
            "DATABASE_URL=postgresql://admin:secret123@prod-db.internal:5432/payments\n"
            "LOG_LEVEL=debug\n"
        )
        self.candidates = detect_candidates(
            self.text, session_id="s1", turn_id="t1", operation_id="o1", channel="stdout"
        )

    def test_candidate_shape_and_shared_location(self) -> None:
        self.assertEqual([item.type for item in self.candidates], ["PASSWORD", "PASSWORD"])
        self.assertEqual([item.meta["rule"] for item in self.candidates], ["Password", "URL Credentials"])
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
        self.assertEqual([item.action for item in predictions], ["MASK", "MASK"])
        assigned: dict[tuple[str, str], str] = {}

        def allocate(candidate_type: str, digest: str) -> str:
            key = candidate_type, digest
            assigned.setdefault(key, f"[{candidate_type}_{sum(1 for t, _ in assigned if t == candidate_type) + 1}]")
            return assigned[key]

        safe = redact(self.text, self.candidates, predictions, allocate)
        self.assertIn("DB_HOST=10.20.30.15", safe)
        self.assertIn("DB_PASSWORD=[PASSWORD_1]", safe)
        self.assertIn("postgresql://admin:[PASSWORD_2]@prod-db.internal:5432/payments", safe)
        self.assertNotIn("mysecret123", safe)
        self.assertNotIn(":secret123@", safe)

    def test_mysql_uri_false_positive_does_not_mask_port_or_database(self) -> None:
        text = "DATABASE_URL=mysql://user:secret@db.internal:3306/app\n"
        candidates = detect_candidates(
            text, session_id="s1", turn_id="t1", operation_id="o2", channel="stdout"
        )
        self.assertEqual([(item.meta["rule"], item.text) for item in candidates], [("URL Credentials", "secret")])
        predictions = MockPredictor().predict(candidates, {})
        safe = redact(text, candidates, predictions, lambda _type, _digest: "[PASSWORD_1]")
        self.assertEqual(safe, "DATABASE_URL=mysql://user:[PASSWORD_1]@db.internal:3306/app\n")


if __name__ == "__main__":
    unittest.main()
