# PromptGuard CredSweeper Demo v0

PromptGuard Demo v0 proves the end-to-end Codex CLI pipeline:

```text
Codex CLI → UserPromptSubmit → PreToolUse → memory-only daemon
→ opaque operation ID → runner → CredSweeper ML-off detector → candidate record
→ mock predictor (KEEP/MASK) → redaction → PostToolUse verifier → Codex
```

This is a pipeline demo, not an ML-quality or enterprise-DLP claim. It implements only `KEEP` and `MASK`.

## Layout

```text
promptguard/
  audit/       metadata-only JSONL logging
  common/      canonical location.py and schemas
  daemon/      loopback daemon and in-memory registries
  decision/    Predictor interface, MockPredictor and name-based predictor loading
  detector/    CredSweeper adapter and span normalization
  hooks/       Codex lifecycle hook
  redaction/   span-safe replacement, fingerprints and session placeholder numbering
  runner/      opaque operation runner
  pipeline.py  detection → decision → redaction assembly shared with evaluation
  scripts/     PowerShell launch helpers
  tests/
synthetic_workspace/
  .env.example  synthetic input copied locally to ignored .env
```

## Run

From this repository root in PowerShell, install the pinned detector dependency once:

```powershell
./promptguard/scripts/setup.ps1
```

On Windows the setup script prefers the Codex desktop app's bundled Python so
the generated venv remains executable from the sandboxed Hook process. It falls
back to `python` or `py` only when that bundled interpreter is unavailable.

Then start the daemon and run the Codex task:

```powershell
./promptguard/scripts/start_daemon.ps1
./promptguard/scripts/run_codex_demo.ps1
```

The launcher refreshes the ignored synthetic `.env` from the committed `.env.example` on every run. No real credential is required or expected.
It first checks `PATH` for `codex` and then automatically detects the Codex desktop app's bundled `codex.exe`, so the VS Code terminal does not need a separate global CLI installation.
The launcher also passes that detected, version-specific Codex binary directory to the runner. This makes bundled tools such as `rg.exe` available without hard-coding the changing Codex build hash.

The Demo task is:

```text
DB connection 문제를 확인해줘. 필요한 로컬 설정 파일을 읽고 문제 원인을 알려줘.
```

Expected model-facing tool content includes:

```text
DB_HOST=10.20.30.15
DB_USER=deploy
DB_PASSWORD=[PASSWORD_1]
DATABASE_URL=postgresql://admin:[PASSWORD_2]@prod-db.internal:5432/payments
LOG_LEVEL=debug
```

The private IP is not a credential candidate and remains visible. CredSweeper detects both password values; PromptGuard masks only their value spans, so the connection-string host, port, and database remain useful to Codex.

## CredSweeper integration

- `credsweeper==1.18.5` is pinned in `requirements.txt`.
- ML validation is disabled with `ml_threshold=0`; built-in rules and filters remain enabled.
- Tool stdout/stderr is scanned in memory through `StringContentProvider`. Raw output is not written to a temporary scan file.
- CredSweeper `LineData.value_start/value_end` becomes the initial PromptGuard span.
- Specialized `URL Credentials` candidates take precedence over generic credential rules inside the same URI.
- Overlapping candidates are normalized before right-to-left placeholder replacement.
- The Demo policy masks every surviving credential candidate. Task-aware KEEP/MASK decisions remain future work.

Stop the daemon without sending any external network request:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:18765/shutdown
```

## Tests

The canonical location implementation is `promptguard/common/location.py`. Pipeline tests run inside the project environment with:

```powershell
./.venv/Scripts/python.exe -m unittest promptguard.tests.test_pipeline -v
```

## Candidate contract

Each in-memory candidate has IDs and type, raw `text`, canonical `span`, `line`, `context`, `meta.line_crop_offset`, and `source`. The raw value is passed to the predictor in memory but is never written to audit logs. Dataset code should import the same `locate`, `build_location`, `check_span`, `split_lines`, and `window_text` functions from `promptguard.common.location`.

## Shared pipeline and processed channels

`promptguard/pipeline.py` holds the runtime assembly: `process_output(text, *, session_id, turn_id, operation_id, channel, task_context, predictor, allocate)` runs detection, decision and redaction, and `build_task_context(prompt, turn_id)` builds the `task_context` the daemon attaches to each operation. The runner calls these functions directly; evaluation should import them rather than copy runner code. The module imports only detector, decision and redaction code (no PowerShell, subprocess or HTTP transport), so it runs on Linux and in CI. A test enforces this import rule.

`PROCESSED_CHANNELS` declares the inputs the system actually redacts: Bash tool `stdout` and `stderr`. The user prompt and `AGENTS.md` reach Codex unprocessed, and `process_output` rejects any other channel. **Rule:** this list must match the `^Bash$` hook matcher in `promptguard/scripts/run_codex_demo.ps1`; change both together when adding a channel.

`promptguard/redaction/placeholders.py` provides `PlaceholderRegistry` (session → type → value fingerprint → number). The daemon's `/placeholder` route and the tests share it.

## Replace the mock model

Implement the protocol in `promptguard/decision/base.py` and register it by name with `register_predictor` in `promptguard/decision/registry.py`. The runner picks a predictor through `load_predictor()`: an explicit name, else `$PROMPTGUARD_PREDICTOR`, else `mock`. Unknown names fail closed (output withheld). The method contract is:

```python
predict(candidates, task_context) -> list[Prediction]
```

Every candidate must receive one `KEEP` or `MASK` prediction with the same `candidate_id`. `Prediction.confidence` is the probability that the candidate should be masked, whichever action was chosen, so evaluation can sweep a threshold over it.

## Evaluation

`evaluation/` measures metric 1 (detection performance) by running a fixed test set through `promptguard.pipeline`. It runs on macOS and Linux without Codex, hooks or the daemon. See [evaluation/README.md](evaluation/README.md).

## Explicit limitations

- Windows/PowerShell and Codex CLI only
- CredSweeper rule/filter detector with ML disabled, deterministic MASK policy, no `GENERALIZE`
- CredSweeper coverage and false positives are not claimed to be complete; the adapter only implements the URI/overlap normalization needed by this V0 demo
- no hosted-tool interception or complete DLP coverage
- Hook failure itself is not a complete security boundary
- loopback has no enterprise authentication/ACL
- task prompt and original command exist in daemon memory for short-lived processing
- process startup dominates latency; Demo v0 is not optimized
