from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "evaluation"
PROMPTGUARD = ROOT / "promptguard"

ALLOWED_PROMPTGUARD = {
    "promptguard.pipeline",
    "promptguard.redaction.engine",
    "promptguard.redaction.placeholders",
    "promptguard.decision.registry",
    "promptguard.decision.base",
    "promptguard.common.schema",
}
FORBIDDEN_EVERYWHERE = ("subprocess", "socket", "urllib", "http")


def imported_modules(path: Path) -> set[str]:
    """Absolute names of every module imported anywhere in the file (relative imports resolved)."""
    package = list(path.relative_to(ROOT).parent.parts)
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join(base + ([node.module] if node.module else []))
            modules.add(module)
            # `from promptguard import pipeline` imports the submodule promptguard.pipeline.
            for alias in node.names:
                target = ROOT.joinpath(*module.split("."), alias.name)
                if target.is_dir() or target.with_suffix(".py").is_file():
                    modules.add(f"{module}.{alias.name}")
    return modules


def _top(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def source_files(root: Path, exclude_tests: bool = True) -> list[Path]:
    return [path for path in root.rglob("*.py") if not (exclude_tests and "tests" in path.relative_to(root).parts)]


class DependencyRuleTests(unittest.TestCase):
    def test_only_adapters_import_promptguard(self) -> None:
        for path in source_files(EVALUATION):
            if path.relative_to(EVALUATION).parts[0] == "adapters":
                continue
            offending = [name for name in imported_modules(path) if _top(name, "promptguard")]
            self.assertEqual(offending, [], str(path))

    def test_adapters_import_only_allowed_promptguard_modules(self) -> None:
        for path in source_files(EVALUATION / "adapters"):
            offending = {name for name in imported_modules(path) if _top(name, "promptguard")} - ALLOWED_PROMPTGUARD
            self.assertEqual(offending, set(), str(path))

    def test_promptguard_does_not_import_evaluation(self) -> None:
        for path in source_files(PROMPTGUARD, exclude_tests=False):
            self.assertEqual([name for name in imported_modules(path) if _top(name, "evaluation")], [], str(path))

    def test_no_subprocess_or_network(self) -> None:
        for path in source_files(EVALUATION):
            offending = [name for name in imported_modules(path) if any(_top(name, bad) for bad in FORBIDDEN_EVERYWHERE)]
            self.assertEqual(offending, [], str(path))


if __name__ == "__main__":
    unittest.main()
