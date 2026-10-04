"""Run provenance: code version, dataset identity and environment. Never subprocess."""

from __future__ import annotations

import platform
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import evaluation
from evaluation.dataset.schema import Session

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def git_info(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Read HEAD and refs straight from .git. `dirty` needs a working-tree scan, so it is always null."""
    info: dict[str, Any] = {"commit": None, "branch": None, "dirty": None}
    git_dir = root / ".git"
    if git_dir.is_file():  # worktree or submodule: "gitdir: <path>"
        pointer = _read(git_dir) or ""
        if not pointer.startswith("gitdir:"):
            return info
        git_dir = (root / pointer.split(":", 1)[1].strip()).resolve()
    head = _read(git_dir / "HEAD")
    if not head:
        return info
    common = _read(git_dir / "commondir")
    common_dir = (git_dir / common).resolve() if common else git_dir
    if not head.startswith("ref:"):
        info["commit"] = head
        return info
    ref = head.split(":", 1)[1].strip()
    info["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    for directory in dict.fromkeys((git_dir, common_dir)):
        commit = _read(directory / ref)
        if commit:
            info["commit"] = commit
            return info
    for line in (_read(common_dir / "packed-refs") or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            info["commit"] = parts[0]
    return info


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def summarize_meta(sessions: Sequence[Session], max_values: int = 20) -> dict[str, Any]:
    """Per meta key: value counts for scalar values, or just the number of distinct values."""
    values: dict[str, list[Any]] = {}
    for session in sessions:
        for key, value in session.meta.items():
            values.setdefault(key, []).append(value)
    summary: dict[str, Any] = {}
    for key, seen in sorted(values.items()):
        scalar = all(isinstance(value, (str, int, float, bool)) or value is None for value in seen)
        counts = Counter(str(value) for value in seen) if scalar else None
        if counts is not None and len(counts) <= max_values:
            summary[key] = dict(sorted(counts.items()))
        else:
            summary[key] = {"sessions": len(seen), "distinct_values": len({repr(value) for value in seen})}
    return summary


def build_run_meta(
    *,
    started_at: datetime,
    system: dict[str, Any],
    thresholds: Sequence[float | None],
    dataset_path: str | Path,
    dataset_sha256: str,
    sessions: Sequence[Session],
    debug: bool,
) -> dict[str, Any]:
    return {
        "started_at": started_at.isoformat(timespec="seconds"),
        "git": git_info(),
        "system": system,
        "thresholds": list(thresholds),
        "debug": debug,
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_sha256,
            "sessions": len(sessions),
            "items": sum(len(session.items) for session in sessions),
            "gold_spans": sum(len(session.gold) for session in sessions),
            "meta_summary": summarize_meta(sessions),
        },
        "versions": {
            "evaluation": evaluation.__version__,
            "python": platform.python_version(),
            "credsweeper": _package_version("credsweeper"),
        },
        "platform": platform.platform(),
    }
