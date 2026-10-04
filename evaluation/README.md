# PromptGuard evaluation: metric 1 (detection performance)

This package runs a fixed test set through PromptGuard and scores how well secrets are kept away from the model. It calls the same runtime assembly as the runner (`promptguard.pipeline.process_output`). It does not copy runner code, and it never starts Codex, hooks, the daemon or PowerShell. It runs on macOS and Linux with Python 3.10+, the standard library and the pinned `credsweeper`.

Building the test set (secret injection, base text collection) is out of scope. This package only reads the format below.

## Quick start

From the repository root, with the project requirements installed (`pip install -r requirements.txt`):

```bash
python -m evaluation validate --dataset evaluation/tests/fixtures/mini_dataset.jsonl
```

```bash
python -m evaluation run --dataset evaluation/tests/fixtures/mini_dataset.jsonl --system promptguard
```

```bash
python -m evaluation run --dataset evaluation/tests/fixtures/mini_dataset.jsonl --system promptguard --sweep 0:1:0.1
```

```bash
python -m evaluation run --dataset evaluation/tests/fixtures/mini_dataset.jsonl --system credsweeper --ml off
```

```bash
python -m evaluation run --dataset evaluation/tests/fixtures/mini_dataset.jsonl --system oracle
```

```bash
python -m evaluation run --dataset evaluation/tests/fixtures/mini_dataset.jsonl --system identity
```

Each run writes `runs/<YYYYmmdd-HHMMSS>_<system>[_<predictor>]/` and prints the folder plus recall, precision, F2, over-masking per 1,000 lines, gold count and secret density. Keep real test sets under `evaluation_data/`. Both `runs/` and `evaluation_data/` are git-ignored.

### Options

| Option | Systems | Meaning |
|---|---|---|
| `--predictor NAME` | promptguard | Predictor from `promptguard.decision.registry` (default `mock`) |
| `--threshold T` | promptguard | Re-decide each action as MASK iff `confidence >= T` |
| `--sweep START:STOP:STEP` | promptguard | One full run per threshold (inclusive), plus PR-AUC and precision at fixed recall |
| `--ml on\|off` | credsweeper | CredSweeper ML validation (default off, the demo detector's setting) |
| `--out DIR` | all | Parent folder for run folders (default `runs`) |
| `--debug` | all | Also write `debug/` with raw candidates and predictions. **Contains secrets.** |

Exit codes: `0` ok, `1` dataset validation failed, `2` edit verification failed (no results are written), `3` configuration error.

## Systems

| System | What it does |
|---|---|
| `promptguard` | Items go through `process_output` in order, one `PlaceholderRegistry` per session. A `prompt` item replaces the task context (`build_task_context(text, turn_id)`), as the daemon does. Before the first prompt the context is empty. Only channels in `promptguard.pipeline.PROCESSED_CHANNELS` (currently `stdout`, `stderr`) are processed. Others pass through unchanged. |
| `credsweeper` | CredSweeper alone over the same channels, masking every detection with `[SECRET]`. PromptGuard's URI post-processing is intentionally not applied. |
| `oracle` | Masks exactly the gold spans. Must score recall 1.0 and precision 1.0. |
| `identity` | Changes nothing. Must score recall 0.0 and precision N/A. |

Secrets in `prompt` and `agents_md` items are always missed by `promptguard` today. That is expected, because the system does not process those channels, and it shows up in recall by channel.

## Dataset format

JSONL with one session per line:

```json
{"session_id": "s-0001",
 "items": [
   {"item_id": "s-0001/0", "turn_id": "t0", "channel": "prompt", "text": "Check why the DB connection fails."},
   {"item_id": "s-0001/1", "turn_id": "t0", "channel": "stdout", "text": "DB_PASSWORD=mysecret123\n"}],
 "gold": [{"item_id": "s-0001/1", "start": 12, "end": 23, "type": "PASSWORD"}],
 "meta": {"source": "fixture"}}
```

- `items` are in time order. `item_id` is unique across the file, and `session_id` is unique too.
- `channel` is one of `prompt`, `agents_md`, `stdout`, `stderr`, or the reserved `file_read` and `mcp`. The user prompt is an item with `channel: "prompt"`, so its secrets are scored like any other input and multi-turn sessions keep their order.
- `gold[].type` is one of `PASSWORD`, `TOKEN`, `ACCESS_KEY`, `PRIVATE_KEY`, `SECRET` (the system's `CandidateType`). Types are used for breakdowns only, never for success.
- Offsets are Python string (code point) offsets into the item's `text`: start inclusive, end exclusive, non-empty. Gold spans in one item must not overlap. Touching spans are allowed.
- `meta` is free-form. It is summarized into `run_meta.json`, so keep secrets out of it.

`validate` reports every problem at once as `session / item / message`. `run` always validates first and runs nothing on an invalid dataset.

## Scoring

- Gold comes only from the dataset, so a secret the system never saw counts as missed.
- Scoring uses only the edits a system reports (`start`, `end`, `replacement` in original-text coordinates). Before scoring an item, the edits are applied to the original text. The result must equal the system's actual output character for character, or the run stops with exit code 2. Candidates, predictions and audit logs are never used for scoring, and output texts are never diffed.
- A gold span is `full` when every character lies inside the union of edits, `missed` when none does, otherwise `partial`. An edit counts as a true positive when it overlaps any gold span. Replacement text is never inspected.

## Metrics

| Key | Definition |
|---|---|
| `recall` | full gold spans / all gold spans |
| `precision` | edits overlapping gold / all edits |
| `f2` | `5PR / (4P + R)`; `0.0` when both are 0; `None` if either is `None` |
| `pr_auc` | sweep only: step-wise area under the PR points, from recall 0; for equal recall the best precision is used; `None` with fewer than two distinct points |
| `precision_at_recall` | sweep only: best precision among thresholds with recall ≥ 0.95 / 0.99, and that threshold |
| `fp_per_1k_lines` | edits not overlapping gold / total lines × 1000 |
| `char_recall` | masked gold characters / all gold characters |
| `partial_rate`, `missed_rate` | partial / missed gold spans over all gold spans |
| `recall_by_type`, `recall_by_channel` | recall restricted to one type or channel; `None` when that group has no gold |
| `latency_ms` | p50 / p95 / max / n over items the system processed (linear-interpolated percentiles). Compare only runs from the same machine. |
| `density_per_1k_lines`, `lines_total`, `composition` | gold per 1,000 lines, total lines (`count("\n")` plus one for an unterminated last line), and gold counts by type and channel |

Ratios with a zero denominator are `None` (shown as `N/A`). PR-AUC and precision at recall depend on the threshold grid, so `metrics.json` records the thresholds used. The mock predictor always returns confidence 1.0, so its sweep collapses to one point and both summary metrics are `None`. That is expected.

## Run folder

| File | Content |
|---|---|
| `run_meta.json` | Start time, git commit and branch, system settings, thresholds, dataset path / SHA-256 / counts / meta summary, versions, platform |
| `metrics.json` | The metrics above. For a sweep: `thresholds`, `summary`, and one entry per threshold in `points` |
| `per_span.jsonl` | One row per gold span: `item_id`, `start`, `end`, `type`, `channel`, `status`, `exposed_chars` (plus `threshold` in a sweep) |
| `per_edit.jsonl` | One row per edit: `item_id`, `start`, `end`, `overlaps_gold` (plus `threshold` in a sweep) |
| `pr_curve.csv`, `pr_curve.png` | Sweep only. The PNG needs `matplotlib`, which is optional and not a dependency |
| `report.md` | Human-readable summary of everything above |
| `debug/items.jsonl` | `--debug` only. Raw candidates and predictions, **including secret values** |

No file outside `debug/` contains raw text. Git information is read directly from `.git` without running `git`, so `dirty` is always `null`.

## Layout and rules

```text
evaluation/
  dataset/   schema, loader, validator         (no promptguard imports)
  scorer/    edit verification, span scoring   (no promptguard imports)
  report/    aggregation, sweep, meta, files   (no promptguard imports)
  adapters/  systems under test                (the only place that imports promptguard)
  run.py     dataset → adapter → scorer → aggregation
  cli.py     python -m evaluation
```

- `evaluation/adapters/` may import only `promptguard.pipeline`, `promptguard.redaction.engine`, `promptguard.redaction.placeholders`, `promptguard.decision.registry`, `promptguard.decision.base` and `promptguard.common.schema`. `promptguard/` never imports `evaluation`. Nothing in `evaluation/` imports `subprocess` or networking modules. `tests/test_dependency_rules.py` enforces all of this.
- The scorer has its own `Edit` type. Adapters convert system edits field by field, `tests/test_system_contract.py` checks that the field names and `GOLD_TYPES` match the system, and edit verification catches changes in meaning.
- Do not change `promptguard/` from here. If evaluation needs a system change, record it in `SYSTEM_REQUESTS.md`.
- Test fixtures must not contain vendor-format secrets (cloud keys, API key prefixes, PEM blocks). Use values like `DB_PASSWORD=mysecret123`.

## Tests

```bash
python -m unittest discover -s evaluation/tests -t .
```

The existing system tests still run with `python -m unittest promptguard.tests.test_pipeline`.

## Known limitations

- Each sweep threshold reruns detection. This is simple but slow on large sets. Caching detection would need a system change, which should go through `SYSTEM_REQUESTS.md`.
- Metric 1 under task-aware KEEP decisions ("KEEP disabled" mode) is not available until the system provides that mode.
- The run folder name uses the local time to the second. Concurrent runs get a `-2`, `-3`, … suffix.
