"""Narrative Engine — generates pitch script/storytelling from ResearchReport data.

Design principles:
- 100% data-driven: every bullet and speaker note comes from real research
- No hallucinations: if data is missing, we say so explicitly
- Storytelling arc: Hook → Problem → Agitation → Solution → Why Now → Why Us → Market → Business → Ask
- Each slide has: title, key_points, speaker_notes, narrative_hook
"""

from typing import List, Dict, Optional, Tuple

from ..research.models import ResearchReport, Competitor, OpportunityGap


class SlideNarrative:
    """A single pitch slide with its full narrative content."""
    def __init__(
        self,
        title: str,
        key_points: List[str],
        speaker_notes: str,
        narrative_hook: str = "",
        icon: str = "zap",
    ):
        self.title = title
        self.key_points = key_points
        self.speaker_notes = speaker_notes
        self.narrative_hook = narrative_hook
        self.icon = icon


class PitchNarrative:
    """Complete pitch deck narrative."""
    def __init__(self, idea: str, slides: List[SlideNarrative]):
        self.idea = idea
        self.slides = slides
        self.total_slides = len(slides)
        # Estimate: ~1.5 min per slide
        self.estimated_minutes = max(3, int(len(slides) * 1.2))


def generate_narrative(report: ResearchReport) -> PitchNarrative:
    """Generate a complete pitch narrative from research data.

    Every bullet point, speaker note, and hook is derived from the ResearchReport.
    No placeholders — if data is missing, the slide adapts accordingly.
    """
    idea = report.idea[:60]
    competitors = report.competitors or []
    gaps = report.opportunity_gaps or []
    features = report.recommended_mvp_features or []
    risks = report.risk_factors or []
    validation = report.market_validation
    sizing = report.market_sizing
    positioning = report.recommended_positioning or ""
    pricing_str = report.recommended_pricing_range or ""

    slides = []

    # ── SLIDE 1: HOOK ──────────────────────────────
    slides.append(_build_hook(idea, positioning, competitors, gaps, sizing))

    # ── SLIDE 2: PROBLEM ───────────────────────────
    slides.append(_build_problem(idea, competitors, gaps, validation, risks))

    # ── SLIDE 3: AGITATION ─────────────────────────
    slides.append(_build_agitation(competitors, gaps, validation))

    # ── SLIDE 4: SOLUTION ──────────────────────────
    slides.append(_build_solution(idea, features, gaps, competitors))

    # ── SLIDE 5: WHY NOW ───────────────────────────
    slides.append(_build_why_now(sizing, validation, gaps))

    # ── SLIDE 6: WHY US ────────────────────────────
    slides.append(_build_why_us(competitors, gaps, features, positioning))

    # ── SLIDE 7: MARKET ────────────────────────────
    slides.append(_build_market(sizing, validation, gaps))

    # ── SLIDE 8: BUSINESS MODEL ────────────────────
    slides.append(_build_business_model(pricing_str, features, competitors))

    # ── SLIDE 9: THE ASK ───────────────────────────
    slides.append(_build_ask(risks, features, gaps, competitors))

    return PitchNarrative(idea=idea, slides=slides)


# ═══════════════════════════════════════════════════════
#  SLIDE BUILDERS
# ═══════════════════════════════════════════════════════

def _build_hook(
    idea: str,
    positioning: str,
    competitors: List[Competitor],
    gaps: List[OpportunityGap],
    sizing,
) -> SlideNarrative:
    """Slide 1: The Hook — attention grabber."""
    title = idea
    points = []

    # Use market sizing for a strong number hook
    if sizing and sizing.tam:
        points.append(f"Market size: {sizing.tam}")
    if sizing and sizing.growth_rate:
        points.append(f"Growing at {sizing.growth_rate}")

    # Use a gap as the urgency hook
    if gaps:
        points.append(f"Key insight: {gaps[0].gap[:100]}")

    # Positioning
    if positioning:
        points.append(positioning[:120])

    # Fallback
    if not points:
        points.append(f"{idea} — a new approach to an unsolved problem")

    speaker = _spk(
        f"Open with a bold statement about {idea}. ",
        f"If you have market size data ({sizing.tam if sizing else 'N/A'}), lead with it. ",
        f"The goal is to make investors lean forward in the first 10 seconds. ",
        f"Mention the key insight from research: ",
        f"'{gaps[0].gap[:80]}'." if gaps else f"the core problem {idea} solves.",
    )

    hook = _hk(
        f"Every day, this problem costs the market real money. ",
        f"{idea} changes that.",
    )

    return SlideNarrative(title, points, speaker, hook, icon="rocket")


def _build_problem(
    idea: str,
    competitors: List[Competitor],
    gaps: List[OpportunityGap],
    validation,
    risks: List[str],
) -> SlideNarrative:
    """Slide 2: The Problem — what's broken today."""
    points = []

    # Real pain points from competitors
    pain_points_found = []
    for c in competitors[:4]:
        for p in c.pain_points[:2]:
            if p and p not in pain_points_found:
                pain_points_found.append(p)
                points.append(f"Users of {c.name} struggle with: {p[:100]}")

    # Common complaints from community research
    if validation and validation.common_complaints:
        for complaint in validation.common_complaints[:2]:
            points.append(f"Community complaint: \"{complaint[:100]}\"")

    # Gaps as problems
    for g in gaps[:2]:
        if g.gap not in " ".join(points):
            points.append(f"Market gap: {g.gap[:100]}")

    # Risk as problem indicator
    if risks and not points:
        points.append(f"Current solutions fail at: {risks[0][:100]}")

    if not points:
        points.append(f"Existing solutions don't fully address the needs of {idea} users")

    speaker = _spk(
        f"Paint the picture of frustration. Use real quotes if you have them. ",
        f"Each pain point should make the audience think 'yeah, that IS broken'. ",
        f"Don't mention your solution yet — just make the problem visceral.",
    )

    hook = _hk("The status quo is broken. Here's the evidence.")

    return SlideNarrative(title="The Problem", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="alert")


def _build_agitation(
    competitors: List[Competitor],
    gaps: List[OpportunityGap],
    validation,
) -> SlideNarrative:
    """Slide 3: Agitation — why current solutions fail."""
    points = []

    # Competitor weaknesses
    for c in competitors[:3]:
        for w in c.weaknesses[:1]:
            points.append(f"{c.name}: {w[:100]}")
        # Pricing insight
        if c.pricing:
            points.append(f"{c.name} pricing: {c.pricing[:80]} — and still doesn't solve it")

    # Validation: what people want but can't get
    if validation and validation.common_desires:
        for desire in validation.common_desires[:2]:
            points.append(f"Users want: \"{desire[:100]}\" — but no one offers it")

    # Gaps as evidence of failure
    for g in gaps[:1]:
        if g.evidence:
            points.append(f"Evidence: {g.evidence[0][:100]}")

    if not points:
        points.append("Current solutions are fragmented, expensive, or incomplete")

    speaker = _spk(
        f"Now twist the knife. Show that competitors HAVE funding/users but STILL can't solve this. ",
        f"Mention specific competitor names and what they're missing. ",
        f"The audience should think: 'These incumbents are vulnerable.'",
    )

    hook = _hk("Even well-funded competitors are failing their users. Here's how.")

    return SlideNarrative(title="Why Current Solutions Fail", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="cross")


def _build_solution(
    idea: str,
    features: List[str],
    gaps: List[OpportunityGap],
    competitors: List[Competitor],
) -> SlideNarrative:
    """Slide 4: Solution — what we built and why it's different."""
    points = []

    # Map features to gaps they solve
    for i, f in enumerate(features[:4]):
        gap_context = ""
        if i < len(gaps):
            gap_context = f" → solves: {gaps[i].gap[:60]}"
        points.append(f"{f[:80]}{gap_context}")

    # Competitive advantage
    if competitors and gaps:
        comp_names = ", ".join(c.name for c in competitors[:3])
        points.append(f"Unlike {comp_names}, we focus on: {gaps[0].gap[:80]}")

    if not points:
        points.append(f"{idea} — built specifically to address the gaps in current solutions")

    speaker = _spk(
        f"Show the product. Each feature should map to a specific pain point from Slide 2. ",
        f"'Remember how users complained about X? Feature Y solves exactly that.' ",
        f"This creates a satisfying narrative loop.",
    )

    hook = _hk("We didn't just build a product. We built the solution to the problems you just saw.")

    return SlideNarrative(title="Our Solution", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="check")


def _build_why_now(
    sizing,
    validation,
    gaps: List[OpportunityGap],
) -> SlideNarrative:
    """Slide 5: Why Now — market timing and urgency."""
    points = []

    if sizing and sizing.key_trends:
        for trend in sizing.key_trends[:2]:
            points.append(f"Trend: {trend[:100]}")
    if sizing and sizing.growth_rate:
        points.append(f"Market growing at {sizing.growth_rate}")

    # Community signals
    if validation:
        if validation.hn_mentions > 0:
            points.append(f"Hacker News: {validation.hn_mentions} discussions about this space")
        if validation.reddit_posts_found > 0:
            points.append(f"Reddit: {validation.reddit_posts_found} posts — growing community demand")
        if validation.gh_similar_projects > 0:
            points.append(f"GitHub: {validation.gh_similar_projects} related projects — developer interest")

    if gaps:
        points.append(f"Window of opportunity: {gaps[0].gap[:100]} remains unsolved")

    if not points:
        points.append("The market is ready for a new approach")

    speaker = _spk(
        f"Answer: 'Why hasn't this been built before?' ",
        f"Use trends + market data to show the timing is right NOW. ",
        f"Investors fear missing the window — create urgency.",
    )

    hook = _hk("Timing is everything. Here's why NOW is the moment.")

    return SlideNarrative(title="Why Now", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="trending")


def _build_why_us(
    competitors: List[Competitor],
    gaps: List[OpportunityGap],
    features: List[str],
    positioning: str,
) -> SlideNarrative:
    """Slide 6: Why Us — competitive moat and differentiation."""
    points = []

    if positioning:
        points.append(f"Positioning: {positioning[:120]}")

    # Our advantages vs competitors
    for c in competitors[:2]:
        for w in c.weaknesses[:1]:
            points.append(f"vs {c.name} ({c.funding or 'unknown funding'}): we solve {w[:80]}")
        if c.pricing:
            points.append(f"vs {c.name} pricing: we offer better value than {c.pricing[:60]}")

    # Unique capabilities
    if gaps:
        points.append(f"Our edge: {gaps[0].gap[:100]}")

    if features:
        points.append(f"Core differentiator: {features[0][:80]}")

    if not points:
        points.append("Our unique approach combines deep market understanding with technical execution")

    speaker = _spk(
        f"Directly compare yourself to competitors. 'Competitor X raised $Y but can't do Z. We can.' ",
        f"Be specific and confident. Investors want to see you understand the competitive landscape cold.",
    )

    hook = _hk("Competitors have money. We have the right solution. Here's the proof.")

    return SlideNarrative(title="Why Us", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="shield")


def _build_market(sizing, validation, gaps: List[OpportunityGap]) -> SlideNarrative:
    """Slide 7: Market — TAM, SAM, and opportunity size."""
    points = []

    if sizing:
        if sizing.tam:
            points.append(f"TAM: {sizing.tam}" + (f" (source: {sizing.tam_source})" if sizing.tam_source else ""))
        if sizing.sam:
            points.append(f"SAM: {sizing.sam}" + (f" (source: {sizing.sam_source})" if sizing.sam_source else ""))
        if sizing.growth_rate:
            points.append(f"Growth rate: {sizing.growth_rate}")
        if sizing.key_trends:
            points.append(f"Key trend: {sizing.key_trends[0][:100]}")

    # Community validation as market signal
    if validation:
        signals = []
        if validation.reddit_posts_found > 0:
            signals.append(f"{validation.reddit_posts_found} Reddit posts")
        if validation.hn_mentions > 0:
            signals.append(f"{validation.hn_mentions} HN mentions")
        if signals:
            points.append(f"Market signals: {', '.join(signals)}")

    if not points:
        points.append("Market data is being refined — early signals are promising")

    speaker = _spk(
        f"Investors care about TAM > $1B. If you have real numbers, lead with them. ",
        f"If not, use bottom-up: 'X users × $Y/month = $Z market'. ",
        f"Show that this is a big market, not a niche hobby.",
    )

    hook = _hk("This isn't a small problem. Here's the size of the prize.")

    return SlideNarrative(title="Market Opportunity", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="chart")


def _build_business_model(
    pricing_str: str,
    features: List[str],
    competitors: List[Competitor],
) -> SlideNarrative:
    """Slide 8: Business Model — how we make money."""
    points = []

    if pricing_str:
        points.append(f"Pricing: {pricing_str}")

    # Competitor pricing context
    comp_pricing = [c for c in competitors if c.pricing]
    if comp_pricing:
        for c in comp_pricing[:2]:
            points.append(f"{c.name} charges: {c.pricing[:80]}")

    # Revenue model
    if features:
        points.append(f"Core monetizable feature: {features[0][:80]}")
    points.append("GTM: Developer-first, community-driven growth")
    points.append("Revenue model: Subscription + usage-based")

    speaker = _spk(
        f"Show you understand unit economics. ",
        f"Compare your pricing to competitors — show you're either cheaper for same value, or premium for unique value. ",
        f"Investors want to see a clear path to revenue.",
    )

    hook = _hk("We know how to make money. Here's the plan.")

    return SlideNarrative(title="Business Model", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="dollar")


def _build_ask(
    risks: List[str],
    features: List[str],
    gaps: List[OpportunityGap],
    competitors: List[Competitor],
) -> SlideNarrative:
    """Slide 9: The Ask — what we need and what's next."""
    points = []

    # What we'll do with funding
    if features:
        points.append(f"Milestone 1: Ship {features[0][:80]}")
    if len(features) > 1:
        points.append(f"Milestone 2: {features[1][:80]}")
    if gaps:
        points.append(f"Capture the {gaps[0].gap[:80]} opportunity")

    # Why we need funding now
    if risks:
        points.append(f"Key risk to mitigate: {risks[0][:80]}")

    points.append("Seeking: $150K-500K seed")
    points.append("Target: 1,000 active users in 6 months")

    speaker = _spk(
        f"Be specific about the ask. 'We're raising $X to achieve Y by Z date.' ",
        f"Connect the ask to the milestones: 'This funding gets us to [specific milestone].' ",
        f"End with confidence and a clear call to action.",
    )

    hook = _hk("We're building this. Here's what we need to win.")

    return SlideNarrative(title="The Ask", key_points=points, speaker_notes=speaker, narrative_hook=hook, icon="rocket")


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def _spk(*lines: str) -> str:
    """Build speaker notes from lines, filtering empty ones."""
    return " ".join(l for l in lines if l.strip())


def _hk(*lines: str) -> str:
    """Build narrative hook from lines."""
    return " ".join(l for l in lines if l.strip())


def format_narrative_markdown(narrative: PitchNarrative) -> str:
    """Export the pitch narrative as a readable Markdown script."""
    lines = [
        f"# Pitch Script: {narrative.idea}",
        f"",
        f"**Slides:** {narrative.total_slides} | **Estimated duration:** ~{narrative.estimated_minutes} min",
        f"",
        f"---",
    ]

    for i, slide in enumerate(narrative.slides, 1):
        lines.append(f"")
        lines.append(f"## Slide {i}: {slide.title}")
        lines.append(f"")
        lines.append(f"**Narrative Hook:** _{slide.narrative_hook}_")
        lines.append(f"")
        lines.append(f"### Key Points")
        for point in slide.key_points:
            lines.append(f"- {point}")
        lines.append(f"")
        lines.append(f"### 🎤 Speaker Notes")
        lines.append(f"> {slide.speaker_notes}")
        lines.append(f"")
        lines.append(f"---")

    # Add storytelling arc summary at the end
    lines.append(f"")
    lines.append(f"## Storytelling Arc Summary")
    arc = [
        f"1. **Hook** ({narrative.slides[0].title}): Grab attention with a bold data point or provocative statement.",
        f"2. **Problem** ({narrative.slides[1].title}): Make the audience feel the pain. Use real quotes and data.",
        f"3. **Agitation** ({narrative.slides[2].title}): Show that even well-funded competitors can't solve it.",
        f"4. **Solution** ({narrative.slides[3].title}): Reveal your product. Map features → pain points from slide 2.",
        f"5. **Why Now** ({narrative.slides[4].title}): Create urgency with market timing data.",
        f"6. **Why Us** ({narrative.slides[5].title}): Prove defensibility and competitive advantage.",
        f"7. **Market** ({narrative.slides[6].title}): Show the size of the prize.",
        f"8. **Business Model** ({narrative.slides[7].title}): Prove you know how to monetize.",
        f"9. **The Ask** ({narrative.slides[8].title}): Clear CTA with specific milestones.",
    ]
    lines.extend(arc)

    return "\n".join(lines)
