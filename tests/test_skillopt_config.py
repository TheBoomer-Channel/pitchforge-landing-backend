"""Tests for skillopt_config.py — decay schedules, seeded patterns, config validation."""

import pytest
from app.devkit.skillopt_config import (
    SkillOptConfig,
    DEFAULT_SCORE_WEIGHTS,
    EDIT_TYPES,
    SKILL_SECTION_NAMES,
    SEEDED_FAILURE_PATTERNS,
)


class TestSkillOptConfig:
    """Unit tests for SkillOptConfig dataclass."""

    def test_default_values(self):
        config = SkillOptConfig(skill_path="/tmp/test.py")
        assert config.epochs == 4
        assert config.minibatch_size == 8
        assert config.edit_budget == 4
        assert config.schedule == "cosine"
        assert config.epsilon == 0.01

    def test_skill_name_from_path(self):
        config = SkillOptConfig(skill_path="/path/to/codegen/datamodel.py")
        assert config.skill_name == "datamodel"

    def test_skill_name_explicit(self):
        config = SkillOptConfig(skill_path="/tmp/x.py", skill_name="custom")
        assert config.skill_name == "custom"

    def test_edit_budget_cosine_epoch0(self):
        config = SkillOptConfig(skill_path="/tmp/x.py", epochs=4, edit_budget=4)
        assert config.edit_budget_for_epoch(0) == 4

    def test_edit_budget_cosine_mid(self):
        config = SkillOptConfig(skill_path="/tmp/x.py", epochs=4, edit_budget=4)
        budget = config.edit_budget_for_epoch(2)
        assert 1 <= budget <= 3

    def test_edit_budget_cosine_last(self):
        config = SkillOptConfig(skill_path="/tmp/x.py", epochs=4, edit_budget=4)
        assert config.edit_budget_for_epoch(3) == 1

    def test_edit_budget_cosine_single_epoch(self):
        config = SkillOptConfig(skill_path="/tmp/x.py", epochs=1, edit_budget=4)
        assert config.edit_budget_for_epoch(0) >= 1

    def test_edit_budget_linear_decay(self):
        config = SkillOptConfig(
            skill_path="/tmp/x.py", epochs=4, edit_budget=4, schedule="linear"
        )
        b0 = config.edit_budget_for_epoch(0)
        b3 = config.edit_budget_for_epoch(3)
        assert b0 >= b3 >= 1

    def test_minimum_budget_is_one(self):
        config = SkillOptConfig(skill_path="/tmp/x.py", epochs=10, edit_budget=4)
        for epoch in range(10):
            assert config.edit_budget_for_epoch(epoch) >= 1


class TestScoreWeights:
    def test_weights_sum_to_one(self):
        total = sum(DEFAULT_SCORE_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_weights_all_positive(self):
        for dim, w in DEFAULT_SCORE_WEIGHTS.items():
            assert w > 0, f"{dim} weight should be positive"


class TestEditTypes:
    def test_valid_edit_types(self):
        assert "add" in EDIT_TYPES
        assert "delete" in EDIT_TYPES
        assert "replace" in EDIT_TYPES


class TestSkillSectionNames:
    def test_all_skills_have_names(self):
        assert "datamodel" in SKILL_SECTION_NAMES
        assert "api" in SKILL_SECTION_NAMES
        assert "frontend" in SKILL_SECTION_NAMES
        assert "project" in SKILL_SECTION_NAMES


class TestSeededFailurePatterns:
    def test_all_skills_seeded(self):
        for skill in ["datamodel", "api", "frontend", "project"]:
            assert skill in SEEDED_FAILURE_PATTERNS, f"Missing: {skill}"

    def test_datamodel_patterns_are_meaningful(self):
        patterns = SEEDED_FAILURE_PATTERNS["datamodel"]
        assert len(patterns) >= 3

    def test_api_patterns_mention_validation(self):
        patterns = SEEDED_FAILURE_PATTERNS["api"]
        has_validation = any(
            "response_model" in p.lower() or "Depends" in p for p in patterns
        )
        assert has_validation, "API patterns should mention response_model or Depends"

    def test_frontend_patterns_exist(self):
        patterns = SEEDED_FAILURE_PATTERNS["frontend"]
        assert len(patterns) >= 3
