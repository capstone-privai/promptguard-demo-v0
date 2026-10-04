from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest import mock

from promptguard import pipeline
from promptguard.common.location import check_span
from promptguard.decision.mock_predictor import MockPredictor
from promptguard.decision.registry import PREDICTOR_ENV, load_predictor
from promptguard.detector.rules import detect_candidates
from promptguard.pipeline import PROCESSED_CHANNELS, build_task_context, process_output
from promptguard.redaction.engine import redact
from promptguard.redaction.placeholders import PlaceholderRegistry


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
        safe, _edits = redact(self.text, self.candidates, predictions, PlaceholderRegistry().allocator("s1"))
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
        safe, _edits = redact(text, candidates, predictions, lambda _type, _digest: "[PASSWORD_1]")
        self.assertEqual(safe, "DATABASE_URL=mysql://user:[PASSWORD_1]@db.internal:3306/app\n")

    def test_process_output_matches_manual_assembly(self) -> None:
        task_context = build_task_context("synthetic task", "t1")
        self.assertEqual(task_context, {"prompt": "synthetic task", "turn_id": "t1"})
        result = process_output(
            self.text, session_id="s1", turn_id="t1", operation_id="o1", channel="stdout",
            task_context=task_context, predictor=MockPredictor(), allocate=PlaceholderRegistry().allocator("s1"),
        )
        manual_text, manual_edits = redact(
            self.text, self.candidates, MockPredictor().predict(self.candidates, task_context),
            PlaceholderRegistry().allocator("s1"),
        )
        self.assertEqual(result.text, manual_text)
        self.assertEqual(result.edits, manual_edits)
        self.assertEqual(
            [(edit.replacement, self.text[edit.start : edit.end]) for edit in result.edits],
            [("[PASSWORD_1]", "mysecret123"), ("[PASSWORD_2]", "secret123")],
        )
        self.assertEqual(result.candidates, self.candidates)
        self.assertEqual([item.action for item in result.predictions], ["MASK", "MASK"])
        self.assertIn("DB_PASSWORD=[PASSWORD_1]", result.text)

    def test_process_output_rejects_unprocessed_channel(self) -> None:
        self.assertEqual(PROCESSED_CHANNELS, ("stdout", "stderr"))
        with self.assertRaises(ValueError):
            process_output(
                self.text, session_id="s1", turn_id="t1", operation_id="o1", channel="agents_md",
                task_context={}, predictor=MockPredictor(), allocate=PlaceholderRegistry().allocator("s1"),
            )

    def test_pipeline_imports_only_detection_decision_redaction(self) -> None:
        tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        allowed = ("__future__", "dataclasses", "typing", "promptguard.common.", "promptguard.decision.",
                   "promptguard.detector.", "promptguard.redaction.")
        self.assertEqual([name for name in modules if not name.startswith(allowed)], [])

    def test_placeholder_registry_numbers_per_session_and_type(self) -> None:
        registry = PlaceholderRegistry()
        self.assertEqual(registry.allocate("s1", "PASSWORD", "a"), "[PASSWORD_1]")
        self.assertEqual(registry.allocate("s1", "PASSWORD", "b"), "[PASSWORD_2]")
        self.assertEqual(registry.allocate("s1", "PASSWORD", "a"), "[PASSWORD_1]")
        self.assertEqual(registry.allocate("s1", "TOKEN", "a"), "[TOKEN_1]")
        self.assertEqual(registry.allocate("s2", "PASSWORD", "b"), "[PASSWORD_1]")
        registry.drop("s1")
        self.assertEqual(registry.allocate("s1", "PASSWORD", "b"), "[PASSWORD_1]")

    def test_load_predictor_by_name_and_environment(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PREDICTOR_ENV, None)
            self.assertIsInstance(load_predictor(), MockPredictor)
        self.assertIsInstance(load_predictor("mock"), MockPredictor)
        with mock.patch.dict(os.environ, {PREDICTOR_ENV: "mock"}):
            self.assertIsInstance(load_predictor(), MockPredictor)
        with self.assertRaises(ValueError):
            load_predictor("does-not-exist")


if __name__ == "__main__":
    unittest.main()
