"""Write a run folder. Only debug/ may contain raw text; every other file holds offsets and counts."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.dataset.schema import CHANNELS, GOLD_TYPES
from evaluation.run import RunResult

Results = Sequence[tuple[float | None, RunResult]]


def create_run_dir(out_root: str | Path, label: str, now: datetime) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "run"
    base = Path(out_root) / f"{now:%Y%m%d-%H%M%S}_{safe}"
    candidate, suffix = base, 2
    while candidate.exists():
        candidate, suffix = base.with_name(f"{base.name}-{suffix}"), suffix + 1
    candidate.mkdir(parents=True)
    return candidate


def _dump(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _per_span(results: Results, sweep: bool) -> list[dict[str, Any]]:
    rows = []
    for threshold, result in results:
        for score in result.scores:
            for gold in score.gold_results:
                row = {"item_id": gold.item_id, "start": gold.start, "end": gold.end, "type": gold.type,
                       "channel": score.channel, "status": gold.status.value, "exposed_chars": gold.exposed_chars}
                rows.append({"threshold": threshold, **row} if sweep else row)
    return rows


def _per_edit(results: Results, sweep: bool) -> list[dict[str, Any]]:
    rows = []
    for threshold, result in results:
        for score in result.scores:
            for edit in score.edit_results:
                row = {"item_id": edit.item_id, "start": edit.start, "end": edit.end, "overlaps_gold": edit.overlaps_gold}
                rows.append({"threshold": threshold, **row} if sweep else row)
    return rows


def _write_curve(run_dir: Path, points: list[dict[str, Any]]) -> bool:
    columns = ["threshold", "precision", "recall", "f2", "fp_per_1k_lines"]
    with (run_dir / "pr_curve.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{key: ("" if point[key] is None else point[key]) for key in columns} for point in points])
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    plotted = [point for point in points if point["precision"] is not None and point["recall"] is not None]
    figure, axis = plt.subplots(figsize=(5, 4))
    axis.plot([p["recall"] for p in plotted], [p["precision"] for p in plotted], marker="o")
    for point in plotted:
        axis.annotate(f"{point['threshold']:g}", (point["recall"], point["precision"]), fontsize=7)
    axis.set_xlabel("Recall")
    axis.set_ylabel("Precision")
    axis.set_xlim(0, 1.02)
    axis.set_ylim(0, 1.02)
    axis.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(run_dir / "pr_curve.png", dpi=120)
    plt.close(figure)
    return True


def _metric_sections(metrics: dict[str, Any], level: str) -> list[str]:
    counts = metrics["counts"]
    latency = metrics["latency_ms"]
    lines = [
        f"{level} Primary metrics", "",
        "| Metric | Value |", "|---|---|",
        f"| Recall (span protection) | {fmt(metrics['recall'])} ({counts['full']}/{counts['gold_total']}) |",
        f"| Precision | {fmt(metrics['precision'])} ({counts['edits_tp']}/{counts['edits_total']}) |",
        "",
        f"{level} Secondary metrics", "",
        "| Metric | Value |", "|---|---|",
        f"| F2 | {fmt(metrics['f2'])} |",
        f"| Over-masking per 1,000 lines | {fmt(metrics['fp_per_1k_lines'], 2)} ({counts['edits_fp']} edits outside gold) |",
        f"| Character recall | {fmt(metrics['char_recall'])} |",
        f"| Partial exposure rate | {fmt(metrics['partial_rate'])} ({counts['partial']}) |",
        f"| Missed rate | {fmt(metrics['missed_rate'])} ({counts['missed']}) |",
        f"| Latency p50 / p95 / max (ms) | {fmt(latency['p50'], 2)} / {fmt(latency['p95'], 2)} / "
        f"{fmt(latency['max'], 2)} (n={latency['n']}) |",
        "",
        f"{level} Composition and recall by type", "",
        "| Type | Gold spans | Recall |", "|---|---|---|",
        *[f"| {kind} | {metrics['composition']['by_type'][kind]} | {fmt(metrics['recall_by_type'][kind])} |"
          for kind in GOLD_TYPES],
        "",
        f"{level} Composition and recall by channel", "",
        "| Channel | Gold spans | Recall |", "|---|---|---|",
        *[f"| {name} | {metrics['composition']['by_channel'][name]} | {fmt(metrics['recall_by_channel'][name])} |"
          for name in CHANNELS],
        "",
    ]
    return lines


def render_report(meta: dict[str, Any], results: Results, summary: dict[str, Any] | None) -> str:
    system = meta["system"]
    dataset = meta["dataset"]
    git = meta["git"]
    first = results[0][1].metrics
    settings = ", ".join(f"{key}={value}" for key, value in system.items() if key != "system")
    lines = [
        "# PromptGuard metric 1 report", "",
        f"- System: `{system.get('system')}`" + (f" ({settings})" if settings else ""),
        f"- Dataset: `{dataset['path']}` (sha256 `{dataset['sha256'][:12]}`): {dataset['sessions']} sessions, "
        f"{dataset['items']} items, {dataset['gold_spans']} gold spans",
        f"- Lines: {first['lines_total']}; secret density per 1,000 lines: {fmt(first['density_per_1k_lines'], 2)}",
        f"- Code: commit `{(git['commit'] or 'unknown')[:12]}` on `{git['branch'] or 'unknown'}`, "
        f"evaluation {meta['versions']['evaluation']}, started {meta['started_at']}",
        "",
    ]
    if meta["debug"]:
        lines += ["> **Warning:** this run used `--debug`. `debug/` contains raw text, including secrets. "
                  "Do not share or commit it.", ""]
    if summary is None:
        lines += _metric_sections(first, "##")
    else:
        lines += ["## Threshold sweep", "",
                  "| Threshold | Recall | Precision | F2 | Over-masking / 1k lines |", "|---|---|---|---|---|"]
        for threshold, result in results:
            m = result.metrics
            lines.append(f"| {threshold:g} | {fmt(m['recall'])} | {fmt(m['precision'])} | {fmt(m['f2'])} | "
                         f"{fmt(m['fp_per_1k_lines'], 2)} |")
        lines += ["", "## Summary metrics", "",
                  "Approximations that depend on the threshold grid; see `metrics.json` for the thresholds used.", "",
                  "| Metric | Value |", "|---|---|",
                  f"| PR-AUC | {fmt(summary['pr_auc'])} |"]
        for target, best in summary["precision_at_recall"].items():
            value = "N/A" if best is None else f"{fmt(best['precision'])} (threshold {best['threshold']:g})"
            lines.append(f"| Precision at recall ≥ {target} | {value} |")
        lines.append("")
        for threshold, result in results:
            lines += [f"## Threshold {threshold:g}", ""] + _metric_sections(result.metrics, "###")
    return "\n".join(lines)


def write_run(run_dir: Path, *, meta: dict[str, Any], results: Results, summary: dict[str, Any] | None,
              points: list[dict[str, Any]] | None = None, debug: bool = False) -> list[str]:
    """Write every result file; return the names written. `summary` is set for sweeps only."""
    sweep = summary is not None
    _dump(run_dir / "run_meta.json", meta)
    if sweep:
        _dump(run_dir / "metrics.json", {
            "thresholds": [threshold for threshold, _result in results],
            "summary": summary,
            "points": [{"threshold": threshold, **result.metrics} for threshold, result in results],
        })
    else:
        _dump(run_dir / "metrics.json", results[0][1].metrics)
    _jsonl(run_dir / "per_span.jsonl", _per_span(results, sweep))
    _jsonl(run_dir / "per_edit.jsonl", _per_edit(results, sweep))
    written = ["run_meta.json", "metrics.json", "per_span.jsonl", "per_edit.jsonl"]
    if sweep:
        written.append("pr_curve.csv")
        if _write_curve(run_dir, points or []):
            written.append("pr_curve.png")
    (run_dir / "report.md").write_text(render_report(meta, results, summary), encoding="utf-8")
    written.append("report.md")
    if debug:
        (run_dir / "debug").mkdir()
        rows = [
            {**({"threshold": threshold} if sweep else {}), "item_id": item_id, "debug": output.debug}
            for threshold, result in results
            for item_id, output in result.outputs.items()
            if output.debug is not None
        ]
        _jsonl(run_dir / "debug" / "items.jsonl", rows)
        written.append("debug/items.jsonl")
    return written
