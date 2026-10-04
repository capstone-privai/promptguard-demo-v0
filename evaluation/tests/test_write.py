from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from evaluation.adapters.promptguard_adapter import PromptGuardAdapter
from evaluation.cli import EXIT_OK, execute_run
from evaluation.dataset.io import load_sessions
from evaluation.report.write import create_run_dir

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dataset.jsonl"
SAFE_FILES = ("run_meta.json", "metrics.json", "per_span.jsonl", "per_edit.jsonl", "report.md")


def _gold_values() -> set[str]:
    values = set()
    for session in load_sessions(FIXTURE):
        texts = {item.item_id: item.text for item in session.items}
        values.update(texts[span.item_id][span.start : span.end] for span in session.gold)
    return values


class WriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _run(self, **kwargs) -> Path:
        with open(self.root / "stdout.txt", "w", encoding="utf-8") as out:
            code = execute_run(str(FIXTURE), lambda t: PromptGuardAdapter("mock", threshold=t, debug=kwargs.get("debug", False)),
                               label="promptguard_mock", out_root=self.root / "runs", out=out, **kwargs)
        self.assertEqual(code, EXIT_OK)
        (run_dir,) = [path for path in (self.root / "runs").iterdir()]
        return run_dir

    def test_single_run_files_without_secrets(self) -> None:
        run_dir = self._run()
        self.assertEqual(sorted(path.name for path in run_dir.iterdir()), sorted(SAFE_FILES))
        secrets = _gold_values()
        self.assertIn("mysecret123", secrets)
        for name in SAFE_FILES:
            content = (run_dir / name).read_text(encoding="utf-8")
            leaked = [secret for secret in secrets if secret in content]
            self.assertEqual(leaked, [], name)
        spans = [json.loads(line) for line in (run_dir / "per_span.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(spans), 12)
        self.assertEqual(set(spans[0]), {"item_id", "start", "end", "type", "channel", "status", "exposed_chars"})
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["counts"]["gold_total"], 12)
        meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(len(meta["dataset"]["sha256"]), 64)
        self.assertEqual(meta["dataset"]["meta_summary"], {"source": {"fixture": 8}})
        self.assertEqual(meta["system"]["system"], "promptguard")

    def test_sweep_writes_curve(self) -> None:
        run_dir = self._run(thresholds=[0.0, 0.5, 1.0], sweep=True)
        self.assertTrue((run_dir / "pr_curve.csv").is_file())
        header, *rows = (run_dir / "pr_curve.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(header, "threshold,precision,recall,f2,fp_per_1k_lines")
        self.assertEqual(len(rows), 3)
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["thresholds"], [0.0, 0.5, 1.0])
        self.assertIsNone(metrics["summary"]["pr_auc"])  # mock: one distinct point
        self.assertIn("## Threshold sweep", (run_dir / "report.md").read_text(encoding="utf-8"))

    def test_debug_is_separate_and_flagged(self) -> None:
        run_dir = self._run(debug=True)
        self.assertTrue((run_dir / "debug" / "items.jsonl").is_file())
        self.assertIn("Warning", (run_dir / "report.md").read_text(encoding="utf-8"))
        for name in SAFE_FILES:
            content = (run_dir / name).read_text(encoding="utf-8")
            self.assertFalse(any(secret in content for secret in _gold_values()), name)

    def test_run_dir_names_do_not_collide(self) -> None:
        now = datetime(2026, 10, 4, 12, 0, 0)
        first = create_run_dir(self.root, "promptguard/mock", now)
        second = create_run_dir(self.root, "promptguard/mock", now)
        self.assertEqual(first.name, "20261004-120000_promptguard-mock")
        self.assertEqual(second.name, "20261004-120000_promptguard-mock-2")


if __name__ == "__main__":
    unittest.main()
