"""Tests for skillopt_scorer.py — 7-dimension composite score function."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.devkit.skillopt_scorer import (
    CodegenTrajectory,
    compute_score,
    _check_compiles,
    _check_imports,
    _check_tests,
    _check_models,
    _check_orphan_code,
    _check_lint,
)


class TestCodegenTrajectory:
    def test_default_scores(self):
        traj = CodegenTrajectory(idea="Test", output_dir="/tmp/test", generated_files=[])
        assert traj.total_score == 0.0
        assert traj.scores == {}

    def test_total_score_computation(self):
        traj = CodegenTrajectory(idea="Test", output_dir="/tmp/test", generated_files=[])
        traj.scores = {
            "compiles": 0.9,
            "imports_valid": 0.8,
            "tests_pass": 0.7,
            "endpoints_match": 0.6,
            "models_match": 0.5,
            "no_orphan_code": 0.4,
            "lint_clean": 0.3,
        }
        expected = (
            0.30 * 0.9 + 0.15 * 0.8 + 0.20 * 0.7
            + 0.15 * 0.6 + 0.10 * 0.5 + 0.05 * 0.4 + 0.05 * 0.3
        )
        assert abs(traj.total_score - expected) < 0.01


class TestCompilesCheck:
    def test_valid_python(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "valid.py"
            p.write_text("def foo():\n    return 42\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_compiles(traj) == 1.0

    def test_syntax_error(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "invalid.py"
            p.write_text("def foo(\n    return ???\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_compiles(traj) == 0.0

    def test_empty_files(self):
        traj = CodegenTrajectory("idea", "/tmp", [])
        assert _check_compiles(traj) == 0.0

    def test_mixed_valid_invalid(self):
        with TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "good.py"
            p1.write_text("x = 1\n")
            p2 = Path(tmp) / "bad.py"
            p2.write_text("x = \n")
            traj = CodegenTrajectory("idea", tmp, [str(p1), str(p2)])
            assert _check_compiles(traj) == 0.5


class TestImportsCheck:
    def test_standard_imports(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "mod.py"
            p.write_text("import os\nfrom typing import Optional\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_imports(traj) == 1.0

    def test_bad_module_names(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.py"
            p.write_text("import none\nfrom null import foo\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_imports(traj)
            assert score < 1.0

    def test_no_py_files_returns_zero(self):
        """_check_imports returns 0.0 when there are no .py files."""
        traj = CodegenTrajectory("idea", "/tmp", [])
        assert _check_imports(traj) == 0.0


class TestTestsCheck:
    def test_has_test_functions(self):
        with TemporaryDirectory() as tmp:
            td = Path(tmp) / "tests"
            td.mkdir()
            p = td / "test_foo.py"
            p.write_text("def test_something():\n    assert True\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_tests(traj) == 1.0

    def test_no_test_file(self):
        traj = CodegenTrajectory("idea", "/tmp", [])
        assert _check_tests(traj) == 0.0

    def test_file_without_test_prefix(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "utils.py"
            p.write_text("def helper():\n    pass\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_tests(traj) == 0.0


class TestModelsCheck:
    def test_models_exact_match(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "models/user.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("class User:\n    pass\nclass Session:\n    pass\n")
            traj = CodegenTrajectory(
                "idea", tmp, [str(p)],
                expected_models=["User", "Session"],
            )
            assert _check_models(traj) == 1.0

    def test_models_partial_match(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "models/user.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("class User:\n    pass\n")
            traj = CodegenTrajectory(
                "idea", tmp, [str(p)],
                expected_models=["User", "Admin", "Log"],
            )
            # 1 of 3 expected models found → 1/3, rounded to 4 decimal places
            assert _check_models(traj) == 0.3333

    def test_no_expected_models(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "models/x.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("class Foo:\n    pass\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_models(traj) == 1.0


class TestOrphanCodeCheck:
    def test_clean_code(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "clean.py"
            p.write_text("def foo():\n    return 42\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_orphan_code(traj) == 1.0

    def test_pass_only_function(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "stub.py"
            p.write_text("def foo():\n    pass\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_orphan_code(traj)
            assert score < 1.0  # Penalized for pass-only function

    def test_todo_comments(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "todo.py"
            p.write_text("# TODO: implement this\ndef foo():\n    return 1\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_orphan_code(traj)
            assert score < 1.0


class TestLintCheck:
    def test_clean_code(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "clean.py"
            p.write_text("def foo():\n    return 42\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            assert _check_lint(traj) == 1.0

    def test_trailing_spaces(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "trailing.py"
            p.write_text("def foo():   \n    return 42\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_lint(traj)
            assert score < 1.0

    def test_bare_except(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "bare_except.py"
            p.write_text("try:\n    1/0\nexcept:\n    pass\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_lint(traj)
            assert score < 1.0

    def test_long_lines(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "long.py"
            p.write_text("x = " + "a" * 130 + "\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_lint(traj)
            assert score < 1.0

    def test_mixed_tabs_spaces(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "mixed.py"
            p.write_text("\tdef foo():\n    return 42\n")
            traj = CodegenTrajectory("idea", tmp, [str(p)])
            score = _check_lint(traj)
            assert score < 1.0


class TestComputeScore:
    def test_perfect_score(self):
        with TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "mod.py"
            p1.write_text("import os\n\ndef hello():\n    return 'world'\n")
            td = Path(tmp) / "tests"
            td.mkdir()
            p2 = td / "test_mod.py"
            p2.write_text("def test_hello():\n    assert True\n")
            traj = CodegenTrajectory(
                "idea", tmp, [str(p1), str(p2)],
                expected_models=["mod"],
                expected_endpoints=["GET /hello"],
            )
            scores = compute_score(traj)
            assert "total" in scores
            assert 0.0 <= scores["total"] <= 1.0
            assert scores["compiles"] == 1.0
            assert scores["no_orphan_code"] == 1.0

    def test_zero_score_on_empty(self):
        traj = CodegenTrajectory("idea", "/tmp/empty", [])
        scores = compute_score(traj)
        # compiles=0, imports=0 (0 py files), tests=0, endpoints=1.0, models=1.0, orphan=1.0, lint=1.0
        # Total = 0.30*0 + 0.15*0 + 0.20*0 + 0.15*1 + 0.10*1 + 0.05*1 + 0.05*1 = 0.35
        assert scores["total"] == pytest.approx(0.35)
