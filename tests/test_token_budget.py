"""Tests for token_budget.py — TokenBudget and truncate_markdown."""

import pytest
from app.services.token_budget import (
    TokenBudget,
    estimate_tokens,
    truncate_markdown,
    section_reader,
    PRUNE_THRESHOLDS,
)


class TestTokenBudget:
    """TokenBudget dataclass tests."""

    def test_for_model_small(self):
        budget = TokenBudget.for_model("small")
        assert budget.max_tokens == 25000

    def test_for_model_medium(self):
        budget = TokenBudget.for_model("medium")
        assert budget.max_tokens == 200000

    def test_for_model_large(self):
        budget = TokenBudget.for_model("large")
        assert budget.max_tokens == 500000

    def test_for_model_xlarge(self):
        budget = TokenBudget.for_model("xlarge")
        assert budget.max_tokens == 1000000

    def test_unknown_model_defaults_to_large(self):
        budget = TokenBudget.for_model("gigantic")
        assert budget.max_tokens == 500000

    def test_pressure_at_half(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=500)
        budget._update_level()
        assert pytest.approx(budget.pressure, 0.01) == 0.5

    def test_pressure_triggers_level_1(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=350)
        budget._update_level()
        assert budget.level == 1

    def test_pressure_triggers_level_2(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=550)
        budget._update_level()
        assert budget.level == 2

    def test_pressure_triggers_level_3(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=750)
        budget._update_level()
        assert budget.level == 3

    def test_consume_tracks_usage(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=100)
        budget.consume(200)
        assert budget.used_tokens == 300

    def test_remaining(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=200)
        assert budget.remaining == 800

    def test_usable(self):
        budget = TokenBudget(max_tokens=1000, used_tokens=100, floor=200)
        assert budget.usable == 800

    def test_default_level_is_zero(self):
        budget = TokenBudget(max_tokens=1000)
        assert budget.level == 0


class TestEstimateTokens:
    def test_english_text(self):
        text = "The quick brown fox jumps over the lazy dog. " * 10
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert abs(tokens - len(text) / 4) < 20

    def test_code_heavy_text(self):
        code = "def foo(x: int) -> str:\n    return str(x)\n" * 20
        tokens = estimate_tokens(code)
        assert tokens > 0
        # Code-heavy: ~2 chars/token
        assert abs(tokens - len(code) / 2) < 30

    def test_empty_text(self):
        assert estimate_tokens("") == 0


class TestTruncateMarkdown:
    def test_fits_within_budget(self):
        md = "## Title\n\nShort content."
        content, offsets = truncate_markdown(md, max_tokens=500)
        assert md in content
        assert "Presupuesto" not in content  # Spanish hint not needed

    def test_truncates_long_section(self):
        md = "## Section\n\n" + ("long paragraph. " * 500) + "\n"
        content, offsets = truncate_markdown(md, max_tokens=200)
        assert "## Section" in content
        assert len(offsets) > 0 or "📌" in content  # Has offsets or truncation hint

    def test_keeps_section_headers(self):
        md = "## First\n\nfirst content.\n\n## Second\n\nsecond content.\n\n## Third\n\nthird content."
        content, offsets = truncate_markdown(md, max_tokens=100)
        assert "## First" in content

    def test_returns_empty_for_empty(self):
        content, offsets = truncate_markdown("", max_tokens=100)
        assert content == ""
        assert offsets == {}

    def test_code_blocks_preserved(self):
        md = "## Code\n\n```python\ndef foo():\n    return 42\n```\n\nSome text after."
        content, offsets = truncate_markdown(md, max_tokens=200)
        assert "## Code" in content


class TestSectionReader:
    def test_extract_existing_section(self):
        md = "## First\n\nalpha\n\n## Second\n\nbeta\n\n## Third\n\ngamma\n"
        result = section_reader(md, "Second")
        assert result is not None
        assert "beta" in result

    def test_missing_section(self):
        result = section_reader("## Only\n\ncontent\n", "MissingSection")
        assert result is None

    def test_empty_content(self):
        result = section_reader("", "Section")
        assert result is None
