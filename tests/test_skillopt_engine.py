"""Tests for skillopt.py — EditOperation apply, rejection buffer, SkillOpt engine."""

import pytest
from app.devkit.skillopt import EditOperation, OptimizationResult, SkillOpt
from app.devkit.skillopt_config import SkillOptConfig


class TestEditOperation:
    """Test bounded edits: add, delete, replace."""

    def test_add_edit_appends_to_section(self):
        """ADD edits should insert new text after target section header."""
        skill = "## Data model generation\n\nSome content.\n\n## API codegen\n\nMore content.\n"
        edit = EditOperation(
            op_type="add",
            target_section="Data model generation",
            new_text="**NEW RULE:** Always use Optional[] for nullable fields.\n",
            reasoning="Prevent missing nullable wrappers",
        )
        result = edit.apply(skill)
        assert "**NEW RULE:** Always use Optional[]" in result
        assert "Data model generation" in result
        # Should appear after the Data model section header
        idx_section = result.index("Data model generation")
        idx_rule = result.index("**NEW RULE:**")
        assert idx_rule > idx_section

    def test_add_edit_appends_to_end_when_section_not_found(self):
        """ADD edits should append to end if target section not found."""
        skill = "## Some other section\n\nContent.\n"
        edit = EditOperation(
            op_type="add",
            target_section="Nonexistent Section",
            new_text="Appended rule.\n",
        )
        result = edit.apply(skill)
        assert "Appended rule." in result
        # Should be near the end
        assert result.strip().endswith("Appended rule.")

    def test_delete_edit_removes_text(self):
        """DELETE edits should remove old_text from skill."""
        skill = "## Section\n\nSome content.\n\n## Old pattern\n\nBAD: Do not use this pattern.\n\n## More\n"
        edit = EditOperation(
            op_type="delete",
            target_section="Old pattern",
            old_text="BAD: Do not use this pattern.",
        )
        result = edit.apply(skill)
        assert "BAD: Do not use this pattern." not in result

    def test_replace_edit_substitutes_text(self):
        """REPLACE edits should replace old_text with new_text."""
        skill = "## Section\n\nAlways use response_model=None for 204 routes.\n"
        edit = EditOperation(
            op_type="replace",
            target_section="Section",
            old_text="Always use response_model=None for 204 routes.",
            new_text="For 204 routes, return Response(status_code=204) explicitly.",
        )
        result = edit.apply(skill)
        assert "Response(status_code=204)" in result
        assert "response_model=None" not in result

    def test_edit_to_dict(self):
        """EditOperation.to_dict() should produce valid dict."""
        edit = EditOperation(
            op_type="replace",
            target_section="API codegen",
            old_text="old pattern",
            new_text="new pattern",
            expected_utility=0.8,
            reasoning="Better pattern",
        )
        d = edit.to_dict()
        assert d["op_type"] == "replace"
        assert d["target_section"] == "API codegen"
        assert d["expected_utility"] == 0.8
        assert "old pattern" in d["old_text"]

    def test_invalid_edit_type_raises(self):
        """Invalid op_type should raise ValueError."""
        with pytest.raises(ValueError):
            EditOperation(op_type="invalid", target_section="x")

    def test_add_with_empty_new_text_does_nothing(self):
        """ADD with empty new_text should not modify skill."""
        skill = "## Section\n\nContent.\n"
        edit = EditOperation(op_type="add", target_section="Section", new_text="")
        result = edit.apply(skill)
        assert result.rstrip() == skill.rstrip()

    def test_delete_with_empty_old_text_does_nothing(self):
        """DELETE with empty old_text should not modify skill."""
        skill = "## Section\n\nContent.\n"
        edit = EditOperation(op_type="delete", target_section="Section", old_text="")
        result = edit.apply(skill)
        assert result.rstrip() == skill.rstrip()

    def test_replace_with_empty_old_text_does_nothing(self):
        """REPLACE with empty old_text should not modify skill."""
        skill = "## Section\n\nContent.\n"
        edit = EditOperation(
            op_type="replace", target_section="Section", old_text="", new_text="new"
        )
        result = edit.apply(skill)
        assert result.rstrip() == skill.rstrip()


class TestOptimizationResult:
    """Test OptimizationResult metrics tracking."""

    def test_default_values(self):
        result = OptimizationResult(skill_name="test-skill")
        assert result.skill_name == "test-skill"
        assert result.initial_score == 0.0
        assert result.final_score == 0.0
        assert result.improvement == 0.0
        assert result.total_accepted_edits == 0

    def test_improvement_calculation(self):
        result = OptimizationResult(
            skill_name="test",
            initial_score=0.65,
            final_score=0.78,
        )
        assert result.improvement == 0.13

    def test_duration_requires_timestamps(self):
        result = OptimizationResult(skill_name="test")
        assert result.duration_seconds == 0.0

    def test_to_dict_includes_all_fields(self):
        result = OptimizationResult(
            skill_name="test",
            initial_score=0.5,
            final_score=0.7,
            best_score=0.75,
            total_accepted_edits=5,
            total_rejected_edits=3,
            meta_patterns=["pattern 1"],
            started_at="2026-06-15T00:00:00",
            finished_at="2026-06-15T00:05:00",
        )
        d = result.to_dict()
        assert d["skill_name"] == "test"
        assert d["improvement"] == 0.2
        assert d["total_accepted_edits"] == 5
        assert d["meta_patterns"] == ["pattern 1"]


class TestSkillOptConfig:
    """Minimal config tests for SkillOpt integration."""

    def test_config_to_dict(self):
        config = SkillOptConfig(
            skill_path="/tmp/test.py",
            skill_name="test-skill",
            epochs=2,
            minibatch_size=4,
        )
        d = config.to_dict()
        assert d["skill_name"] == "test-skill"
        assert d["epochs"] == 2

    def test_config_output_dir_auto(self):
        config = SkillOptConfig(skill_path="/tmp/test.py", skill_name="test")
        assert "skillopt_runs" in config.output_dir
        assert "test" in config.output_dir
