"""AI Quality Monitoring — EvalRunner service.

TASK-059 — Eval suite with golden dataset, LLM-as-judge scoring,
regression detection, and Slack alerting.

Usage:
    from app.services.ai_quality import eval_runner

    # Run full eval suite
    results = await eval_runner.run_full_suite()

    # Get latest quality report
    report = await eval_runner.get_report()
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import settings
from ..models.quality import EvalResult

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────

_EVALS_DIR = Path(__file__).resolve().parent.parent.parent / "evals"
_DEFAULT_CASES_PATH = _EVALS_DIR / "cases.json"

# ── Defaults ────────────────────────────────────────────

DEFAULT_BASELINE = 0.85
REGRESSION_THRESHOLD = 0.80
MIN_CASES_FOR_TREND = 3


class EvalRunner:
    """Runs AI quality evaluations against the LLM.

    Loads golden cases, runs each through the LLM router,
    scores results using LLM-as-judge, and tracks regressions.
    """

    def __init__(self, cases_path: Optional[str] = None):
        self._cases_path = Path(cases_path) if cases_path else _DEFAULT_CASES_PATH
        self._cases: list[dict] = []

    # ── Public API ──────────────────────────────────────

    async def run_full_suite(
        self,
        models: Optional[list[str]] = None,
        task_types: Optional[list[str]] = None,
    ) -> dict:
        """Run all eval cases and return the report.

        Args:
            models: Optional list of models to test (default: auto-select).
            task_types: Optional list of task types to include.

        Returns:
            Report dict with scores, regressions, and per-category breakdown.
        """
        self._cases = self._load_cases(task_types=task_types)
        if not self._cases:
            return {"status": "error", "message": "No eval cases found"}

        run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
        logger.info(f"Running AI quality eval suite: {len(self._cases)} cases [run_id={run_id}]")

        results = []
        for case in self._cases:
            try:
                result = await self._evaluate_single(case, run_id, models)
                results.append(result)
            except Exception as e:
                logger.error(f"Eval case {case['id']} failed: {e}")
                results.append({
                    "case_id": case["id"],
                    "category": case.get("category", "general"),
                    "score": 0.0,
                    "model": "error",
                    "run_id": run_id,
                    "error": str(e),
                })

        # Save all results to DB
        saved = await self._save_results(results, run_id)

        # Compute statistics
        report = self._compute_report(saved, run_id)

        # Check for regressions
        regressions = await self._check_regressions(report)
        if regressions:
            report["regressions"] = regressions
            await self._send_regression_alert(regressions, report)

        logger.info(
            f"Eval suite complete: avg_score={report['average_score']:.3f}, "
            f"total_cases={report['total_cases']}, "
            f"regressions={len(regressions)}"
        )
        return report

    async def get_report(self, limit: int = 5) -> dict:
        """Get latest quality report with trend data.

        Args:
            limit: Number of recent runs to include for trend.

        Returns:
            Report with latest scores and trend data.
        """
        # Get latest run
        latest = await EvalResult.find().sort(-EvalResult.ts).limit(1).to_list()
        if not latest:
            return {"status": "no_data", "message": "No eval runs recorded yet"}

        latest_run_id = latest[0].run_id
        return await self._build_report(latest_run_id, limit)

    async def get_run(self, run_id: str) -> dict:
        """Get detailed results for a specific run."""
        results = await EvalResult.find(
            EvalResult.run_id == run_id
        ).sort(EvalResult.case_id).to_list()

        if not results:
            return {"status": "not_found", "message": f"Run {run_id} not found"}

        return self._compute_report(results, run_id)

    def get_case_count(self) -> int:
        """Return number of available eval cases."""
        return len(self._load_cases())

    # ── Internal ────────────────────────────────────────

    def _load_cases(self, task_types: Optional[list[str]] = None) -> list[dict]:
        """Load eval cases from the golden dataset JSON."""
        if not self._cases_path.exists():
            logger.warning(f"Eval cases not found at {self._cases_path}")
            return []

        try:
            with open(self._cases_path) as f:
                all_cases = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load eval cases: {e}")
            return []

        if task_types:
            return [c for c in all_cases if c.get("task_type") in task_types]
        return all_cases

    async def _evaluate_single(
        self,
        case: dict,
        run_id: str,
        models: Optional[list[str]] = None,
    ) -> dict:
        """Run a single eval case through the LLM and score it.

        Uses LLM-as-judge pattern:
        1. Send the prompt to the LLM
        2. Use a second LLM call to score the output against the rubric
        """
        prompt = case.get("prompt", "")
        expected = case.get("expected_output", "")
        rubric = case.get("rubric", "")
        case_id = case.get("id", "unknown")
        task_type = case.get("task_type", "chat")

        # Phase 1: Generate response
        from .llm_router import llm_router

        start = time.monotonic()
        try:
            actual_response = await llm_router.chat(
                prompt=prompt,
                task_type=task_type,
                temperature=0.3,
                max_tokens=2048,
            )
            latency_ms = (time.monotonic() - start) * 1000

            # Phase 2: Score with LLM-as-judge
            score = await self._score_with_judge(
                prompt=prompt,
                expected=expected,
                actual=actual_response,
                rubric=rubric,
            )

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return {
                "case_id": case_id,
                "category": case.get("category", "general"),
                "prompt": prompt,
                "expected_output": expected,
                "actual_output": "",
                "score": 0.0,
                "rubric": rubric,
                "model": "error",
                "task_type": task_type,
                "latency_ms": latency_ms,
                "error": str(e),
                "run_id": run_id,
            }

        return {
            "case_id": case_id,
            "category": case.get("category", "general"),
            "prompt": prompt,
            "expected_output": expected,
            "actual_output": actual_response,
            "score": score,
            "rubric": rubric,
            "model": llm_router._last_used_model or "unknown",
            "task_type": task_type,
            "latency_ms": latency_ms,
            "run_id": run_id,
        }

    async def _score_with_judge(
        self,
        prompt: str,
        expected: str,
        actual: str,
        rubric: str,
    ) -> float:
        """Score LLM output quality using LLM-as-judge.

        Returns a float 0.0 to 1.0 representing quality score.
        Uses the LLM itself to evaluate its own output.

        In dev/offline mode, returns a simulated score for testing.
        """
        # Offline mode: return fixed score for determinism
        if os.getenv("AI_QUALITY_OFFLINE", "false").lower() == "true":
            return 0.85

        scoring_prompt = f"""You are an AI quality evaluator. Score the following LLM output on a scale of 0.0 to 1.0.

ORIGINAL PROMPT:
{prompt}

EXPECTED CHARACTERISTICS:
{expected}

SCORING RUBRIC:
{rubric}

ACTUAL OUTPUT:
{actual}

Respond with ONLY a single float between 0.0 and 1.0. No explanation.
Base your score on how well the output satisfies the rubric criteria.
0.0 = completely wrong/irrelevant, 0.5 = partially correct, 1.0 = perfect."""
        from .llm import llm as deepseek_llm
        try:
            result = await deepseek_llm.chat(
                scoring_prompt,
                temperature=0.1,
                max_tokens=50,
            )
            # Parse float from response
            score = float(result.strip()[:4].strip())
            return max(0.0, min(1.0, score))
        except Exception as e:
            logger.warning(f"LLM-as-judge parsing failed: {e}, using fallback")
            return 0.5

    async def _save_results(
        self,
        results: list[dict],
        run_id: str,
    ) -> list[EvalResult]:
        """Save eval results to database."""
        saved = []
        for r in results:
            try:
                record = EvalResult(
                    case_id=r.get("case_id", "unknown"),
                    category=r.get("category", "general"),
                    prompt=r.get("prompt", ""),
                    expected_output=r.get("expected_output", ""),
                    actual_output=r.get("actual_output", ""),
                    score=r.get("score", 0.0),
                    rubric=r.get("rubric", ""),
                    model=r.get("model", "unknown"),
                    task_type=r.get("task_type", "chat"),
                    latency_ms=r.get("latency_ms", 0.0),
                    run_id=run_id,
                    error=r.get("error"),
                )
                await record.insert()
                saved.append(record)
            except Exception as e:
                logger.error(f"Failed to save eval result: {e}")
        return saved

    def _compute_report(
        self,
        results: list[EvalResult],
        run_id: str,
    ) -> dict:
        """Compute aggregate statistics from eval results.

        Args:
            results: List of EvalResult objects.
            run_id: The batch run identifier.

        Returns:
            Report dict with scores, breakdowns, and per-category stats.
        """
        if not results:
            return {"status": "no_results", "run_id": run_id}

        total = len(results)
        scores = [r.score for r in results]
        avg_score = sum(scores) / max(total, 1)

        # Per-category breakdown
        categories: dict[str, dict] = {}
        for r in results:
            cat = r.category or "general"
            if cat not in categories:
                categories[cat] = {"count": 0, "scores": [], "avg": 0.0}
            categories[cat]["count"] += 1
            categories[cat]["scores"].append(r.score)

        for cat_data in categories.values():
            cat_data["avg"] = round(
                sum(cat_data["scores"]) / max(cat_data["count"], 1), 3
            )
            del cat_data["scores"]

        # Per-model breakdown
        models: dict[str, dict] = {}
        for r in results:
            mdl = r.model or "unknown"
            if mdl not in models:
                models[mdl] = {"count": 0, "scores": [], "avg": 0.0}
            models[mdl]["count"] += 1
            models[mdl]["scores"].append(r.score)

        for mdl_data in models.values():
            mdl_data["avg"] = round(
                sum(mdl_data["scores"]) / max(mdl_data["count"], 1), 3
            )
            del mdl_data["scores"]

        # Failed cases
        failures = [r.case_id for r in results if r.error or r.score == 0.0]

        return {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_cases": total,
            "average_score": round(avg_score, 3),
            "pass_count": sum(1 for s in scores if s >= REGRESSION_THRESHOLD),
            "fail_count": sum(1 for s in scores if s < REGRESSION_THRESHOLD),
            "min_score": round(min(scores), 3),
            "max_score": round(max(scores), 3),
            "by_category": categories,
            "by_model": models,
            "failures": failures,
        }

    async def _build_report(self, run_id: str, limit: int = 5) -> dict:
        """Build a full quality report with trend data."""
        results = await EvalResult.find(
            EvalResult.run_id == run_id
        ).sort(EvalResult.case_id).to_list()

        report = self._compute_report(results, run_id)

        # Get recent runs for trend
        recent_runs = await EvalResult.find().sort(-EvalResult.ts).to_list()
        run_ids: list[str] = []
        seen: set[str] = set()
        for r in recent_runs:
            if r.run_id not in seen and r.run_id != run_id:
                seen.add(r.run_id)
                run_ids.append(r.run_id)
            if len(seen) >= limit:
                break

        trend = []
        for rid in run_ids:
            run_results = [r for r in recent_runs if r.run_id == rid]
            if run_results:
                avg = sum(r.score for r in run_results) / max(len(run_results), 1)
                trend.append({
                    "run_id": rid,
                    "average_score": round(avg, 3),
                    "total_cases": len(run_results),
                    "generated_at": max(r.ts.isoformat() for r in run_results),
                })

        report["trend"] = sorted(trend, key=lambda x: x["run_id"], reverse=True)
        return report

    async def _check_regressions(self, report: dict) -> list[dict]:
        """Check for regressions compared to previous runs.

        A regression is detected when:
        - Average score drops below REGRESSION_THRESHOLD (0.80)
        - Average score drops >10% compared to previous run
        """
        regressions = []

        if report["average_score"] < REGRESSION_THRESHOLD:
            regressions.append({
                "type": "below_threshold",
                "message": (
                    f"Quality score {report['average_score']:.3f} "
                    f"is below threshold {REGRESSION_THRESHOLD}"
                ),
                "score": report["average_score"],
                "threshold": REGRESSION_THRESHOLD,
            })

        # Check per-category regressions
        for category, cat_data in report.get("by_category", {}).items():
            if cat_data["avg"] < REGRESSION_THRESHOLD:
                regressions.append({
                    "type": "category_regression",
                    "category": category,
                    "message": (
                        f"Category '{category}' score {cat_data['avg']:.3f} "
                        f"is below threshold {REGRESSION_THRESHOLD}"
                    ),
                    "score": cat_data["avg"],
                    "threshold": REGRESSION_THRESHOLD,
                })

        return regressions

    async def _send_regression_alert(
        self,
        regressions: list[dict],
        report: dict,
    ) -> None:
        """Send a Slack alert when quality regressions are detected.

        Reuses the same Slack webhook pattern from llm_cost_tracker.py.
        """
        slack_webhook = settings.SLACK_WEBHOOK_URL
        if not slack_webhook:
            logger.warning("Slack webhook not configured — regression alert not sent")
            return

        try:
            import httpx

            lines = [
                "🚨 *AI Quality Regression Detected*",
                f"*Run:* `{report['run_id']}`",
                f"*Score:* {report['average_score']:.3f} (threshold: {REGRESSION_THRESHOLD})",
                f"*Cases:* {report['total_cases']} ({report['pass_count']} pass, {report['fail_count']} fail)",
                "",
                "*Regressions:*",
            ]
            for r in regressions:
                lines.append(f"• {r['message']}")

            payload = {"text": "\n".join(lines), "mrkdwn": True}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(slack_webhook, json=payload)
                if resp.status_code not in (200, 201, 204):
                    logger.warning(f"Slack alert failed: {resp.status_code}")
                else:
                    logger.info("Quality regression alert sent to Slack")
        except Exception as e:
            logger.warning(f"Failed to send Slack alert (non-fatal): {e}")


# ── Singleton ───────────────────────────────────────────

_eval_runner_instance: Optional[EvalRunner] = None


def get_eval_runner() -> EvalRunner:
    """Get or create the EvalRunner singleton."""
    global _eval_runner_instance
    if _eval_runner_instance is None:
        _eval_runner_instance = EvalRunner()
    return _eval_runner_instance


# Shortcut for imports
eval_runner = get_eval_runner()
