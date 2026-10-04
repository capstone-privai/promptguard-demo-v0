from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from promptguard.decision.registry import load_predictor  # noqa: E402
from promptguard.pipeline import ProcessedOutput, process_output  # noqa: E402
from promptguard.transport.client import TransportError, post  # noqa: E402


def _resolve_powershell() -> str:
    candidates = [
        os.environ.get("PROMPTGUARD_POWERSHELL"),
        shutil.which("pwsh.exe"),
        shutil.which("powershell.exe"),
        str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("PowerShell executable was not found")


def _child_environment() -> dict[str, str]:
    """Preserve the caller environment and expose the active Codex tool bundle."""
    environment = os.environ.copy()
    path_entries = [entry for entry in environment.get("PATH", "").split(os.pathsep) if entry]
    candidates: list[Path] = []

    configured_bin = environment.get("PROMPTGUARD_CODEX_BIN")
    if configured_bin:
        candidates.append(Path(configured_bin))

    codex_cli = environment.get("CODEX_CLI_PATH")
    if codex_cli:
        candidates.append(Path(codex_cli).parent)

    local_app_data = environment.get("LOCALAPPDATA")
    if local_app_data:
        codex_bin_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
        if codex_bin_root.is_dir():
            discovered = sorted(
                (item.parent for item in codex_bin_root.glob("*/rg.exe") if item.is_file()),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            candidates.extend(discovered)

    known = {os.path.normcase(os.path.abspath(entry)) for entry in path_entries}
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        normalized = os.path.normcase(os.path.abspath(str(candidate)))
        if normalized not in known:
            path_entries.insert(0, str(candidate))
            known.add(normalized)

    environment["PATH"] = os.pathsep.join(path_entries)
    return environment


def _emit(operation_id: str, status: str, exit_code: int, stdout: str = "", stderr: str = "") -> None:
    sys.stdout.write(
        f"[PROMPTGUARD_RESULT]\noperation_id={operation_id}\nstatus={status}\nexit_code={exit_code}\n"
        f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n"
    )


def _safe_event(payload: dict[str, Any]) -> None:
    try:
        post("/event", payload)
    except TransportError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation-id", required=True)
    args = parser.parse_args()
    operation_id = args.operation_id
    started = time.perf_counter()
    try:
        operation = post("/claim", {"operation_id": operation_id}, timeout=0.7)
    except TransportError:
        _emit(operation_id, "blocked_claim_failed", 71, stderr="PromptGuard operation unavailable.")
        return 71

    session_id, turn_id = operation["session_id"], operation["turn_id"]
    try:
        child = subprocess.run(
            [_resolve_powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", operation["command"]],
            cwd=Path.cwd(), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            env=_child_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        predictor = load_predictor()
        task_context = operation.get("task_context", {})

        def allocate(candidate_type: str, digest: str) -> str:
            response = post("/placeholder", {"session_id": session_id, "candidate_type": candidate_type, "fingerprint": digest})
            return str(response["placeholder"])

        def process(text: str, channel: str) -> ProcessedOutput:
            return process_output(
                text, session_id=session_id, turn_id=turn_id, operation_id=operation_id, channel=channel,
                task_context=task_context, predictor=predictor, allocate=allocate,
            )

        stdout_result = process(child.stdout, "stdout")
        stderr_result = process(child.stderr, "stderr")
        safe_stdout, safe_stderr = stdout_result.text, stderr_result.text
        all_candidates = [*stdout_result.candidates, *stderr_result.candidates]
        all_predictions = [*stdout_result.predictions, *stderr_result.predictions]
        _safe_event({
            "event": "runner_complete", "session_id": session_id, "turn_id": turn_id, "operation_id": operation_id,
            "status": "executed", "exit_code": child.returncode,
            "candidate_count": len(all_candidates), "candidate_types": [candidate.type for candidate in all_candidates],
            "actions": [prediction.action for prediction in all_predictions],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2), "marker_present": False,
        })
        _emit(operation_id, "executed", child.returncode, safe_stdout, safe_stderr)
        return child.returncode
    except Exception as exc:
        _safe_event({"event": "runner_failed", "session_id": session_id, "turn_id": turn_id, "operation_id": operation_id, "status": "blocked", "failure_kind": type(exc).__name__, "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
        _emit(operation_id, "blocked_pipeline_failure", 73, stderr="PromptGuard processing failed; output withheld.")
        return 73


if __name__ == "__main__":
    raise SystemExit(main())
