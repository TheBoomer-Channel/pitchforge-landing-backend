"""SkillOpt Engine — self-improving codegen templates via forward/backward passes.

TASK-067 — Core engine that optimizes codegen skill templates through:
1. Forward pass: execute codegen on 40 training ideas, collect trajectories + scores
2. Backward pass (minibatch): LLM optimizer proposes bounded edits (ADD/DELETE/REPLACE)
3. Bounded text update: rank edits, clip to budget with cosine schedule
4. Validation gate: evaluate candidate skill on heldout set
5. Meta update: extract patterns across epochs

Based on arXiv:2605.23904v2 — SkillOpt: Self-Improving Code Generation Skills.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .skillopt_config import (
    EDIT_TYPES,
    SEEDED_FAILURE_PATTERNS,
    SKILL_SECTION_NAMES,
    DEFAULT_SCORE_WEIGHTS,
    SkillOptConfig,
)
from .skillopt_scorer import (
    CodegenTrajectory,
    compute_score,
)

logger = logging.getLogger(__name__)


# ── Data Classes ───────────────────────────────────────


@dataclass
class EditOperation:
    """A bounded edit proposed by the optimizer LLM."""

    op_type: str  # "add" | "delete" | "replace"
    target_section: str  # Section header where edit applies
    old_text: str = ""
    new_text: str = ""
    expected_utility: float = 0.5
    reasoning: str = ""

    def __post_init__(self):
        if self.op_type not in EDIT_TYPES:
            raise ValueError(f"Invalid op_type: {self.op_type}, must be one of {EDIT_TYPES}")

    def apply(self, skill_text: str) -> str:
        """Apply this edit to a skill template text."""
        if self.op_type == "add":
            return self._apply_add(skill_text)
        elif self.op_type == "delete":
            return self._apply_delete(skill_text)
        elif self.op_type == "replace":
            return self._apply_replace(skill_text)
        return skill_text

    def _apply_add(self, text: str) -> str:
        """Add new_text after the target_section header."""
        if not self.new_text:
            return text

        # Find the section header
        section_pattern = re.compile(
            rf"^(#+\s*{re.escape(self.target_section)}.*)$",
            re.MULTILINE,
        )
        match = section_pattern.search(text)
        if match:
            pos = match.end()
            # Insert after the section header + following blank line
            return text[:pos] + "\n" + self.new_text.strip() + "\n" + text[pos:]
        # Fallback: append to end
        return text + "\n\n" + self.new_text.strip() + "\n"

    def _apply_delete(self, text: str) -> str:
        """Delete old_text from the skill template."""
        if not self.old_text:
            return text
        return text.replace(self.old_text.strip(), "")

    def _apply_replace(self, text: str) -> str:
        """Replace old_text with new_text."""
        if not self.old_text:
            return text
        return text.replace(self.old_text.strip(), self.new_text.strip())

    def to_dict(self) -> dict:
        return {
            "op_type": self.op_type,
            "target_section": self.target_section,
            "old_text": self.old_text[:200],
            "new_text": self.new_text[:200],
            "expected_utility": self.expected_utility,
            "reasoning": self.reasoning,
        }


@dataclass
class OptimizationResult:
    """Tracks metrics across optimization epochs."""

    skill_name: str
    epochs: list[dict] = field(default_factory=list)
    initial_score: float = 0.0
    final_score: float = 0.0
    best_score: float = 0.0
    total_accepted_edits: int = 0
    total_rejected_edits: int = 0
    rejection_buffer: list[dict] = field(default_factory=list)
    meta_patterns: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    @property
    def improvement(self) -> float:
        return round(self.final_score - self.initial_score, 4)

    @property
    def duration_seconds(self) -> float:
        if not self.started_at or not self.finished_at:
            return 0.0
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.finished_at)
        return (end - start).total_seconds()

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "best_score": self.best_score,
            "improvement": self.improvement,
            "total_accepted_edits": self.total_accepted_edits,
            "total_rejected_edits": self.total_rejected_edits,
            "epochs_count": len(self.epochs),
            "rejection_buffer_size": len(self.rejection_buffer),
            "meta_patterns": self.meta_patterns,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ── Main Engine ────────────────────────────────────────


class SkillOpt:
    """Self-improving codegen template optimizer.

    Usage:
        config = SkillOptConfig(
            skill_path="codegen/datamodel.py",
            train_ideas=load_ideas("training/ideas.jsonl"),
            heldout_ideas=load_ideas("training/heldout_ideas.jsonl"),
        )
        engine = SkillOpt(config)
        result = await engine.optimize()
    """

    def __init__(self, config: SkillOptConfig):
        self.config = config
        self.original_skill_text = ""
        self.current_skill_text = ""
        self.rejection_buffer: list[tuple[EditOperation, float]] = []

    async def optimize(self) -> OptimizationResult:
        """Run the full SkillOpt pipeline: forward → backward → validate → repeat."""
        result = OptimizationResult(
            skill_name=self.config.skill_name,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # Load original skill text
        skill_path = Path(self.config.skill_path)
        if not skill_path.exists():
            logger.error(f"Skill file not found: {skill_path}")
            return result

        self.original_skill_text = skill_path.read_text()
        self.current_skill_text = self.original_skill_text

        # ── 0. Baseline score on heldout set ──
        logger.info(f"🏁 SkillOpt [{self.config.skill_name}] — computing baseline...")
        baseline_trajectories = await self._forward_pass(self.config.heldout_ideas)
        result.initial_score = self._mean_score(baseline_trajectories)
        result.best_score = result.initial_score
        self.config.initial_score = result.initial_score
        logger.info(
            f"   Baseline score: {result.initial_score:.4f} "
            f"({len(baseline_trajectories)} ideas)"
        )

        # ── Epoch loop ──
        for epoch in range(self.config.epochs):
            epoch_start = time.monotonic()
            budget = self.config.edit_budget_for_epoch(epoch)
            logger.info(f"\n📚 Epoch {epoch + 1}/{self.config.epochs} (budget={budget} edits)")

            # 1. Forward pass on training set
            trajectories = await self._forward_pass(self.config.train_ideas)
            mean_score = self._mean_score(trajectories)
            logger.info(f"   Forward pass: mean_score={mean_score:.4f}")

            # Separate good/bad trajectories
            good = [t for t in trajectories if t.total_score >= 0.7]
            bad = [t for t in trajectories if t.total_score < 0.7]
            logger.info(f"   Good: {len(good)} | Bad: {len(bad)}")

            # 2. Minibatch reflection: optimizer proposes edits
            edit_candidates = await self._reflect_minibatches(bad, good, epoch)

            # 3. Bounded text update: rank + clip
            accepted, rejected = self._rank_and_clip(edit_candidates, budget)

            # 4. Create candidate skill with accepted edits applied
            candidate_text = self.current_skill_text
            for edit in accepted:
                try:
                    candidate_text = edit.apply(candidate_text)
                except Exception as e:
                    logger.warning(f"   ⚠️ Edit apply failed: {e}")

            # 5. Validation gate: test candidate on heldout set
            holdout_trajectories = await self._evaluate_candidate(
                candidate_text, self.config.heldout_ideas
            )
            candidate_score = self._mean_score(holdout_trajectories)

            logger.info(
                f"   Validation: current={result.best_score:.4f} → "
                f"candidate={candidate_score:.4f}"
            )

            # 6. Accept/reject
            improved = candidate_score > result.best_score + self.config.epsilon
            if improved:
                self.current_skill_text = candidate_text
                result.best_score = candidate_score
                result.total_accepted_edits += len(accepted)
                self.config.accepted_edits += len(accepted)
                logger.info(f"   ✅ ACCEPTED — score improved to {candidate_score:.4f}")
            else:
                result.total_rejected_edits += len(accepted)
                self.config.rejected_edits += len(accepted)
                # Add to rejection buffer
                for edit in accepted:
                    self.rejection_buffer.append((edit, candidate_score - result.best_score))
                    if len(self.rejection_buffer) > self.config.rejection_buffer_size:
                        self.rejection_buffer.pop(0)
                logger.info(f"   ❌ REJECTED — score {candidate_score:.4f} ≤ {result.best_score:.4f}")

            # Track epoch metrics
            epoch_duration = int((time.monotonic() - epoch_start) * 1000)
            result.epochs.append({
                "epoch": epoch + 1,
                "train_mean_score": mean_score,
                "candidate_score": candidate_score,
                "best_score": result.best_score,
                "accepted_edits": len(accepted) if improved else 0,
                "rejected_edits": len(accepted) if not improved else 0,
                "budget": budget,
                "candidates_proposed": len(edit_candidates),
                "accepted": improved,
                "duration_ms": epoch_duration,
            })

        # ── 7. Save optimized skill ──
        result.final_score = result.best_score
        result.finished_at = datetime.now(timezone.utc).isoformat()
        self._save_optimized_skill(result)

        # ── 8. Meta pattern extraction ──
        result.meta_patterns = self._extract_meta_patterns(result)

        logger.info(
            f"\n🏁 SkillOpt complete: {result.initial_score:.4f} → "
            f"{result.final_score:.4f} "
            f"(Δ={result.improvement:+.4f}) in {self.config.epochs} epochs"
        )
        logger.info(
            f"   Accepted: {result.total_accepted_edits} | "
            f"Rejected: {result.total_rejected_edits}"
        )

        return result

    async def _forward_pass(
        self, ideas: list[dict], skill_text_override: Optional[str] = None
    ) -> list[CodegenTrajectory]:
        """Run codegen on all ideas and score the outputs.

        Uses the current skill text as the template. For each idea,
        generates code into a temp directory and scores the result.
        """
        trajectories = []
        skill_text = skill_text_override or self.current_skill_text

        for idea_dict in ideas:
            idea = idea_dict.get("idea", "")
            if not idea:
                continue

            traj = await self._generate_and_score(idea, idea_dict, skill_text)
            trajectories.append(traj)

            # Rate limit: small delay between ideas
            await asyncio.sleep(0.1)

        return trajectories

    async def _generate_and_score(
        self, idea: str, idea_dict: dict, skill_text: str
    ) -> CodegenTrajectory:
        """Execute codegen for one idea and score the output.

        This is where the actual codegen happens. In the MVI, we use
        a simulated approach that evaluates the skill text structure
        rather than running the full Docker-based codegen pipeline.
        """
        # For MVI: simulate codegen by checking skill text structure
        # In production, this would run the actual codegen pipeline
        # and parse the results.

        try:
            # ── Simulated codegen execution ──
            # Check if skill text contains key patterns
            expected_features = idea_dict.get("expected_features", [])
            expected_models = idea_dict.get("expected_models", [])
            expected_endpoints = idea_dict.get("expected_endpoints", [])

            # Create a "virtual" trajectory with simulated scores
            traj = CodegenTrajectory(
                idea=idea,
                output_dir=f"/tmp/skillopt/{self.config.skill_name}/{_slug(idea)}",
                generated_files=[],
                expected_features=expected_features,
                expected_models=expected_models,
                expected_endpoints=expected_endpoints,
            )

            # Score based on skill text quality heuristics
            scores = self._simulate_scores(skill_text, idea_dict)
            traj.scores = scores

            self.config.total_api_calls += 1

            return traj

        except Exception as e:
            logger.warning(f"   ⚠️ Failed to generate for '{idea[:40]}': {e}")
            # Return zero-score trajectory
            traj = CodegenTrajectory(
                idea=idea,
                output_dir=f"/tmp/skillopt/{self.config.skill_name}/error",
                generated_files=[],
            )
            traj.scores = {"total": 0.0}
            return traj

    def _simulate_scores(self, skill_text: str, idea_dict: dict) -> dict[str, float]:
        """Simulate codegen scores based on skill text quality heuristics.

        This is the MVI fallback. In production, scores come from actual
        codegen execution (Docker build, pytest run, etc.).
        """

        # Check for common failure patterns
        has_imports = "import" in skill_text
        has_optional = "Optional[" in skill_text
        has_field = "Field(" in skill_text
        has_response_model = "response_model" in skill_text
        has_depends = "Depends" in skill_text
        has_error_handling = "HTTPException" in skill_text or "404" in skill_text
        has_pagination = "skip" in skill_text.lower() or "limit" in skill_text.lower()
        has_healthcheck = "healthcheck" in skill_text.lower() or "health" in skill_text
        has_cors = "CORSMiddleware" in skill_text
        has_tests = "test_" in skill_text
        has_docker = "docker" in skill_text.lower()
        has_type_hints = "->" in skill_text
        has_async = "async def" in skill_text

        # Score each dimension heuristically
        scores = {}

        # compiles: basic structure indicators
        scores["compiles"] = (
            0.7
            + 0.1 * has_imports
            + 0.1 * has_type_hints
            + 0.1 * has_async
        )

        # imports_valid: standard library patterns
        scores["imports_valid"] = 0.8 + 0.1 * has_imports + 0.1 * has_optional

        # tests_pass: test indicators
        scores["tests_pass"] = 0.5 + 0.3 * has_tests + 0.2 * has_field

        # endpoints_match: route pattern indicators
        endpoints_ok = has_response_model and has_depends and has_error_handling
        scores["endpoints_match"] = (
            0.3
            + 0.25 * has_response_model
            + 0.25 * has_depends
            + 0.1 * has_pagination
            + 0.1 * has_error_handling
        )

        # models_match: model/schema indicators
        scores["models_match"] = 0.6 + 0.2 * has_field + 0.2 * has_optional

        # no_orphan_code: completeness indicators
        scores["no_orphan_code"] = (
            0.6
            + 0.1 * has_imports
            + 0.1 * has_error_handling
            + 0.1 * has_tests
            + 0.1 * has_docker
        )

        # lint_clean: code quality indicators
        scores["lint_clean"] = (
            0.7
            + 0.1 * has_type_hints
            + 0.1 * has_async
            + 0.05 * has_cors
            + 0.05 * has_healthcheck
        )

        # Compute total
        weights = DEFAULT_SCORE_WEIGHTS
        total = sum(weights.get(k, 0.0) * min(v, 1.0) for k, v in scores.items())
        scores["total"] = round(total, 4)

        return scores

    async def _reflect_minibatches(
        self,
        bad_trajectories: list[CodegenTrajectory],
        good_trajectories: list[CodegenTrajectory],
        epoch: int,
    ) -> list[EditOperation]:
        """LLM optimizer reflects on minibatches and proposes bounded edits.

        Splits bad trajectories into minibatches, sends each to the LLM
        with the current skill text, and collects edit proposals.
        """
        if not bad_trajectories:
            logger.info("   No failed trajectories — skipping reflection")
            return []

        batch_size = self.config.minibatch_size
        all_candidates: list[EditOperation] = []

        # Process minibatches
        for i in range(0, len(bad_trajectories), batch_size):
            batch = bad_trajectories[i : i + batch_size]

            try:
                edits = await self._llm_reflect_minibatch(batch, good_trajectories[:3], epoch)
                all_candidates.extend(edits)
            except Exception as e:
                logger.warning(f"   ⚠️ Reflection failed for batch {i}: {e}")

        # Also check rejection buffer for patterns
        if self.rejection_buffer:
            buffer_edits = self._mine_rejection_buffer()
            all_candidates.extend(buffer_edits)

        return all_candidates

    async def _llm_reflect_minibatch(
        self,
        bad_trajectories: list[CodegenTrajectory],
        good_examples: list[CodegenTrajectory],
        epoch: int,
    ) -> list[EditOperation]:
        """Send a minibatch to the LLM optimizer for reflection.

        The LLM receives the current skill text and failed trajectories,
        and proposes bounded edits to fix the issues.
        """
        # Build the reflection prompt
        bad_summaries = "\n".join(
            f"- {t.idea[:80]}: score={t.total_score:.3f} "
            + ", ".join(f"{k}={v:.2f}" for k, v in t.scores.items() if k != "total")
            for t in bad_trajectories
        )

        good_summaries = "\n".join(
            f"- {t.idea[:80]}: score={t.total_score:.3f}"
            for t in good_examples
        )

        # Get seeded failure patterns for this skill
        skill_name = self.config.skill_name
        known_patterns = SEEDED_FAILURE_PATTERNS.get(skill_name, [])

        prompt = f"""You are an optimizer for codegen skill templates. Given the current skill text and the scores of generated code, propose up to {self.config.edit_budget_for_epoch(epoch)} bounded edits to improve the skill.

## Current Skill Text
```python
{self.current_skill_text[:3000]}
```

## Failed Generations (score < 0.70)
{bad_summaries if bad_summaries else "None"}

## Good Generations (score >= 0.70)
{good_summaries if good_summaries else "None"}

## Known Failure Patterns for {skill_name}
{chr(10).join(f'- {p}' for p in known_patterns) if known_patterns else "None pre-seeded"}

## Instructions
Analyze WHY the failed generations scored low and propose bounded edits:
- ADD: new guidance/rules to prevent failures
- DELETE: harmful patterns that cause failures
- REPLACE: improve existing patterns

Return JSON array of edits:
[{{"op_type": "add"|"delete"|"replace", "target_section": "section name", "old_text": "...", "new_text": "...", "reasoning": "why this helps"}}]

Rules:
- Each edit must be bounded (small, focused changes)
- target in specific sections of the template
- Focus on the LOWEST scoring dimensions
- Do NOT change the overall structure drastically"""

        try:
            import httpx

            # Use DeepSeek API for optimization
            api_key = _get_api_key()

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are an expert code generation optimizer. Output valid JSON only.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1500,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    edits = self._parse_edit_response(content)
                    self.config.total_api_calls += 1
                    return edits
                else:
                    logger.warning(f"   LLM API error: {response.status_code}")
                    return []

        except Exception as e:
            logger.warning(f"   LLM reflection failed: {e}")
            return []

    def _parse_edit_response(self, content: str) -> list[EditOperation]:
        """Parse JSON edit proposals from LLM response."""
        try:
            # Extract JSON array from response (handle markdown code blocks)
            json_match = re.search(r"\[[\s\S]*\]", content)
            if not json_match:
                return []

            proposals = json.loads(json_match.group())

            edits = []
            for p in proposals:
                if not isinstance(p, dict):
                    continue
                op_type = p.get("op_type", "")
                if op_type not in EDIT_TYPES:
                    continue
                edits.append(
                    EditOperation(
                        op_type=op_type,
                        target_section=p.get("target_section", ""),
                        old_text=p.get("old_text", ""),
                        new_text=p.get("new_text", ""),
                        reasoning=p.get("reasoning", ""),
                        expected_utility=p.get("expected_utility", 0.5),
                    )
                )
            return edits
        except json.JSONDecodeError as e:
            logger.warning(f"   Failed to parse edit response: {e}")
            return []

    def _mine_rejection_buffer(self) -> list[EditOperation]:
        """Extract potential edits from rejection buffer patterns."""
        if not self.rejection_buffer:
            return []

        # Look for edits that were rejected multiple times
        # If same target_section appears 3+ times, revive with lower utility
        from collections import Counter

        section_counts = Counter(
            edit.target_section for edit, _ in self.rejection_buffer
        )

        candidates = []
        for edit, delta in self.rejection_buffer[-10:]:
            if section_counts[edit.target_section] >= 3:
                # Revive with adjusted utility
                revived = EditOperation(
                    op_type=edit.op_type,
                    target_section=edit.target_section,
                    old_text=edit.old_text,
                    new_text=edit.new_text,
                    reasoning=f"[REVIVED] {edit.reasoning} (seen {section_counts[edit.target_section]}x)",
                    expected_utility=edit.expected_utility * 0.5,
                )
                candidates.append(revived)

        return candidates[:2]  # Max 2 revived edits

    def _rank_and_clip(
        self, edits: list[EditOperation], budget: int
    ) -> tuple[list[EditOperation], list[EditOperation]]:
        """Rank edits by expected_utility, clip to budget."""
        # Deduplicate by target_section + op_type combination
        seen = set()
        unique = []
        for edit in sorted(edits, key=lambda e: e.expected_utility, reverse=True):
            key = (edit.op_type, edit.target_section, edit.old_text[:50])
            if key not in seen:
                seen.add(key)
                unique.append(edit)

        accepted = unique[:budget]
        rejected = unique[budget:]
        return accepted, rejected

    async def _evaluate_candidate(
        self, candidate_text: str, ideas: list[dict]
    ) -> list[CodegenTrajectory]:
        """Evaluate a candidate skill on heldout ideas."""
        return await self._forward_pass(ideas, skill_text_override=candidate_text)

    def _extract_meta_patterns(self, result: OptimizationResult) -> list[str]:
        """Extract meta-patterns from across-epoch optimization data."""
        patterns = []

        # Pattern 1: Score trajectory
        if len(result.epochs) >= 2:
            first = result.epochs[0]["best_score"]
            last = result.epochs[-1]["best_score"]
            if last > first + 0.05:
                patterns.append(f"Steady improvement: {first:.3f} → {last:.3f}")
            elif last <= first:
                patterns.append("Stagnation: no improvement across epochs")

        # Pattern 2: Acceptance rate
        if result.epochs:
            accept_rates = [
                e["accepted"] for e in result.epochs
            ]
            early_rate = sum(accept_rates[: len(accept_rates) // 2]) / max(len(accept_rates) // 2, 1)
            late_rate = sum(accept_rates[len(accept_rates) // 2 :]) / max(len(accept_rates) - len(accept_rates) // 2, 1)
            if late_rate > early_rate:
                patterns.append(f"Improving acceptance: {early_rate:.0%} → {late_rate:.0%}")
            elif late_rate < early_rate:
                patterns.append(f"Declining acceptance: {early_rate:.0%} → {late_rate:.0%}")

        # Pattern 3: Edit efficiency
        if result.total_accepted_edits > 0:
            improvement_per_edit = result.improvement / result.total_accepted_edits
            patterns.append(f"Δ/Edit: {improvement_per_edit:.4f}")

        # Pattern 4: Budget utilization
        if result.epochs:
            avg_used = sum(e.get("accepted_edits", 0) + e.get("rejected_edits", 0) for e in result.epochs) / len(result.epochs)
            avg_budget = sum(e.get("budget", self.config.edit_budget) for e in result.epochs) / len(result.epochs)
            patterns.append(f"Budget utilization: {avg_used:.1f}/{avg_budget:.1f} avg")

        return patterns

    @staticmethod
    def _mean_score(trajectories: list[CodegenTrajectory]) -> float:
        """Compute mean score across trajectories."""
        if not trajectories:
            return 0.0
        return round(
            sum(t.total_score for t in trajectories) / len(trajectories), 4
        )

    def _save_optimized_skill(self, result: OptimizationResult) -> str:
        """Save the optimized skill text and result metadata."""
        out = Path(self.config.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        # Save optimized skill
        skill_out = out / f"{self.config.skill_name}_optimized.py"
        skill_out.write_text(self.current_skill_text)

        # Save result metadata
        result_out = out / "optimization_result.json"
        result_out.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
        )

        # Save rejection buffer for future runs
        buffer_out = out / "rejection_buffer.jsonl"
        with open(buffer_out, "w") as f:
            for edit, delta in self.rejection_buffer:
                f.write(
                    json.dumps(
                        {"edit": edit.to_dict(), "score_delta": delta}
                    )
                    + "\n"
                )

        logger.info(f"   💾 Saved to {out}")
        return str(out)


# ── Helpers ────────────────────────────────────────────


def _slug(text: str) -> str:
    """Convert text to a safe directory name."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:50]


def _get_api_key() -> str:
    """Get DeepSeek API key from project settings."""
    try:
        from app.config import settings
        key = settings.DEEPSEEK_API_KEY
        if key:
            return key
    except (ImportError, AttributeError):
        pass
    import os
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY not set in environment or config")
    return key
