"""Detection → decision → redaction assembly shared by the runner and evaluation.

Keep this module free of PowerShell, subprocess and transport (HTTP) imports so the
evaluation harness can call the exact runtime assembly on Linux or in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from promptguard.common.schema import Candidate, Prediction
from promptguard.decision.base import Predictor
from promptguard.redaction.engine import Edit, PlaceholderAllocator, redact


# Input channels this system actually redacts: Bash tool stdout/stderr only. The user
# prompt and AGENTS.md reach the model unprocessed. Evaluation reads this list to decide
# which inputs pass through the system, so it must never claim more than the runtime does.
# Keep in sync with the hook matcher ('^Bash$') in scripts/run_codex_demo.ps1 and change
# both together when adding a channel.
PROCESSED_CHANNELS: tuple[str, ...] = ("stdout", "stderr")


@dataclass(frozen=True)
class ProcessedOutput:
    text: str
    candidates: list[Candidate]
    predictions: list[Prediction]
    edits: list[Edit]  # (start, end, replacement) against the original text


def build_task_context(prompt: str, turn_id: str) -> dict[str, Any]:
    """The task_context handed to Predictor.predict, as the daemon stores it per operation."""
    return {"prompt": prompt, "turn_id": turn_id}


def process_output(
    text: str,
    *,
    session_id: str,
    turn_id: str,
    operation_id: str,
    channel: str,
    task_context: dict[str, Any],
    predictor: Predictor,
    allocate: PlaceholderAllocator,
) -> ProcessedOutput:
    if channel not in PROCESSED_CHANNELS:
        raise ValueError(f"channel {channel!r} is not processed by PromptGuard; expected one of {PROCESSED_CHANNELS}")
    # Deferred so callers (the runner before claim, the daemon) avoid importing CredSweeper
    # and its heavier dependencies until output actually needs scanning.
    from promptguard.detector.rules import detect_candidates

    candidates = detect_candidates(text, session_id=session_id, turn_id=turn_id, operation_id=operation_id, channel=channel)
    predictions = predictor.predict(candidates, task_context)
    safe_text, edits = redact(text, candidates, predictions, allocate)
    return ProcessedOutput(safe_text, candidates, predictions, edits)
