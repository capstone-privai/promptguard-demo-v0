from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.adapters.base import ItemOutput
from evaluation.cli import EXIT_CONFIG, EXIT_DATASET, EXIT_OK, EXIT_SCORING, execute_run, main
from evaluation.dataset.schema import Session
from evaluation.scorer.edits import Edit

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"


class LyingAdapter:
    """Claims to mask every gold span but returns the original text."""

    name = "lying"

    def describe(self) -> dict:
        return {"system": self.name}

    def run_session(self, session: Session) -> dict[str, ItemOutput]:
        return {
            item.item_id: ItemOutput(item.item_id, item.text,
                                     [Edit(start=span.start, end=span.end, replacement="[X]") for span in session.gold_for(item.item_id)])
            for item in session.items
        }


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name) / "runs"

    def _main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        code = main(list(argv), out=out)
        return code, out.getvalue()

    def _broken_dataset(self) -> Path:
        path = Path(self._tmp.name) / "broken.jsonl"
        record = json.loads(FIXTURE.read_text(encoding="utf-8").splitlines()[0])
        record["items"][0]["channel"] = "browser"
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return path

    def test_validate(self) -> None:
        code, output = self._main("validate", "--dataset", str(FIXTURE))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("OK: 8 sessions", output)
        code, output = self._main("validate", "--dataset", str(self._broken_dataset()))
        self.assertEqual(code, EXIT_DATASET)
        self.assertIn("invalid channel", output)

    def test_run_reference_systems(self) -> None:
        for system, recall in (("oracle", "recall=1.0000"), ("identity", "recall=0.0000")):
            code, output = self._main("run", "--dataset", str(FIXTURE), "--system", system, "--out", str(self.out_dir))
            self.assertEqual(code, EXIT_OK, output)
            self.assertIn(recall, output)

    def test_run_promptguard(self) -> None:
        code, output = self._main("run", "--dataset", str(FIXTURE), "--system", "promptguard", "--out", str(self.out_dir))
        self.assertEqual(code, EXIT_OK, output)
        self.assertIn("gold=12", output)
        self.assertIn("results: ", output)

    def test_run_promptguard_sweep(self) -> None:
        code, output = self._main("run", "--dataset", str(FIXTURE), "--system", "promptguard", "--sweep", "0:1:0.5",
                                  "--out", str(self.out_dir))
        self.assertEqual(code, EXIT_OK, output)
        self.assertEqual(output.count("threshold="), 3)
        self.assertIn("pr_auc=N/A", output)

    def test_invalid_dataset_exits_1(self) -> None:
        code, output = self._main("run", "--dataset", str(self._broken_dataset()), "--system", "oracle",
                                  "--out", str(self.out_dir))
        self.assertEqual(code, EXIT_DATASET)
        self.assertIn("nothing was run", output)

    def test_unverifiable_edits_exit_2_without_results(self) -> None:
        out = io.StringIO()
        code = execute_run(str(FIXTURE), lambda _threshold: LyingAdapter(), out_root=self.out_dir, out=out)
        self.assertEqual(code, EXIT_SCORING)
        self.assertFalse(self.out_dir.exists())
        self.assertIn("session=s-0001 item=s-0001/2", out.getvalue())
        self.assertIn("first difference at offset", out.getvalue())
        self.assertNotIn("mysecret123", out.getvalue())

    def test_configuration_errors_exit_3(self) -> None:
        code, _output = self._main("run", "--dataset", str(FIXTURE), "--system", "nope")
        self.assertEqual(code, EXIT_CONFIG)
        code, _output = self._main("run", "--dataset", str(FIXTURE))
        self.assertEqual(code, EXIT_CONFIG)
        for extra in (["--system", "promptguard", "--predictor", "does-not-exist"],
                      ["--system", "promptguard", "--threshold", "1.5"],
                      ["--system", "oracle", "--threshold", "0.5"],
                      ["--system", "oracle", "--sweep", "0:1:0.5"],
                      ["--system", "promptguard", "--sweep", "1:0:0.5"],
                      ["--system", "promptguard", "--threshold", "0.5", "--sweep", "0:1:0.5"],
                      ["--system", "oracle", "--ml", "on"]):
            code, _output = self._main("run", "--dataset", str(FIXTURE), "--out", str(self.out_dir), *extra)
            self.assertEqual(code, EXIT_CONFIG, extra)


if __name__ == "__main__":
    unittest.main()
