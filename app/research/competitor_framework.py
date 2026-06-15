"""Competitor Framework — 8-Point competitor analysis from BoomerDev methodology.

Integrates the structured 8-point framework for competitor analysis:
- WHO: Founding year, team, funding, HQ
- WHERE: Geographic presence, distribution channels
- CLIENTS: ICP, notable clients, use cases
- TECH: Stack, integrations, mobile
- FOUNDERS: Background, network
- INVESTORS + SOURCES: Investor list, funding rounds
- MODEL: Pricing, monetization, unit economics
- MVP: Core features, differentiation, stage
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class CompetitorProfile:
    """Complete 8-point competitor profile."""

    name: str
    website: Optional[str] = None

    # WHO
    founding_year: Optional[str] = None
    team_size: Optional[str] = None
    funding_total: Optional[str] = None
    headquarters: Optional[str] = None

    # WHERE
    geographic_presence: list[str] = field(default_factory=list)
    distribution_channels: list[str] = field(default_factory=list)

    # CLIENTS
    icp_description: Optional[str] = None
    notable_clients: list[str] = field(default_factory=list)
    primary_use_cases: list[str] = field(default_factory=list)

    # TECH
    technology_stack: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    mobile_available: bool = False

    # FOUNDERS
    founder_names: list[str] = field(default_factory=list)
    founder_background: Optional[str] = None
    founder_network: Optional[str] = None

    # INVESTORS
    investors: list[str] = field(default_factory=list)
    latest_funding_round: Optional[str] = None
    funding_sources: list[str] = field(default_factory=list)

    # MODEL
    pricing_plans: list[str] = field(default_factory=list)
    monetization_strategy: Optional[str] = None
    cac_estimate: Optional[str] = None
    ltv_estimate: Optional[str] = None

    # MVP
    core_features: list[str] = field(default_factory=list)
    unique_differentiation: Optional[str] = None
    stage: Optional[str] = None  # idea / mvp / growth / scale

    # Metadata
    source: str = "research"
    confidence: float = 0.5  # 0.0 - 1.0


# ── Research sources mapping ───────────────────────────

RESEARCH_SOURCES = {
    "crunchbase": "Funding, investors, founders, founding year",
    "linkedin": "Team size, founder background, employees",
    "g2": "User reviews, feature comparisons, ratings",
    "trustpilot": "Customer satisfaction, pain points",
    "reddit": "Authentic user feedback, community sentiment",
    "similarweb": "Traffic estimation, geographic distribution",
}


def build_profile_from_research(
    name: str,
    description: str = "",
    website: Optional[str] = None,
    strengths: Optional[List[str]] = None,
    weaknesses: Optional[List[str]] = None,
    pain_points: Optional[List[str]] = None,
    funding: Optional[str] = None,
    business_model: Optional[str] = None,
    target_market: Optional[str] = None,
    source: str = "research",
    confidence: float = 0.5,
) -> CompetitorProfile:
    """Build a CompetitorProfile from existing research data.

    Maps the existing ResearchReport.Competitor data into the
    8-point framework. Fields not available from research are
    left as None for the LLM to fill in later.
    """
    profile = CompetitorProfile(
        name=name,
        website=website,
        funding_total=funding,
        monetization_strategy=business_model,
        icp_description=target_market,
        source=source,
        confidence=confidence,
    )

    # Strengths are competitor advantages, used as gap references for differentiation
    if strengths:
        profile.unique_differentiation = strengths[0] if strengths else None
        profile.core_features = strengths[:5]

    logger.info(f"Built 8-point profile for {name} (confidence: {confidence:.0%})")

    return profile


def format_profile_report(profile: CompetitorProfile) -> str:
    """Format CompetitorProfile as structured markdown report."""
    lines = [f"# Competitor Analysis: {profile.name}", ""]

    # WHO
    lines.append("## WHO")
    if profile.founding_year:
        lines.append(f"- **Founded:** {profile.founding_year}")
    if profile.team_size:
        lines.append(f"- **Team:** {profile.team_size}")
    if profile.funding_total:
        lines.append(f"- **Funding:** {profile.funding_total}")
    if profile.headquarters:
        lines.append(f"- **HQ:** {profile.headquarters}")
    if profile.founder_names:
        lines.append(f"- **Founders:** {', '.join(profile.founder_names)}")
    lines.append("")

    # WHERE
    lines.append("## WHERE")
    if profile.geographic_presence:
        lines.append(f"- **Presence:** {', '.join(profile.geographic_presence)}")
    if profile.distribution_channels:
        lines.append(f"- **Channels:** {', '.join(profile.distribution_channels)}")
    lines.append("")

    # CLIENTS
    lines.append("## CLIENTS")
    if profile.icp_description:
        lines.append(f"- **ICP:** {profile.icp_description}")
    if profile.notable_clients:
        lines.append(f"- **Notable:** {', '.join(profile.notable_clients)}")
    if profile.primary_use_cases:
        lines.append(f"- **Use Cases:** {', '.join(profile.primary_use_cases)}")
    lines.append("")

    # TECH
    lines.append("## TECH")
    if profile.technology_stack:
        lines.append(f"- **Stack:** {', '.join(profile.technology_stack)}")
    if profile.integrations:
        lines.append(f"- **Integrations:** {', '.join(profile.integrations)}")
    lines.append(f"- **Mobile:** {'Yes' if profile.mobile_available else 'No'}")
    lines.append("")

    # FOUNDERS
    lines.append("## FOUNDERS")
    if profile.founder_background:
        lines.append(f"- **Background:** {profile.founder_background}")
    if profile.founder_network:
        lines.append(f"- **Network:** {profile.founder_network}")
    lines.append("")

    # INVESTORS
    lines.append("## INVESTORS + SOURCES")
    if profile.investors:
        lines.append(f"- **Investors:** {', '.join(profile.investors)}")
    if profile.latest_funding_round:
        lines.append(f"- **Latest Round:** {profile.latest_funding_round}")
    if profile.funding_sources:
        lines.append(f"- **Sources:** {', '.join(profile.funding_sources)}")
    lines.append("")

    # MODEL
    lines.append("## MODEL")
    if profile.pricing_plans:
        lines.append(f"- **Plans:** {', '.join(profile.pricing_plans)}")
    if profile.monetization_strategy:
        lines.append(f"- **Strategy:** {profile.monetization_strategy}")
    if profile.cac_estimate:
        lines.append(f"- **CAC:** {profile.cac_estimate}")
    if profile.ltv_estimate:
        lines.append(f"- **LTV:** {profile.ltv_estimate}")
    lines.append("")

    # MVP
    lines.append("## MVP")
    if profile.core_features:
        lines.append("### Core Features")
        for f in profile.core_features[:5]:
            lines.append(f"- {f}")
    if profile.unique_differentiation:
        lines.append(f"- **Differentiation:** {profile.unique_differentiation}")
    if profile.stage:
        lines.append(f"- **Stage:** {profile.stage}")
    lines.append("")

    lines.append(f"*Confidence: {profile.confidence:.0%} | Source: {profile.source}*")

    return "\n".join(lines)


def get_research_sources_guide() -> str:
    """Return the recommended research sources for competitive analysis."""
    lines = ["## Recommended Research Sources", ""]
    for source, purpose in RESEARCH_SOURCES.items():
        lines.append(f"- **{source.title()}**: {purpose}")
    return "\n".join(lines)
