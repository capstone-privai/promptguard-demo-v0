"""Command line entry point: `python -m evaluation validate|run ...`.

Exit codes: 0 ok, 1 invalid dataset, 2 edit verification failed, 3 configuration error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from evaluation.adapters.base import SystemUnderTest
from evaluation.dataset.io import dataset_sha256, load_sessions
from evaluation.dataset.validate import validate_dataset
from evaluation.report.meta import build_run_meta
from evaluation.report.sweep import curve_points, parse_range, run_thresholds, summarize
from evaluation.report.write import create_run_dir, fmt, write_run
from evaluation.run import DatasetInvalidError, ScoringError, load_dataset

EXIT_OK = 0
EXIT_DATASET = 1
EXIT_SCORING = 2
EXIT_CONFIG = 3

SYSTEMS = ("promptguard", "credsweeper", "oracle", "identity")

AdapterFactory = Callable[[float | None], SystemUnderTest]


class ConfigError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse would exit 2, which means a scoring failure here
        raise ConfigError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m evaluation", description="PromptGuard metric 1 evaluation")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    validate = commands.add_parser("validate", help="check a dataset's format")
    validate.add_argument("--dataset", required=True)
    run = commands.add_parser("run", help="run a system over a dataset, score it and write a run folder")
    run.add_argument("--dataset", required=True)
    run.add_argument("--system", required=True, choices=SYSTEMS)
    run.add_argument("--predictor", help="predictor name for --system promptguard (default: mock)")
    thresholds = run.add_mutually_exclusive_group()
    thresholds.add_argument("--threshold", type=float, help="MASK iff confidence >= T (promptguard only)")
    thresholds.add_argument("--sweep", metavar="START:STOP:STEP", help="run once per threshold (promptguard only)")
    run.add_argument("--ml", choices=("on", "off"), help="CredSweeper ML validation (credsweeper only; default: off)")
    run.add_argument("--out", default="runs", help="parent folder for run folders (default: runs)")
    run.add_argument("--debug", action="store_true", help="also write debug/ with raw candidates (contains secrets)")
    return parser


def summary_line(metrics: dict[str, Any]) -> str:
    return (
        f"recall={fmt(metrics['recall'])} precision={fmt(metrics['precision'])} f2={fmt(metrics['f2'])} "
        f"fp_per_1k_lines={fmt(metrics['fp_per_1k_lines'], 2)} gold={metrics['counts']['gold_total']} "
        f"density_per_1k_lines={fmt(metrics['density_per_1k_lines'], 2)}"
    )


def adapter_factory(args: argparse.Namespace) -> tuple[AdapterFactory, str]:
    """Return a threshold → adapter factory and the run folder label."""
    if args.system != "promptguard" and (args.predictor or args.threshold is not None or args.sweep):
        raise ConfigError("--predictor, --threshold and --sweep apply to --system promptguard only")
    if args.system != "credsweeper" and args.ml:
        raise ConfigError("--ml applies to --system credsweeper only")
    if args.system == "promptguard":
        from evaluation.adapters.promptguard_adapter import PromptGuardAdapter

        predictor = args.predictor or "mock"
        return (lambda threshold: PromptGuardAdapter(predictor, threshold=threshold, debug=args.debug)), f"promptguard_{predictor}"
    if args.system == "credsweeper":
        from evaluation.adapters.credsweeper_adapter import CredSweeperAdapter

        ml = args.ml == "on"
        return (lambda _threshold: CredSweeperAdapter(ml=ml)), f"credsweeper_ml-{'on' if ml else 'off'}"
    if args.system == "oracle":
        from evaluation.adapters.reference import OracleAdapter

        return (lambda _threshold: OracleAdapter()), "oracle"
    if args.system == "identity":
        from evaluation.adapters.reference import IdentityAdapter

        return (lambda _threshold: IdentityAdapter()), "identity"
    raise ConfigError(f"unknown system {args.system!r}")


def _validate(dataset: str, out: TextIO) -> int:
    issues = validate_dataset(dataset)
    if issues:
        for issue in issues:
            print(issue, file=out)
        print(f"{len(issues)} issue(s) found", file=out)
        return EXIT_DATASET
    sessions = load_sessions(dataset)
    items = sum(len(session.items) for session in sessions)
    gold = sum(len(session.gold) for session in sessions)
    print(f"OK: {len(sessions)} sessions, {items} items, {gold} gold spans", file=out)
    return EXIT_OK


def execute_run(
    dataset: str,
    make_adapter: AdapterFactory,
    *,
    label: str = "run",
    thresholds: Sequence[float | None] = (None,),
    sweep: bool = False,
    out_root: str | Path = "runs",
    debug: bool = False,
    out: TextIO | None = None,
) -> int:
    """Validate, run, score and write. Adapters are injected so tests can reach every exit path."""
    out = out or sys.stdout
    started_at = datetime.now()
    try:
        sessions = load_dataset(dataset)
    except DatasetInvalidError as exc:
        for issue in exc.issues:
            print(issue, file=out)
        print(f"dataset invalid: {len(exc.issues)} issue(s); nothing was run", file=out)
        return EXIT_DATASET

    def build(threshold: float | None) -> SystemUnderTest:
        try:
            return make_adapter(threshold)
        except (ConfigError, ValueError) as exc:
            raise ConfigError(str(exc)) from exc

    try:
        results = run_thresholds(sessions, thresholds, build)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=out)
        return EXIT_CONFIG
    except ScoringError as exc:
        print(f"scoring failed: {exc}", file=out)
        print("no results were written", file=out)
        return EXIT_SCORING

    points = curve_points(results) if sweep else None
    summary = summarize(points) if points is not None else None
    meta = build_run_meta(started_at=started_at, system=results[0][1].system, thresholds=list(thresholds),
                          dataset_path=dataset, dataset_sha256=dataset_sha256(dataset), sessions=sessions, debug=debug)
    run_dir = create_run_dir(out_root, label, started_at)
    write_run(run_dir, meta=meta, results=results, summary=summary, points=points, debug=debug)
    print(f"results: {run_dir}", file=out)
    for threshold, result in results:
        prefix = "" if threshold is None else f"threshold={threshold:g} "
        print(prefix + summary_line(result.metrics), file=out)
    if summary is not None:
        at = {target: None if best is None else fmt(best["precision"]) for target, best in summary["precision_at_recall"].items()}
        print(f"pr_auc={fmt(summary['pr_auc'])} precision_at_recall={at}", file=out)
    if debug:
        print("warning: debug/ contains raw text including secrets; do not share or commit it", file=out)
    return EXIT_OK


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    try:
        args = build_parser().parse_args(argv)
        if args.command == "validate":
            return _validate(args.dataset, out)
        make_adapter, label = adapter_factory(args)
        thresholds: list[float | None] = parse_range(args.sweep) if args.sweep else [args.threshold]
    except (ConfigError, ValueError) as exc:
        print(f"configuration error: {exc}", file=out)
        return EXIT_CONFIG
    return execute_run(args.dataset, make_adapter, label=label, thresholds=thresholds, sweep=bool(args.sweep),
                       out_root=args.out, debug=args.debug, out=out)
