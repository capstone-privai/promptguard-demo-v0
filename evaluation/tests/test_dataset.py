from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.dataset.io import dataset_sha256, load_sessions
from evaluation.dataset.validate import validate_dataset

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


def _session(session_id: str = "s1", **overrides):
    record = {
        "session_id": session_id,
        "items": [{"item_id": f"{session_id}/0", "turn_id": "t0", "channel": "stdout", "text": "DB_PASSWORD=mysecret123\n"}],
        "gold": [{"item_id": f"{session_id}/0", "start": 12, "end": 23, "type": "PASSWORD"}],
        "meta": {"source": "test"},
    }
    record.update(overrides)
    return record


class DatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, lines: list[str]) -> Path:
        path = Path(self._tmp.name) / "data.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _issues(self, *records) -> list[str]:
        return [str(issue) for issue in validate_dataset(self._write([json.dumps(record) for record in records]))]

    def test_fixture_is_valid_and_loads(self) -> None:
        self.assertEqual(validate_dataset(FIXTURE), [])
        sessions = load_sessions(FIXTURE)
        self.assertEqual(len(sessions), 8)
        first = sessions[0]
        self.assertEqual([item.channel for item in first.items], ["prompt", "agents_md", "stdout"])
        texts = {item.item_id: item.text for item in first.items}
        self.assertEqual([texts[span.item_id][span.start : span.end] for span in first.gold_for("s-0001/2")],
                         ["mysecret123", "secret123"])
        self.assertEqual(first.meta, {"source": "fixture"})
        self.assertEqual(len(dataset_sha256(FIXTURE)), 64)

    def test_valid_minimal_session(self) -> None:
        self.assertEqual(self._issues(_session()), [])

    def test_each_error_kind_is_reported(self) -> None:
        item = {"item_id": "s1/0", "turn_id": "t0", "channel": "stdout", "text": "DB_PASSWORD=mysecret123\n"}
        cases = {
            "invalid JSON": ["{not json"],
            "missing or invalid 'session_id'": [json.dumps(_session(session_id=""))],
            "missing or invalid 'items'": [json.dumps({"session_id": "s1", "gold": []})],
            "missing or invalid 'gold'": [json.dumps({"session_id": "s1", "items": [item]})],
            "missing or invalid 'text'": [json.dumps(_session(items=[{**item, "text": 5}]))],
            "duplicate session_id": [json.dumps(_session()), json.dumps(_session(items=[{**item, "item_id": "s1/9"}], gold=[]))],
            "duplicate item_id": [json.dumps(_session(items=[item, item]))],
            "already used in session": [json.dumps(_session()), json.dumps(_session("s2", items=[item], gold=[]))],
            "invalid channel": [json.dumps(_session(items=[{**item, "channel": "browser"}]))],
            "invalid type": [json.dumps(_session(gold=[{"item_id": "s1/0", "start": 12, "end": 23, "type": "IP"}]))],
            "not in this session": [json.dumps(_session(gold=[{"item_id": "s9/0", "start": 0, "end": 1, "type": "SECRET"}]))],
            "outside text": [json.dumps(_session(gold=[{"item_id": "s1/0", "start": 12, "end": 99, "type": "SECRET"}]))],
            "is empty": [json.dumps(_session(gold=[{"item_id": "s1/0", "start": 12, "end": 12, "type": "SECRET"}]))],
            "must be integers": [json.dumps(_session(gold=[{"item_id": "s1/0", "start": "12", "end": 23, "type": "SECRET"}]))],
            "overlap": [json.dumps(_session(gold=[
                {"item_id": "s1/0", "start": 12, "end": 20, "type": "SECRET"},
                {"item_id": "s1/0", "start": 18, "end": 23, "type": "SECRET"},
            ]))],
        }
        for expected, lines in cases.items():
            with self.subTest(expected):
                messages = [str(issue) for issue in validate_dataset(self._write(lines))]
                self.assertTrue(any(expected in message for message in messages), messages)

    def test_adjacent_gold_spans_are_allowed(self) -> None:
        gold = [{"item_id": "s1/0", "start": 12, "end": 18, "type": "SECRET"},
                {"item_id": "s1/0", "start": 18, "end": 23, "type": "SECRET"}]
        self.assertEqual(self._issues(_session(gold=gold)), [])

    def test_all_issues_are_collected_with_location(self) -> None:
        bad_items = [{"item_id": "s1/0", "turn_id": "t0", "channel": "browser", "text": "abc"}]
        bad_gold = [{"item_id": "s1/0", "start": 0, "end": 9, "type": "IP"}]
        issues = validate_dataset(self._write([json.dumps(_session(items=bad_items, gold=bad_gold)), "{oops"]))
        self.assertGreaterEqual(len(issues), 4)
        self.assertIn("s1 / s1/0 / line 1: invalid channel", str(issues[0]))
        self.assertTrue(any(issue.session_id is None and "line 2" in issue.message for issue in issues))

    def test_empty_dataset_is_invalid(self) -> None:
        path = Path(self._tmp.name) / "empty.jsonl"
        path.write_text("\n", encoding="utf-8")
        self.assertEqual([issue.message for issue in validate_dataset(path)], ["dataset contains no sessions"])


if __name__ == "__main__":
    unittest.main()
