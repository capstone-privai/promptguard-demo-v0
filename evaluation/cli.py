"""Command line entry point: `python -m evaluation validate|run ...`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from evaluation.adapters.base import SystemUnderTest
from evaluation.dataset.validate import validate_dataset
from evaluation.dataset.io import load_sessions
from evaluation.run import DatasetInvalidError, RunResult, ScoringError, evaluate_sessions, load_dataset

EXIT_OK = 0
EXIT_DATASET = 1
EXIT_SCORING = 2
EXIT_CONFIG = 3

SYSTEMS = ("oracle", "identity")

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
    run = commands.add_parser("run", help="run a system over a dataset and score it")
    run.add_argument("--dataset", required=True)
    run.add_argument("--system", required=True, choices=SYSTEMS)
    run.add_argument("--out", default="runs")
    run.add_argument("--debug", action="store_true", help="also write raw candidates/predictions (may contain secrets)")
    return parser


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def summary_line(metrics: dict[str, Any]) -> str:
    return (
        f"recall={fmt(metrics['recall'])} precision={fmt(metrics['precision'])} f2={fmt(metrics['f2'])} "
        f"fp_per_1k_lines={fmt(metrics['fp_per_1k_lines'], 2)} gold={metrics['counts']['gold_total']} "
        f"density_per_1k_lines={fmt(metrics['density_per_1k_lines'], 2)}"
    )


def adapter_factory(args: argparse.Namespace) -> AdapterFactory:
    if args.system == "oracle":
        from evaluation.adapters.reference import OracleAdapter

        return lambda _threshold: OracleAdapter()
    if args.system == "identity":
        from evaluation.adapters.reference import IdentityAdapter

        return lambda _threshold: IdentityAdapter()
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
    thresholds: Sequence[float | None] = (None,),
    out: TextIO | None = None,
) -> int:
    """Run and score; adapters are injected so tests can exercise every exit path."""
    out = out or sys.stdout
    try:
        sessions = load_dataset(dataset)
    except DatasetInvalidError as exc:
        for issue in exc.issues:
            print(issue, file=out)
        print(f"dataset invalid: {len(exc.issues)} issue(s); nothing was run", file=out)
        return EXIT_DATASET
    results: list[tuple[float | None, RunResult]] = []
    for threshold in thresholds:
        try:
            adapter = make_adapter(threshold)
        except (ConfigError, ValueError) as exc:
            print(f"configuration error: {exc}", file=out)
            return EXIT_CONFIG
        try:
            results.append((threshold, evaluate_sessions(sessions, adapter)))
        except ScoringError as exc:
            print(f"scoring failed: {exc}", file=out)
            print("no results were written", file=out)
            return EXIT_SCORING
    for threshold, result in results:
        prefix = "" if threshold is None else f"threshold={threshold:g} "
        print(prefix + summary_line(result.metrics), file=out)
    return EXIT_OK


def main(argv: Sequence[str] | None = None, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    try:
        args = build_parser().parse_args(argv)
        if args.command == "validate":
            return _validate(args.dataset, out)
        make_adapter = adapter_factory(args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=out)
        return EXIT_CONFIG
    return execute_run(args.dataset, make_adapter, out=out)
