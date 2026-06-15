"""Methodology — 3-Gate Idea Filter from BoomerDev PitchForge methodology.

Integrates the "Criterio de 3 Puertas" evaluation framework:
- Gate 1 (Pain): Is the problem real? Do people pay? Are there competitors?
- Gate 2 (Feasibility): Can we build it? MVP in <2 weeks? No blocking dependencies?
- Gate 3 (Distribution): Can we reach the ICP organically? Communities? Freemium?

Includes the weighted Scorecard for quantitative evaluation.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of a single gate evaluation."""
    gate: str
    passed: bool
    score: float  # 1-5
    reasoning: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class IdeaFilterResult:
    """Complete 3-Gate + Scorecard evaluation result."""
    idea: str
    passed: bool
    total_score: float  # Weighted score 1-5
    min_required: float = 3.5

    gate_pain: Optional[GateResult] = None
    gate_feasibility: Optional[GateResult] = None
    gate_distribution: Optional[GateResult] = None

    # Scorecard breakdown
    score_pain_validated: float = 0.0       # 25%
    score_competitors: float = 0.0           # 10%
    score_market_size: float = 0.0           # 15%
    score_stack_known: float = 0.0           # 15%
    score_mvp_2weeks: float = 0.0            # 15%
    score_organic_channel: float = 0.0       # 10%
    score_pricing: float = 0.0               # 10%

    recommendations: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


# ── Weight configuration ───────────────────────────────

SCORECARD_WEIGHTS = {
    "pain_validated": 0.25,
    "competitors_existing": 0.10,
    "market_size": 0.15,
    "stack_known": 0.15,
    "mvp_2weeks": 0.15,
    "organic_channel": 0.10,
    "pricing_gt_9": 0.10,
}

GATE_PASS_THRESHOLD = 3.0  # Each gate must score >= 3.0


# ── 3-Gate Filter ──────────────────────────────────────

def evaluate_idea(
    idea: str,
    target_market: str = "",
    business_model: str = "",
    has_competitors: bool = False,
    competitor_count: int = 0,
    market_size_estimate: str = "",
    known_stack: bool = True,
    mvp_feasible_2weeks: bool = True,
    organic_channel_available: bool = False,
    pricing_gt_9: bool = True,
    reddit_posts: int = 0,
    hn_mentions: int = 0,
    research_summary: str = "",
) -> IdeaFilterResult:
    """Evaluate a startup idea through the 3-Gate filter.

    Args:
        idea: The startup idea description.
        target_market: Target market/industry.
        business_model: Business model description.
        has_competitors: Whether competitors were found in research.
        competitor_count: Number of competitors found.
        market_size_estimate: TAM/SAM estimate from research.
        known_stack: Whether the stack is known/familiar.
        mvp_feasible_2weeks: Whether MVP can be built in 2 weeks.
        organic_channel_available: Whether organic distribution channels exist.
        pricing_gt_9: Whether pricing > $9/month is viable.
        reddit_posts: Reddit posts found.
        hn_mentions: HN mentions found.
        research_summary: Summary from research report.

    Returns:
        IdeaFilterResult with scores and pass/fail status.
    """
    logger.info(f"Evaluating idea through 3-Gate filter: {idea[:80]}")

    # ── Gate 1: Pain ──
    pain_score, pain_reasoning, pain_evidence = _evaluate_pain(
        has_competitors, competitor_count, reddit_posts, hn_mentions, research_summary
    )
    gate_pain = GateResult(
        gate="Pain (¿Duele?)",
        passed=pain_score >= GATE_PASS_THRESHOLD,
        score=pain_score,
        reasoning=pain_reasoning,
        evidence=pain_evidence,
    )

    # ── Gate 2: Feasibility ──
    feasibility_score, feasibility_reasoning, feasibility_evidence = _evaluate_feasibility(
        known_stack, mvp_feasible_2weeks, idea
    )
    gate_feasibility = GateResult(
        gate="Feasibility (¿Podemos?)",
        passed=feasibility_score >= GATE_PASS_THRESHOLD,
        score=feasibility_score,
        reasoning=feasibility_reasoning,
        evidence=feasibility_evidence,
    )

    # ── Gate 3: Distribution ──
    distribution_score, distribution_reasoning, distribution_evidence = _evaluate_distribution(
        organic_channel_available, reddit_posts, hn_mentions, pricing_gt_9, target_market
    )
    gate_distribution = GateResult(
        gate="Distribution (¿Hay canal?)",
        passed=distribution_score >= GATE_PASS_THRESHOLD,
        score=distribution_score,
        reasoning=distribution_reasoning,
        evidence=distribution_evidence,
    )

    # ── Scorecard ──
    score_pain = min(5.0, pain_score)
    score_comp = min(5.0, 1 + competitor_count * 0.5) if competitor_count > 0 else 1.0
    score_market = _estimate_market_score(market_size_estimate)
    score_stack = 5.0 if known_stack else 2.0
    score_mvp = 5.0 if mvp_feasible_2weeks else 2.0
    score_channel = 4.0 if organic_channel_available else 1.5
    score_pricing = 4.0 if pricing_gt_9 else 1.0

    total_score = (
        score_pain * SCORECARD_WEIGHTS["pain_validated"]
        + score_comp * SCORECARD_WEIGHTS["competitors_existing"]
        + score_market * SCORECARD_WEIGHTS["market_size"]
        + score_stack * SCORECARD_WEIGHTS["stack_known"]
        + score_mvp * SCORECARD_WEIGHTS["mvp_2weeks"]
        + score_channel * SCORECARD_WEIGHTS["organic_channel"]
        + score_pricing * SCORECARD_WEIGHTS["pricing_gt_9"]
    )

    total_score = round(total_score, 1)
    passed = total_score >= 3.5 and all(
        g.passed for g in [gate_pain, gate_feasibility, gate_distribution]
    )

    recommendations = _generate_recommendations(
        gate_pain, gate_feasibility, gate_distribution, total_score
    )

    risks = []
    if not gate_pain.passed:
        risks.append(f"Pain not sufficiently validated (score: {pain_score:.1f}/5)")
    if not gate_feasibility.passed:
        risks.append(f"Feasibility concerns (score: {feasibility_score:.1f}/5)")
    if not gate_distribution.passed:
        risks.append(f"Distribution channel unclear (score: {distribution_score:.1f}/5)")
    if total_score < 3.5:
        risks.append(f"Overall score below threshold ({total_score:.1f}/5)")

    result = IdeaFilterResult(
        idea=idea,
        passed=passed,
        total_score=total_score,
        gate_pain=gate_pain,
        gate_feasibility=gate_feasibility,
        gate_distribution=gate_distribution,
        score_pain_validated=round(score_pain, 1),
        score_competitors=round(score_comp, 1),
        score_market_size=round(score_market, 1),
        score_stack_known=round(score_stack, 1),
        score_mvp_2weeks=round(score_mvp, 1),
        score_organic_channel=round(score_channel, 1),
        score_pricing=round(score_pricing, 1),
        recommendations=recommendations,
        risks=risks,
    )

    status = "PASSED" if passed else "FAILED"
    logger.info(f"Idea filter: {status} (score: {total_score:.1f}/5, min: 3.5)")

    return result


def _evaluate_pain(
    has_competitors: bool,
    competitor_count: int,
    reddit_posts: int,
    hn_mentions: int,
    summary: str,
) -> tuple[float, str, list[str]]:
    """Evaluate Gate 1: Is there real pain?"""
    evidence = []
    score = 1.0

    if has_competitors and competitor_count > 0:
        score += 1.5
        evidence.append(f"{competitor_count} competitors found — market validation")
    elif has_competitors:
        score += 0.5
        evidence.append("Some competitive activity detected")

    if reddit_posts > 10:
        score += 1.5
        evidence.append(f"{reddit_posts} Reddit discussions — active community")
    elif reddit_posts > 0:
        score += 0.5
        evidence.append(f"{reddit_posts} Reddit posts found")

    if hn_mentions > 0:
        score += 0.5
        evidence.append(f"{hn_mentions} HN mentions")

    if summary:
        summary_lower = summary.lower()
        if any(word in summary_lower for word in ["gap", "need", "problem", "pain", "demand"]):
            score += 0.5
            evidence.append("Research summary indicates market need")

    if competitor_count >= 3:
        score += 0.5
        evidence.append("Multiple competitors — strong signal of paying market")

    score = min(5.0, score)

    if score >= 4.0:
        reasoning = "Strong pain validation — clear market demand with multiple signals."
    elif score >= 3.0:
        reasoning = "Moderate pain signals — market exists but could be stronger."
    elif score >= 2.0:
        reasoning = "Weak pain signals — limited evidence of real problem."
    else:
        reasoning = "No pain validation — consider pivoting or deeper research."

    return score, reasoning, evidence


def _evaluate_feasibility(
    known_stack: bool,
    mvp_feasible_2weeks: bool,
    idea: str,
) -> tuple[float, str, list[str]]:
    """Evaluate Gate 2: Can we build it?"""
    evidence = []
    score = 1.0

    if known_stack:
        score += 2.0
        evidence.append("Stack is known (FastAPI, React) — low technical risk")

    if mvp_feasible_2weeks:
        score += 1.5
        evidence.append("MVP feasible in <2 weeks with AI agents")
    else:
        score += 0.5

    # Check for blocking dependencies
    blocking_keywords = ["hardware", "physical", "regulation", "fda", "compliance", "license"]
    has_blockers = any(kw in idea.lower() for kw in blocking_keywords)
    if not has_blockers:
        score += 0.5
        evidence.append("No blocking external dependencies detected")

    score = min(5.0, score)

    if score >= 4.0:
        reasoning = "Highly feasible — familiar stack, quick MVP, no blockers."
    elif score >= 3.0:
        reasoning = "Feasible with some challenges — manageable technical risk."
    elif score >= 2.0:
        reasoning = "Difficult to build — consider simplifying scope or acquiring skills."
    else:
        reasoning = "Not feasible with current resources — consider different idea."

    return score, reasoning, evidence


def _evaluate_distribution(
    organic_channel: bool,
    reddit_posts: int,
    hn_mentions: int,
    pricing_gt_9: bool,
    target_market: str,
) -> tuple[float, str, list[str]]:
    """Evaluate Gate 3: Can we reach the ICP?"""
    evidence = []
    score = 1.0

    if organic_channel:
        score += 1.5
        evidence.append("Organic distribution channel available")

    if reddit_posts > 0 or hn_mentions > 0:
        score += 1.0
        evidence.append(f"Community presence: Reddit ({reddit_posts}), HN ({hn_mentions})")

    if pricing_gt_9:
        score += 1.0
        evidence.append("Pricing model supports viral/freemium growth")

    if target_market:
        score += 0.5
        evidence.append(f"Target market defined: {target_market}")

    score = min(5.0, score)

    if score >= 4.0:
        reasoning = "Clear distribution channels — organic reach viable."
    elif score >= 3.0:
        reasoning = "Moderate distribution potential — some channels available."
    elif score >= 2.0:
        reasoning = "Weak distribution — limited organic reach options."
    else:
        reasoning = "No distribution channel — will require paid acquisition from day 1."

    return score, reasoning, evidence


def _estimate_market_score(market_size: str) -> float:
    """Estimate market size score from TAM/SAM string."""
    if not market_size:
        return 2.0
    size_lower = market_size.lower()
    # Use word boundaries so "m" doesn't match "medium", "small", etc.
    import re
    if re.search(r'\bbillion\b|\bbn\b', size_lower):
        return 5.0
    if re.search(r'\bmillion\b|\b[0-9]+m\b', size_lower):
        return 3.5
    if "large" in size_lower or "growing" in size_lower:
        return 3.0
    return 2.0


def _generate_recommendations(
    pain: GateResult,
    feasibility: GateResult,
    distribution: GateResult,
    total_score: float,
) -> list[str]:
    """Generate actionable recommendations based on gate results."""
    recs = []

    if not pain.passed:
        recs.append("Run deeper customer interviews to validate pain before building")
        recs.append("Search more communities (Reddit, HN, niche forums) for problem signals")
    if not feasibility.passed:
        recs.append("Simplify MVP scope — cut features to fit 2-week build window")
        recs.append("Consider using pre-built SaaS starter kits to accelerate development")
    if not distribution.passed:
        recs.append("Identify at least 1 organic distribution channel before starting")
        recs.append("Build a waitlist / landing page to test ICP reach before coding")

    if total_score >= 4.0:
        recs.append("High potential idea — proceed to full planning pipeline")
    elif total_score >= 3.5:
        recs.append("Viable idea — proceed to planning with noted risks")
    elif total_score >= 2.5:
        recs.append("Needs refinement — address weak areas and re-evaluate")
    else:
        recs.append("Consider pivoting to a different idea with stronger signals")

    return recs


# ── Research integration helper ────────────────────────

def filter_from_research(idea: str, report_summary: str = "",
                         competitor_count: int = 0,
                         reddit_posts: int = 0, hn_mentions: int = 0,
                         market_size: str = "", target_market: str = "",
                         business_model: str = "",
                         known_stack: bool = True,
                         mvp_feasible_2weeks: bool = True,
                         pricing_gt_9: bool = True) -> IdeaFilterResult:
    """Quick evaluation from research report data.

    This is the primary integration point — call this after running
    ResearchEngine.run() to get a 3-Gate evaluation of the idea.

    Defaults assume familiar FastAPI+React stack and AI-assisted MVP,
    but these can be overridden for non-standard ideas.
    """
    return evaluate_idea(
        idea=idea,
        target_market=target_market,
        business_model=business_model,
        has_competitors=competitor_count > 0,
        competitor_count=competitor_count,
        market_size_estimate=market_size,
        known_stack=known_stack,
        mvp_feasible_2weeks=mvp_feasible_2weeks,
        organic_channel_available=reddit_posts > 5 or hn_mentions > 0,
        pricing_gt_9=pricing_gt_9,
        reddit_posts=reddit_posts,
        hn_mentions=hn_mentions,
        research_summary=report_summary,
    )


def format_filter_report(result: IdeaFilterResult) -> str:
    """Format IdeaFilterResult as readable markdown report."""
    lines = []
    status = "PASSED" if result.passed else "FAILED"
    icon = "✅" if result.passed else "❌"

    lines.append(f"# Idea Filter Report: {result.idea[:60]}")
    lines.append("")
    lines.append(f"**Result:** {icon} {status} ({result.total_score:.1f}/5.0)")
    lines.append(f"**Minimum required:** {result.min_required}/5.0")
    lines.append("")

    lines.append("## 3-Gate Evaluation")
    lines.append("")

    for gate in [result.gate_pain, result.gate_feasibility, result.gate_distribution]:
        if gate is None:
            continue
        gicon = "✅" if gate.passed else "❌"
        lines.append(f"### {gicon} Gate: {gate.gate}")
        lines.append(f"**Score:** {gate.score:.1f}/5.0")
        lines.append(f"**Reasoning:** {gate.reasoning}")
        if gate.evidence:
            lines.append("**Evidence:**")
            for e in gate.evidence:
                lines.append(f"- {e}")
        lines.append("")

    lines.append("## Scorecard Breakdown")
    lines.append("")
    lines.append("| Criterion | Weight | Score | Weighted |")
    lines.append("|-----------|--------|-------|----------|")
    lines.append(f"| Pain Validated | 25% | {result.score_pain_validated:.1f} | {result.score_pain_validated * 0.25:.1f} |")
    lines.append(f"| Competitors Exist | 10% | {result.score_competitors:.1f} | {result.score_competitors * 0.10:.1f} |")
    lines.append(f"| Market Size | 15% | {result.score_market_size:.1f} | {result.score_market_size * 0.15:.1f} |")
    lines.append(f"| Stack Known | 15% | {result.score_stack_known:.1f} | {result.score_stack_known * 0.15:.1f} |")
    lines.append(f"| MVP in 2 Weeks | 15% | {result.score_mvp_2weeks:.1f} | {result.score_mvp_2weeks * 0.15:.1f} |")
    lines.append(f"| Organic Channel | 10% | {result.score_organic_channel:.1f} | {result.score_organic_channel * 0.10:.1f} |")
    lines.append(f"| Pricing > $9/mo | 10% | {result.score_pricing:.1f} | {result.score_pricing * 0.10:.1f} |")
    lines.append(f"| **TOTAL** | **100%** | | **{result.total_score:.1f}** |")
    lines.append("")

    if result.recommendations:
        lines.append("## Recommendations")
        lines.append("")
        for r in result.recommendations:
            lines.append(f"- {r}")
        lines.append("")

    if result.risks:
        lines.append("## Risks")
        lines.append("")
        for r in result.risks:
            lines.append(f"- ⚠️ {r}")
        lines.append("")

    return "\n".join(lines)
