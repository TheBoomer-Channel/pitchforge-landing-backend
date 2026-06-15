"""AB Prompt Testing Service — variant assignment, logging, quality scoring.

TASK-058 — A/B Prompt Testing Framework.
- Deterministic variant assignment by user_id hash
- Prompt execution logging with input/output
- Quality scoring via LLM-as-judge with rubric
- Statistical winner selection
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..models.ab_prompts import (
    PromptExperiment, PromptVariant, PromptLogEntry, QualityScore,
    AssignVariantResponse, VariantStats, QualityScoreResponse,
)
from ..services.llm import llm

logger = logging.getLogger(__name__)


# ── Variant Assignment (deterministic by user_id) ──────

def _hash_user(user_id: str, prompt_name: str) -> int:
    """Deterministic hash for consistent variant assignment."""
    raw = f"{user_id}:{prompt_name}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16) % 100


def select_variant(experiment: PromptExperiment, user_id: str) -> Optional[PromptVariant]:
    """Select a variant deterministically based on user_id hash.

    Uses cumulative traffic percentage:
    - control: 0-49 (50%)
    - v1: 50-69 (20%)
    - v2: 70-84 (15%)
    - v3: 85-94 (10%)
    - v4: 95-99 (5%)
    """
    if not experiment.variants:
        return None

    hash_val = _hash_user(user_id, experiment.name)
    cumulative = 0

    for variant in experiment.variants:
        cumulative += variant.traffic_pct
        if hash_val < cumulative:
            return variant

    # Fallback to control
    return experiment.variants[0]


async def get_or_create_experiment(name: str, control_prompt: str, description: str = "") -> PromptExperiment:
    """Get existing experiment or create one with a single control variant."""
    exp = await PromptExperiment.find_one(PromptExperiment.name == name)
    if not exp:
        exp = PromptExperiment(
            name=name,
            description=description,
            variants=[
                PromptVariant(
                    key="control",
                    name="Control (original)",
                    content=control_prompt,
                    traffic_pct=100,
                    is_control=True,
                )
            ],
        )
        await exp.insert()
    return exp


async def assign_variant(prompt_name: str, user_id: str) -> AssignVariantResponse:
    """Assign a prompt variant to a user deterministically.

    Returns the variant content and metadata.
    If no experiment exists, returns a default response.
    """
    exp = await PromptExperiment.find_one(PromptExperiment.name == prompt_name)
    if not exp or not exp.enabled:
        return AssignVariantResponse(
            prompt_name=prompt_name,
            variant_key="control",
            variant_content="",
            is_control=True,
            traffic_pct=100,
        )

    variant = select_variant(exp, user_id)
    if not variant:
        return AssignVariantResponse(
            prompt_name=prompt_name,
            variant_key="control",
            variant_content="",
            is_control=True,
            traffic_pct=100,
        )

    return AssignVariantResponse(
        prompt_name=prompt_name,
        variant_key=variant.key,
        variant_content=variant.content,
        is_control=variant.is_control,
        traffic_pct=variant.traffic_pct,
    )


# ── Logging ────────────────────────────────────────────

async def log_execution(
    prompt_name: str,
    variant_key: str,
    user_id: str,
    input_text: str,
    output_text: str,
    latency_ms: float,
    token_count: int,
    task_type: str = "chat",
) -> Optional[str]:
    """Log a prompt execution to the experiment's log.

    Returns the log_id for later rating/scoring.
    """
    exp = await PromptExperiment.find_one(PromptExperiment.name == prompt_name)
    if not exp:
        return None

    log_id = f"{prompt_name}_{int(time.time())}_{hash(user_id) % 10000:04d}"

    entry = PromptLogEntry(
        log_id=log_id,
        user_id=user_id,
        prompt_name=prompt_name,
        variant_key=variant_key,
        input_snippet=input_text[:200],
        output_snippet=output_text[:500],
        latency_ms=latency_ms,
        token_count=token_count,
        task_type=task_type,
    )

    # Keep last 1000 logs; append and cap
    exp.logs.append(entry)
    if len(exp.logs) > 1000:
        exp.logs = exp.logs[-1000:]

    exp.total_calls += 1
    exp.updated_at = datetime.now(timezone.utc)
    await exp.save()

    return log_id


async def rate_output(log_id: str, rating: int) -> bool:
    """Record a user rating (thumbs up/down) for a prompt execution."""
    exp = await PromptExperiment.find(
        PromptExperiment.logs.log_id == log_id
    ).first_or_none()

    if not exp:
        return False

    for entry in exp.logs:
        if entry.log_id == log_id:
            entry.user_rating = rating
            exp.total_user_ratings += 1
            exp.updated_at = datetime.now(timezone.utc)
            await exp.save()
            return True

    return False


# ── Quality Scoring (LLM-as-Judge) ────────────────────

RUBRIC = """
## Quality Scoring Rubric (0-10)

Rate the AI output on these 5 dimensions:

1. **Relevance** (0-10): Does the output directly address the user's request?
2. **Accuracy** (0-10): Is the information factually correct and well-reasoned?
3. **Clarity** (0-10): Is the output clear, well-structured, and easy to understand?
4. **Completeness** (0-10): Does it cover all aspects of the request?
5. **Overall** (0-10): Combined assessment considering task difficulty.

Output ONLY valid JSON:
{"relevance": 8, "accuracy": 7, "clarity": 9, "completeness": 8, "overall": 8, "reasoning": "The response addresses the core question but misses some edge cases."}
"""


async def score_quality(log_id: str) -> Optional[QualityScoreResponse]:
    """Score a prompt execution using LLM-as-judge.

    Uses the LLM to evaluate the output against a rubric.
    Returns quality scores for 5 dimensions.
    """
    exp = await PromptExperiment.find(
        PromptExperiment.logs.log_id == log_id
    ).first_or_none()

    if not exp:
        return None

    entry = None
    for e in exp.logs:
        if e.log_id == log_id:
            entry = e
            break

    if not entry:
        return None

    # Build judge prompt
    judge_prompt = f"""You are an expert AI output quality judge. Evaluate the following AI response.

## User Input
{entry.input_snippet}

## AI Output
{entry.output_snippet}

{RUBRIC}"""

    try:
        result = await llm.json(judge_prompt, temperature=0.1, max_tokens=500)

        if not result:
            return QualityScoreResponse(
                score=0, relevance=0, accuracy=0, clarity=0,
                completeness=0, reasoning="LLM judge failed to return valid JSON"
            )

        qs = QualityScore(
            overall=result.get("overall", 0),
            relevance=result.get("relevance", 0),
            accuracy=result.get("accuracy", 0),
            clarity=result.get("clarity", 0),
            completeness=result.get("completeness", 0),
            reasoning=result.get("reasoning", ""),
        )

        # Store back to the log entry
        entry.quality_score = qs
        exp.total_quality_scores += 1
        exp.updated_at = datetime.now(timezone.utc)
        await exp.save()

        return QualityScoreResponse(
            score=qs.overall,
            relevance=qs.relevance,
            accuracy=qs.accuracy,
            clarity=qs.clarity,
            completeness=qs.completeness,
            reasoning=qs.reasoning or "",
        )

    except Exception as e:
        logger.warning(f"Quality scoring failed for {log_id}: {e}")
        return QualityScoreResponse(
            score=0, relevance=0, accuracy=0, clarity=0,
            completeness=0, reasoning=f"Error: {e}"
        )


# ── Statistics ─────────────────────────────────────────

async def get_experiment_status(name: str) -> Optional[dict]:
    """Get A/B test status with per-variant stats."""
    exp = await PromptExperiment.find_one(PromptExperiment.name == name)
    if not exp:
        return None

    variant_stats = {}
    for variant in exp.variants:
        variant_stats[variant.key] = {
            "total_calls": 0,
            "total_ratings": 0,
            "positive_ratings": 0,
            "quality_scores": [],
            "total_latency": 0.0,
        }

    for entry in exp.logs:
        vk = entry.variant_key
        if vk not in variant_stats:
            continue
        variant_stats[vk]["total_calls"] += 1
        variant_stats[vk]["total_latency"] += entry.latency_ms
        if entry.user_rating is not None:
            variant_stats[vk]["total_ratings"] += 1
            if entry.user_rating == 1:
                variant_stats[vk]["positive_ratings"] += 1
        if entry.quality_score:
            variant_stats[vk]["quality_scores"].append(entry.quality_score.overall)

    variants = []
    for variant in exp.variants:
        stats = variant_stats.get(variant.key, {})
        qs = stats.get("quality_scores", [])
        avg_qs = sum(qs) / len(qs) if qs else 0.0
        tc = stats.get("total_calls", 0)

        variants.append(VariantStats(
            variant_key=variant.key,
            name=variant.name,
            traffic_pct=variant.traffic_pct,
            total_calls=tc,
            total_ratings=stats.get("total_ratings", 0),
            positive_ratings=stats.get("positive_ratings", 0),
            avg_quality_score=round(avg_qs, 2),
            avg_latency_ms=round(stats.get("total_latency", 0) / max(tc, 1), 1),
            is_control=variant.is_control,
        ))

    # Determine winner (highest avg quality score with at least 10 evaluations)
    scored_variants = [v for v in variants if v.total_calls >= 10 and v.avg_quality_score > 0]
    winner = None
    confidence = None
    if scored_variants:
        best = max(scored_variants, key=lambda v: v.avg_quality_score)
        if not best.is_control:
            control = next((v for v in scored_variants if v.is_control), None)
            if control and control.avg_quality_score > 0:
                improvement = ((best.avg_quality_score - control.avg_quality_score) / control.avg_quality_score) * 100
                if improvement > 5:  # At least 5% improvement
                    winner = best.variant_key
                    confidence = round(improvement, 1)

    return {
        "name": exp.name,
        "enabled": exp.enabled,
        "description": exp.description,
        "variants": [v.model_dump() for v in variants],
        "total_calls": exp.total_calls,
        "total_ratings": exp.total_user_ratings,
        "winner": winner,
        "confidence": confidence,
    }


async def list_experiments() -> list[dict]:
    """List all prompt experiments with basic stats."""
    experiments = await PromptExperiment.find_all().to_list()
    result = []
    for exp in experiments:
        result.append({
            "name": exp.name,
            "description": exp.description,
            "enabled": exp.enabled,
            "variant_count": len(exp.variants),
            "total_calls": exp.total_calls,
            "total_ratings": exp.total_user_ratings,
            "total_quality_scores": exp.total_quality_scores,
            "created_at": exp.created_at.isoformat(),
        })
    return result
