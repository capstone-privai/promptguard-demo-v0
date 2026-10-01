# PromptGuard Demo v0

PromptGuard Demo v0 proves the end-to-end Codex CLI pipeline:

```text
Codex CLI → UserPromptSubmit → PreToolUse → memory-only daemon
→ opaque operation ID → runner → detector → candidate record
→ mock predictor (KEEP/MASK) → redaction → PostToolUse verifier → Codex
```

This is a pipeline demo, not an ML-quality or enterprise-DLP claim. It implements only `KEEP` and `MASK`.

## Layout

```text
promptguard/
  audit/       metadata-only JSONL logging
  common/      canonical location.py and schemas
  daemon/      loopback daemon and in-memory registries
  decision/    Predictor interface and MockPredictor
  detector/    Demo v0 rules
  hooks/       Codex lifecycle hook
  redaction/   span-safe replacement and fingerprints
  runner/      opaque operation runner
  scripts/     PowerShell launch helpers
  tests/
synthetic_workspace/
  .env.example  synthetic input copied locally to ignored .env
```

## Run

From this repository root in PowerShell:

```powershell
./promptguard/scripts/start_daemon.ps1
./promptguard/scripts/run_codex_demo.ps1
```

The launcher copies the committed synthetic `.env.example` to an ignored local `.env` when needed. No real credential is required or expected.
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
API_TOKEN=[TOKEN_1]
LOG_LEVEL=debug
```

The private IP is deliberately `KEEP`; password and token candidates are `MASK`.

Stop the daemon without sending any external network request:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:18765/shutdown
```

## Tests

The canonical location implementation is `promptguard/common/location.py`. The supplied `test_location.py` can be run with that directory on `PYTHONPATH`. Pipeline tests run with:

```powershell
$Python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python -m unittest promptguard.tests.test_pipeline -v
```

## Candidate contract

Each in-memory candidate has IDs and type, raw `text`, canonical `span`, `line`, `context`, `meta.line_crop_offset`, and `source`. The raw value is passed to the predictor in memory but is never written to audit logs. Dataset code should import the same `locate`, `build_location`, `check_span`, `split_lines`, and `window_text` functions from `promptguard.common.location`.

## Replace the mock model

Implement the protocol in `promptguard/decision/base.py`, then change only the predictor construction in `promptguard/runner/main.py`. The method contract is:

```python
predict(candidates, task_context) -> list[Prediction]
```

Every candidate must receive one `KEEP` or `MASK` prediction with the same `candidate_id`.

## Explicit limitations

- Windows/PowerShell and Codex CLI only
- rule detector, deterministic mock decisions, no `GENERALIZE`
- no hosted-tool interception or complete DLP coverage
- Hook failure itself is not a complete security boundary
- loopback has no enterprise authentication/ACL
- task prompt and original command exist in daemon memory for short-lived processing
- process startup dominates latency; Demo v0 is not optimized
