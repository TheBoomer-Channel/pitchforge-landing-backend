"""Functional Spec Generator — features, user flows, UX from research data."""

import json
import logging
import re
from typing import Optional

from app.services.llm import llm
from .models import FunctionalSpec
from app.research.models import ResearchReport

logger = logging.getLogger(__name__)

# ── Module-level integration keyword → service name mapping ──
# Ordered from most specific to least specific to avoid over-matching.
# Keys with spaces or 4+ chars are word-boundary matched to avoid false positives.
_INTEGRATION_KEYWORDS: list[tuple[str, str]] = [
    ("social login", "Social Login (Google/GitHub)"),
    ("oauth", "OAuth 2.0 Provider"),
    ("stripe", "Stripe Payments"),
    ("github", "GitHub API"),
    ("gitlab", "GitLab API"),
    ("slack", "Slack API"),
    ("discord", "Discord API"),
    ("sendgrid", "Email Service (SendGrid)"),
    ("postmark", "Email Service (Postmark)"),
    ("smtp", "Email Service (SMTP)"),
    ("calendar", "Google Calendar API"),
    ("webhook", "Webhook Outbound"),
    ("s3", "AWS S3 / Cloudflare R2"),
    ("cdn", "CDN (Cloudflare)"),
    ("analytics", "Analytics (PostHog/Plausible)"),
    ("search", "Search Engine (Meilisearch/Algolia)"),
    ("monitoring", "Monitoring (Sentry)"),
    ("backup", "Backup Service"),
    ("video", "Video Service (Mux/Vimeo)"),
    ("notifications", "Push Notifications (OneSignal/Firebase)"),
    ("chat", "Real-time Chat (WebSocket)"),
    ("storage", "Cloud Storage (S3/R2)"),
    ("upload", "File Storage (S3/R2)"),
    ("payment", "Stripe Payments"),
    ("auth", "Authentication Provider (Supabase/Auth0)"),
    # Broad keywords (3 chars) — checked last, with word boundaries
    ("api", "REST API"),
    ("log", "Logging (Sentry/Grafana)"),
    ("cron", "Background Jobs (Arq/Redis)"),
    ("queue", "Job Queue (Redis/Arq)"),
]

# Canonical names for deduplication — if two keywords map to the same canonical, only first wins
_CANONICAL_INTEGRATIONS = {
    "Stripe Payments": "Stripe Payments",
    "Email Service (SendGrid)": "Email Service",
    "Email Service (Postmark)": "Email Service",
    "Email Service (SMTP)": "Email Service",
    "Email Service (SendGrid/Postmark)": "Email Service",
    "Push Notifications": "Push Notifications",
    "Push Notifications (OneSignal/Firebase)": "Push Notifications",
    "File Storage (S3/R2)": "File Storage",
    "Cloud Storage (S3/R2)": "File Storage",
}


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a word boundary in text.
    For multi-word keywords or keywords >= 4 chars, use simple containment.
    For short single-word keywords (<=3 chars), require word boundaries.
    """
    if " " in keyword or len(keyword) >= 4:
        return keyword in text
    # 3-char keyword like 'api', 'log', 'cron': require word boundaries
    return bool(re.search(rf'\b{re.escape(keyword)}\b', text))


def _deterministic_functional(report: ResearchReport) -> FunctionalSpec:
    """Build functional spec from research report data without LLM.
    
    TASK-062 — Uses competitive pain points for feature prioritization.
    TASK-062-filled — user_personas, integration_points, data_privacy_notes, feature_roadmap.
    """
    features = report.recommended_mvp_features or []
    
    # Use CompetitorAnalyzer pain summary for prioritization
    insights = report.competitive_insights or {}
    pain_summary = insights.get("pain_summary", {})
    critical_pains = set(pain_summary.get("critical", []))
    common_pains = set(pain_summary.get("common", []))
    
    # Prioritize: features solving critical pains → P0, common pains → P1, rest → P2
    core_features = []
    for i, f in enumerate(features):
        name = f.split("(")[0].strip() if "(" in f else f
        # Check if this feature relates to any critical/comon pain
        fl = f.lower()
        is_critical = any(p.lower()[:20] in fl for p in critical_pains)
        is_common = any(p.lower()[:20] in fl for p in common_pains)
        if is_critical or i < 2:
            priority = "P0"
        elif is_common or i < 5:
            priority = "P1"
        else:
            priority = "P2"
        core_features.append({
            "id": f"F{i+1}",
            "name": name,
            "description": f,
            "priority": priority,
            "acceptance_criteria": ["Works end-to-end", "User can complete the flow"],
            "effort": "medium",
        })

    # ── Derive user personas from competitor data ──────
    user_personas = []
    if report.competitors:
        seen_markets = set()
        for c in report.competitors[:4]:
            market = (c.target_market or "").strip()
            if not market or market.lower() in seen_markets:
                continue
            seen_markets.add(market.lower())
            user_personas.append({
                "name": f"{market} User",
                "role": market,
                "goals": (c.strengths[:3] if c.strengths else ["Complete tasks efficiently", "Save time", "Achieve results"]),
                "pain_points": (c.pain_points[:3] if c.pain_points else ["Fragmented tools", "Manual overhead", "Poor UX"]),
                "tech_level": "medium",
            })
    if not user_personas:
        user_personas.append({
            "name": "Early Adopter",
            "role": "Product user",
            "goals": ["Solve core problem efficiently", "Save time and money", "Get reliable results"],
            "pain_points": ["Existing solutions are too complex", "No integrated workflow", "High cost of alternatives"],
            "tech_level": "medium",
        })

    # ── Extract integration points from feature names ──
    integration_points = []
    seen_canonical = set()
    all_text = " ".join(features).lower() + " " + report.summary.lower()
    for keyword, service in _INTEGRATION_KEYWORDS:
        canonical = _CANONICAL_INTEGRATIONS.get(service, service)
        if canonical in seen_canonical:
            continue
        if _word_match(keyword, all_text):
            integration_points.append(service)
            seen_canonical.add(canonical)
    # Always add essential infrastructure (use canonical to avoid duplicates)
    _ESSENTIALS = [
        ("Stripe Payments", "Stripe Payments"),
        ("Email Service", "Email Service (SendGrid/Postmark)"),
        ("Error Tracking", "Error Tracking (Sentry)"),
    ]
    for canonical, display in _ESSENTIALS:
        if canonical not in seen_canonical:
            integration_points.append(display)
            seen_canonical.add(canonical)

    # ── Data privacy notes ─────────────────────────────
    data_privacy_notes = [
        "Encrypt data at rest (AES-256) and in transit (TLS 1.3)",
        "Implement GDPR-compliant data export and deletion (Right to Access / Right to be Forgotten)",
        "Cookie consent banner with opt-out for non-essential cookies",
        "Publish clear Privacy Policy detailing data collection, usage, and sharing",
        "Apply data minimization — only collect what is necessary for core functionality",
        "Conduct regular security audits and dependency vulnerability scans",
    ]
    if any(kw in all_text for kw in ["payment", "stripe", "billing", "subscription"]):
        data_privacy_notes.append("Use Stripe for PCI-compliant payment processing; never store raw credit card data")

    # ── Feature roadmap from priority tiers ────────────
    p0_ids = [f["id"] for f in core_features if f["priority"] == "P0"]
    p1_ids = [f["id"] for f in core_features if f["priority"] == "P1"]
    p2_ids = [f["id"] for f in core_features if f["priority"] == "P2"]
    feature_roadmap = []
    if p0_ids:
        feature_roadmap.append({
            "phase": "MVP (Sprint 1-2)",
            "features": p0_ids,
            "goal": "Core value proposition working end-to-end",
            "estimate": "2-3 weeks",
        })
    if p1_ids:
        feature_roadmap.append({
            "phase": "v1.1 — Enhance (Sprint 3-4)",
            "features": p1_ids,
            "goal": "Important features that improve retention",
            "estimate": "2 weeks",
        })
    if p2_ids:
        feature_roadmap.append({
            "phase": "v1.2+ — Polish (Sprint 5+)",
            "features": p2_ids,
            "goal": "Nice-to-haves and polish for growth",
            "estimate": "2+ weeks",
        })

    return FunctionalSpec(
        user_personas=user_personas,
        core_features=core_features,
        user_journeys=[
            {"scenario": "First-time user onboarding", "steps": ["Land on homepage", "Sign up", "Complete profile", "Use core feature"]},
            {"scenario": "Daily active use", "steps": ["Login", "Access main dashboard", "Perform key action", "View results"]},
        ],
        non_functional_reqs=[
            {"category": "performance", "requirement": "Page load < 3s"},
            {"category": "availability", "requirement": "99.5% uptime SLA"},
            {"category": "security", "requirement": "HTTPS, auth, data encryption"},
        ],
        integration_points=integration_points,
        data_privacy_notes=data_privacy_notes,
        ui_principles=["Mobile-first responsive", "Dark theme", "Minimal clicks to core action"],
        feature_roadmap=feature_roadmap,
    )


async def generate_functional(report: ResearchReport, use_llm: bool = True) -> FunctionalSpec:
    """Generate functional specification using DeepSeek Pro."""
    if not use_llm:
        return _deterministic_functional(report)
    try:
        features_text = "\n".join(f"- {f}" for f in (report.recommended_mvp_features or []))
        competitors_text = "\n".join(
            f"- {c.name}: strengths={c.strengths[:2] if c.strengths else 'N/A'}, weaknesses={c.weaknesses[:2] if c.weaknesses else 'N/A'}"
            for c in report.competitors[:4]
        )

        prompt = f"""You are a senior product designer / UX architect. Generate a complete Functional Specification for the following product.

PRODUCT: {report.idea}
POSITIONING: {report.recommended_positioning or "Not specified"}

=== RESEARCH CONTEXT ===

RECOMMENDED MVP FEATURES:
{features_text or "Not specified"}

COMPETITOR UX INSIGHTS:
{competitors_text or "No competitors found"}

=== TASK ===

Produce a structured JSON with EXACTLY this shape (ONLY JSON, no markdown):

{{{{
  "user_personas": [
    {{{{ "name": "Persona name", "role": "Job title / role", "goals": ["Goal 1", "Goal 2"], "pain_points": ["Pain 1", "Pain 2"], "tech_level": "low/medium/high" }}}}
  ],
  "core_features": [
    {{{{ "id": "F1", "name": "Feature name", "description": "What it does in 1-2 sentences", "priority": "P0", "acceptance_criteria": ["Criterion 1", "Criterion 2"], "effort": "low/medium/high" }}}}
  ],
  "user_journeys": [
    {{{{ "scenario": "End-to-end scenario name", "steps": ["Step 1", "Step 2", "Step 3", "Step 4"] }}}}
  ],
  "non_functional_reqs": [
    {{{{ "category": "performance/security/scalability/usability/reliability", "requirement": "Specific measurable requirement" }}}}
  ],
  "integration_points": [
    "External API or service name"
  ],
  "data_privacy_notes": [
    "Privacy consideration"
  ],
  "ui_principles": [
    "Design principle for the product"
  ],
  "feature_roadmap": [
    {{{{ "phase": "MVP (Weeks 1-4)", "features": ["F1", "F2", "F3"], "estimate": "4 weeks" }}}}
  ]
}}}}

Rules:
- Personas MUST be specific to the target market
- Feature priorities: P0=must have for MVP, P1=important but can wait, P2=nice to have
- Acceptance criteria MUST be testable (pass/fail)
- Non-functional reqs MUST be specific and measurable
- Journeys should cover: onboarding + core action + power user path
- OUTPUT ONLY THE JSON OBJECT."""

        result = await llm.json_pro(prompt, temperature=0.2, max_tokens=4096, timeout=180)
        d = result
        if d:
            return FunctionalSpec(**d)

        logger.warning("Failed to parse Functional JSON, using deterministic")
        return _deterministic_functional(report)

    except Exception as e:
        logger.warning(f"Functional LLM failed: {e}, using deterministic fallback")
        return _deterministic_functional(report)
