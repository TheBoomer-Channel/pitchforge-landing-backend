"""SkillOpt Scorer — composite score function for evaluating codegen output quality.

TASK-067 — Evaluates codegen trajectories across 7 weighted dimensions:
compiles, imports_valid, tests_pass, endpoints_match, models_match,
no_orphan_code, lint_clean.
"""

import ast
import logging
import re
from pathlib import Path
from typing import Optional

from .skillopt_config import DEFAULT_SCORE_WEIGHTS

logger = logging.getLogger(__name__)


class CodegenTrajectory:
    """Tracks the output of a single codegen run for scoring."""

    def __init__(
        self,
        idea: str,
        output_dir: str,
        generated_files: list[str],
        expected_features: Optional[list[str]] = None,
        expected_models: Optional[list[str]] = None,
        expected_endpoints: Optional[list[str]] = None,
    ):
        self.idea = idea
        self.output_dir = Path(output_dir)
        self.generated_files = [Path(f) for f in generated_files]
        self.expected_features = expected_features or []
        self.expected_models = expected_models or []
        self.expected_endpoints = expected_endpoints or []
        self.scores: dict[str, float] = {}

    @property
    def total_score(self) -> float:
        if not self.scores:
            return 0.0
        weights = DEFAULT_SCORE_WEIGHTS
        return sum(
            weights.get(k, 0.0) * v for k, v in self.scores.items()
        )


def compute_score(trajectory: CodegenTrajectory) -> dict[str, float]:
    """Compute composite score (0.0-1.0) for a codegen trajectory.

    Returns dict of individual scores + 'total'.
    """
    scores = {}

    scores["compiles"] = _check_compiles(trajectory)
    scores["imports_valid"] = _check_imports(trajectory)
    scores["tests_pass"] = _check_tests(trajectory)
    scores["endpoints_match"] = _check_endpoints(trajectory)
    scores["models_match"] = _check_models(trajectory)
    scores["no_orphan_code"] = _check_orphan_code(trajectory)
    scores["lint_clean"] = _check_lint(trajectory)

    weights = DEFAULT_SCORE_WEIGHTS
    total = sum(weights.get(k, 0.0) * v for k, v in scores.items())
    scores["total"] = round(total, 4)

    trajectory.scores = scores
    return scores


# ── Individual Checks ──────────────────────────────────


def _check_compiles(traj: CodegenTrajectory) -> float:
    """Check if Python files are syntactically valid."""
    py_files = [f for f in traj.generated_files if f.suffix == ".py"]
    if not py_files:
        return 0.0
    valid = 0
    for pf in py_files:
        try:
            if pf.exists():
                source = pf.read_text()
                ast.parse(source)
                valid += 1
        except SyntaxError:
            logger.debug(f"Syntax error in {pf}")
    return round(valid / len(py_files), 4)


def _check_imports(traj: CodegenTrajectory) -> float:
    """Check if all imports reference files that exist."""
    py_files = [f for f in traj.generated_files if f.suffix == ".py"]
    if not py_files:
        return 0.0

    valid_count = 0
    total_imports = 0

    for pf in py_files:
        if not pf.exists():
            continue
        try:
            tree = ast.parse(pf.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    total_imports += 1
                    # Simple heuristic: check if module name looks valid
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if _module_looks_valid(alias.name, traj):
                                valid_count += 1
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and _module_looks_valid(node.module, traj):
                            valid_count += 1
        except SyntaxError:
            pass

    if total_imports == 0:
        return 1.0  # No imports = no invalid imports
    return round(valid_count / total_imports, 4)


def _module_looks_valid(module_name: str, traj: CodegenTrajectory) -> bool:
    """Heuristic: is the module import likely valid?

    For local imports (starting with '.'), check if referenced files exist.
    For third-party imports, just check they're not obviously invalid.
    """
    # Standard library / third-party — assume valid
    if not module_name.startswith("."):
        # Known bad patterns
        if module_name.lower() in ("", "none", "null", "undefined", "unknown"):
            return False
        # Check for obviously typo'd module names (mixed separators, double dots)
        if ".." in module_name or "/" in module_name or "\\" in module_name:
            return False
        return True

    # Relative imports — check if target module likely exists
    # Known relative import patterns: .models, ..utils, .routes.user
    cleaned = module_name.lstrip(".")
    if cleaned:
        # Check if any generated file matches the relative path
        expected_name = cleaned.replace(".", "/") + ".py"
        for gf in traj.generated_files:
            if str(gf).endswith(expected_name):
                return True
        # If no match found among generated files, check if the
        # module name looks like a valid Python identifier
        parts = cleaned.split(".")
        if all(p.isidentifier() for p in parts):
            return True  # Plausible relative import
        return False
    return True  # Bare '.' import (unlikely but valid)


def _check_tests(traj: CodegenTrajectory) -> float:
    """Check if test files are syntactically valid and match expected structure."""
    test_files = [f for f in traj.generated_files if "test" in f.name.lower() or "test" in str(f.parent).lower()]
    if not test_files:
        # No test files generated at all
        return 0.0

    valid = 0
    for tf in test_files:
        if tf.exists() and tf.suffix == ".py":
            try:
                tree = ast.parse(tf.read_text())
                # Count test functions
                test_funcs = [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name.startswith("test_")
                ]
                if test_funcs:
                    valid += 1
            except SyntaxError:
                pass

    return round(valid / max(len(test_files), 1), 4)


def _check_endpoints(traj: CodegenTrajectory) -> float:
    """Check if generated endpoints match expected endpoints."""
    if not traj.expected_endpoints:
        return 1.0  # No expectations = perfect match

    route_files = [
        f
        for f in traj.generated_files
        if f.suffix == ".py"
        and ("routes" in str(f) or "router" in str(f) or "endpoint" in str(f))
    ]

    found_endpoints = set()
    for rf in route_files:
        if rf.exists():
            try:
                content = rf.read_text()
                # Find route decorators: @router.get("..."), @router.post("..."), etc.
                routes = re.findall(
                    r'@router\.(\w+)\s*\(\s*["\']([^"\']+)["\']', content
                )
                for method, path in routes:
                    found_endpoints.add(f"{method.upper()} {path}")

                # Also find @app.get etc.
                app_routes = re.findall(
                    r'@app\.(\w+)\s*\(\s*["\']([^"\']+)["\']', content
                )
                for method, path in app_routes:
                    found_endpoints.add(f"{method.upper()} {path}")

                # And standalone decorators like @router.delete
                standalone = re.findall(r'@router\.(\w+)', content)
                for method in standalone:
                    paths = re.findall(r'["\']([^"\']+)["\']', content)
                    if paths:
                        found_endpoints.add(f"{method.upper()} {paths[0]}")

            except Exception:
                pass

    expected_set = set(e.upper().replace(" ", " ") for e in traj.expected_endpoints)

    if not found_endpoints or not expected_set:
        return 0.5 if found_endpoints else 0.0

    # Jaccard similarity
    intersection = len(found_endpoints & expected_set)
    union = len(found_endpoints | expected_set)
    return round(intersection / union, 4)


def _check_models(traj: CodegenTrajectory) -> float:
    """Check if generated models match expected models."""
    if not traj.expected_models:
        return 1.0

    model_files = [
        f
        for f in traj.generated_files
        if f.suffix == ".py"
        and ("model" in str(f).lower() or "schema" in str(f).lower())
    ]

    found_models = set()
    for mf in model_files:
        if mf.exists():
            try:
                tree = ast.parse(mf.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        found_models.add(node.name)
            except SyntaxError:
                pass

    expected_set = set(m.lower() for m in traj.expected_models)
    found_set = set(m.lower() for m in found_models)

    if not expected_set:
        return 1.0

    # Check how many expected models are found
    matches = sum(1 for em in expected_set if any(em in fm for fm in found_set))
    return round(matches / len(expected_set), 4)


def _check_orphan_code(traj: CodegenTrajectory) -> float:
    """Check for orphaned code: unused imports, dead functions, empty files."""
    py_files = [f for f in traj.generated_files if f.suffix == ".py"]
    if not py_files:
        return 1.0

    issues = 0
    for pf in py_files:
        if not pf.exists():
            continue
        try:
            content = pf.read_text()
            tree = ast.parse(content)

            # Check for empty function bodies (just 'pass')
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    body = node.body
                    if len(body) == 1 and isinstance(body[0], ast.Pass):
                        issues += 1

            # Check for TODO/FIXME/XXX comments suggesting incomplete code
            todo_count = len(re.findall(r"#\s*(TODO|FIXME|XXX|HACK)", content))
            issues += todo_count * 0.5

        except SyntaxError:
            issues += 1  # Syntax error = definitely orphaned/problematic

    # Score: 1.0 - (issues / (files * 3)), normalized
    normalized = min(issues / (len(py_files) * 3), 1.0)
    return round(1.0 - normalized, 4)


def _check_lint(traj: CodegenTrajectory) -> float:
    """Check for common lint issues in generated code."""
    py_files = [f for f in traj.generated_files if f.suffix == ".py"]
    if not py_files:
        return 1.0

    lint_issues = 0
    for pf in py_files:
        if not pf.exists():
            continue
        try:
            content = pf.read_text()

            # Check for trailing whitespace
            if re.search(r"[ \t]+$", content, re.MULTILINE):
                lint_issues += 1

            # Check for multiple blank lines (>2)
            if re.search(r"\n\n\n+", content):
                lint_issues += 0.5

            # Check for lines > 120 chars
            for line in content.split("\n"):
                if len(line) > 120:
                    lint_issues += 0.2
                    break

            # Check for mixed tabs/spaces (per-line, not whole file)
            has_tab_indent = False
            has_space_indent = False
            for line in content.split("\n"):
                if line.startswith("\t"):
                    has_tab_indent = True
                elif line.startswith(" "):
                    has_space_indent = True
            if has_tab_indent and has_space_indent:
                lint_issues += 1

            # Check for bare except
            if re.search(r"except\s*:", content):
                lint_issues += 0.5

        except Exception:
            pass

    normalized = min(lint_issues / (len(py_files) * 4), 1.0)
    return round(1.0 - normalized, 4)
