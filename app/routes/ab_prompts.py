"""A/B Prompt Testing — API routes for prompt experimentation framework.

TASK-058 — A/B Prompt Testing.
- Create/manage prompt experiments with variants
- Deterministic variant assignment by user_id
- Log prompt executions and rate outputs
- Quality scoring via LLM-as-judge
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user, User
from ..models.ab_prompts import (
    PromptExperiment, PromptVariant,
    CreateExperimentRequest, AddVariantRequest, UpdateTrafficRequest,
    LogExecutionRequest, RateOutputRequest, QualityScoreRequest,
    AssignVariantResponse, ExperimentStatusResponse, QualityScoreResponse,
)
from ..services.ab_prompts import (
    assign_variant,
    log_execution,
    rate_output,
    score_quality,
    get_experiment_status,
    list_experiments,
    get_or_create_experiment,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ab-prompts", tags=["ab-prompts"])


# ── Experiment Management (auth) ───────────────────────

@router.get("/experiments")
async def api_list_experiments(
    user: User = Depends(get_current_user),
):
    """List all prompt experiments with basic stats."""
    return await list_experiments()


@router.post("/experiments")
async def api_create_experiment(
    req: CreateExperimentRequest,
    user: User = Depends(get_current_user),
):
    """Create a new prompt experiment with control variant."""
    exp = await get_or_create_experiment(req.name, req.control_prompt, req.description)
    return {
        "name": exp.name,
        "description": exp.description,
        "variants": [v.model_dump() for v in exp.variants],
    }


@router.get("/experiments/{name}", response_model=ExperimentStatusResponse)
async def api_experiment_status(
    name: str,
    user: User = Depends(get_current_user),
):
    """Get A/B test status for a specific prompt experiment."""
    status = await get_experiment_status(name)
    if not status:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    return ExperimentStatusResponse(**status)


@router.post("/experiments/{name}/variants")
async def api_add_variant(
    name: str,
    req: AddVariantRequest,
    user: User = Depends(get_current_user),
):
    """Add a new variant to an existing experiment."""
    exp = await get_or_create_experiment(name, "")
    if not exp:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    # Validate traffic distribution doesn't exceed 100%
    current_total = sum(v.traffic_pct for v in exp.variants)
    if current_total + req.traffic_pct > 100:
        raise HTTPException(
            status_code=400,
            detail=f"Total traffic would exceed 100% (current: {current_total}%)"
        )

    variant_key = f"v{len([v for v in exp.variants if not v.is_control]) + 1}"
    exp.variants.append(PromptVariant(
        key=variant_key,
        name=req.name,
        content=req.content,
        traffic_pct=req.traffic_pct,
    ))
    exp.updated_at = datetime.now(timezone.utc)
    await exp.save()

    return {"key": variant_key, "name": req.name, "traffic_pct": req.traffic_pct}


@router.put("/experiments/{name}/traffic")
async def api_update_traffic(
    name: str,
    req: UpdateTrafficRequest,
    user: User = Depends(get_current_user),
):
    """Update traffic allocation for a variant."""
    exp = await PromptExperiment.find_one(PromptExperiment.name == name)
    if not exp:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    for variant in exp.variants:
        if variant.key == req.variant_key:
            variant.traffic_pct = req.traffic_pct
            exp.updated_at = datetime.now(timezone.utc)
            await exp.save()
            return {"variant_key": req.variant_key, "traffic_pct": req.traffic_pct}

    raise HTTPException(status_code=404, detail=f"Variant '{req.variant_key}' not found")


@router.post("/experiments/{name}/toggle")
async def api_toggle_experiment(
    name: str,
    user: User = Depends(get_current_user),
):
    """Enable or disable a prompt experiment."""
    exp = await PromptExperiment.find_one(PromptExperiment.name == name)
    if not exp:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    exp.enabled = not exp.enabled
    exp.updated_at = datetime.now(timezone.utc)
    await exp.save()
    return {"name": exp.name, "enabled": exp.enabled}


# ── Runtime Endpoints (no auth, for prompt consumers) ──

@router.get("/assign/{prompt_name}/{user_id}", response_model=AssignVariantResponse)
async def api_assign_variant(
    prompt_name: str,
    user_id: str,
):
    """Assign a prompt variant deterministically by user_id hash.

    This is called at runtime before every LLM call.
    The caller passes the user_id and gets back which variant to use.
    """
    return await assign_variant(prompt_name, user_id)


@router.post("/log")
async def api_log_execution(req: LogExecutionRequest):
    """Log a prompt execution for later analysis.

    Called after every LLM call with the input, output, and timing.
    Returns a log_id for rating/scoring.
    """
    log_id = await log_execution(
        prompt_name=req.prompt_name,
        variant_key=req.variant_key,
        user_id=req.user_id,
        input_text=req.input_text,
        output_text=req.output_text,
        latency_ms=req.latency_ms,
        token_count=req.token_count,
        task_type=req.task_type,
    )
    if not log_id:
        raise HTTPException(status_code=404, detail=f"Experiment '{req.prompt_name}' not found")
    return {"log_id": log_id}


@router.post("/rate")
async def api_rate_output(req: RateOutputRequest):
    """Rate a prompt execution (thumbs up/down)."""
    ok = await rate_output(req.log_id, req.rating)
    if not ok:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return {"status": "ok"}


@router.post("/score", response_model=QualityScoreResponse)
async def api_score_quality(req: QualityScoreRequest):
    """Score a prompt execution using LLM-as-judge.

    Triggers an LLM call to evaluate the output quality against a rubric.
    Results are stored in the log entry for analysis.
    """
    score = await score_quality(req.log_id)
    if not score:
        raise HTTPException(status_code=404, detail="Log entry not found")
    return score
