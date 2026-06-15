"""Competitor Analyzer — extracts actionable insights from competitor data.

TASK-064: Analyzes N competitors and produces:
- Table stakes (features all competitors have)
- Differentiation gaps (features nobody has)
- Pain point summary by severity/source
- Pricing landscape comparison
- Must-have features (synthesized from table stakes + pain points)
"""

import logging
from collections import Counter
from .models import Competitor

logger = logging.getLogger(__name__)


class CompetitorAnalyzer:
    """Analyzes competitor data and produces structured, actionable insights."""

    @staticmethod
    def get_table_stakes(competitors: list[Competitor]) -> list[str]:
        """Features present in >70% of competitors → required for MVP.

        Derives from strengths and features_detected across all competitors.
        """
        if not competitors:
            return []

        all_features: list[str] = []
        for c in competitors:
            # Collect from strengths (top 3) and features_detected
            all_features.extend(c.strengths[:3])
            all_features.extend(c.features_detected)

        if not all_features:
            return []

        freq = Counter(all_features)
        threshold = max(1, int(len(competitors) * 0.7))
        table_stakes = [f for f, count in freq.most_common() if count >= threshold]

        logger.info(f"Table stakes found: {len(table_stakes)} (from {len(competitors)} competitors, threshold={threshold})")
        return table_stakes

    @staticmethod
    def get_differentiation_gaps(competitors: list[Competitor]) -> list[str]:
        """Features that NO competitor has well → our opportunity to differentiate.

        Derived from common weaknesses and missing features.
        """
        if not competitors:
            return []

        all_weaknesses: list[str] = []
        for c in competitors:
            all_weaknesses.extend(c.weaknesses[:3])

        if not all_weaknesses:
            return []

        # Weaknesses mentioned by >50% of competitors = differentiation opportunity
        freq = Counter(all_weaknesses)
        threshold = max(1, int(len(competitors) * 0.5))
        gaps = [w for w, count in freq.most_common() if count >= threshold]

        logger.info(f"Differentiation gaps: {len(gaps)}")
        return gaps

    @staticmethod
    def get_pain_point_summary(competitors: list[Competitor]) -> dict:
        """Aggregate pain points by severity and source.

        Returns:
            {
                "critical": [...],   # Mentioned in >3 sources
                "common": [...],     # Mentioned in 2-3 sources
                "minor": [...],      # Mentioned once
                "by_competitor": {"CompA": ["pain1"], ...}
            }
        """
        if not competitors:
            return {"critical": [], "common": [], "minor": [], "by_competitor": {}}

        # Collect all structured pain points with sources
        all_pains: list[dict] = []
        by_competitor: dict[str, list[str]] = {}

        for c in competitors:
            comp_pains: list[str] = []

            # Structured pain points (new field)
            for pp in c.pain_points_with_sources:
                all_pains.append(pp)
                comp_pains.append(pp.get("pain", ""))

            # Legacy pain_points (string list)
            for p in c.pain_points:
                if not any(existing.get("pain") == p for existing in all_pains):
                    all_pains.append({"pain": p, "source": c.source or "unknown", "severity": "medium"})
                    comp_pains.append(p)

            if comp_pains:
                by_competitor[c.name] = comp_pains

        # Group by frequency
        pain_texts = [p.get("pain", "") for p in all_pains]
        freq = Counter(pain_texts)

        critical = []
        common = []
        minor = []
        seen = set()

        for pain in all_pains:
            text = pain.get("pain", "")
            severity = pain.get("severity", "medium")
            count = freq.get(text, 1)

            if text in seen:
                continue
            seen.add(text)

            if severity == "high" or count >= 3:
                critical.append(text)
            elif count >= 2:
                common.append(text)
            else:
                minor.append(text)

        logger.info(f"Pain points: {len(critical)} critical, {len(common)} common, {len(minor)} minor")

        return {
            "critical": critical,
            "common": common,
            "minor": minor,
            "by_competitor": by_competitor,
            "total_unique": len(seen),
        }

    @staticmethod
    def get_pricing_landscape(competitors: list[Competitor]) -> dict:
        """Analyze competitor pricing to inform our pricing strategy.

        Returns:
            {
                "range": {"min": 0, "max": 299, "median": 49, "avg": 65},
                "most_common_tier": "Starter ($29/mo)",
                "free_tier_available": True,
                "competitors": [{"name": "X", "tiers": [...], "pricing_text": "..."}]
            }
        """
        if not competitors:
            return {"range": {}, "most_common_tier": "Unknown", "free_tier_available": True, "competitors": []}

        comp_pricing = []
        all_prices = []
        has_free = False

        for c in competitors:
            entry = {"name": c.name, "tiers": c.pricing_tiers, "pricing_text": c.pricing or ""}

            if c.pricing_tiers:
                for tier in c.pricing_tiers:
                    price = tier.get("price", 0)
                    if isinstance(price, (int, float)):
                        all_prices.append(price)
                        if price == 0:
                            has_free = True
            elif c.pricing:
                # Try to extract price from text
                entry["pricing_text"] = c.pricing
                # Simple heuristic: look for $XX numbers
                import re
                nums = re.findall(r'\$(\d+)', c.pricing)
                for n in nums:
                    all_prices.append(int(n))
                    if int(n) == 0:
                        has_free = True

            comp_pricing.append(entry)

        range_info = {}
        if all_prices:
            sorted_prices = sorted(all_prices)
            n = len(sorted_prices)
            range_info = {
                "min": sorted_prices[0],
                "max": sorted_prices[-1],
                "median": sorted_prices[n // 2],
                "avg": round(sum(sorted_prices) / n, 0),
            }

        most_common = "Unknown"
        if all_prices:
            price_freq = Counter(all_prices)
            most_common_price = price_freq.most_common(1)[0][0] if price_freq else 0
            most_common = f"${most_common_price}/mo" if most_common_price > 0 else "Free"

        logger.info(f"Pricing landscape: {len(comp_pricing)} competitors, range={range_info}")

        return {
            "range": range_info,
            "most_common_tier": most_common,
            "free_tier_available": has_free,
            "competitors": comp_pricing,
        }

    @staticmethod
    def get_must_have_features(competitors: list[Competitor]) -> dict:
        """Synthesize table stakes + pain points → prioritized feature list.

        Returns:
            {
                "table_stakes": ["Feature A", "Feature B"],    # P0 — must have
                "differentiators": ["Feature C"],               # P1 — competitive advantage
                "nice_to_have": ["Feature D"],                  # P2 — optional
            }
        """
        table_stakes = CompetitorAnalyzer.get_table_stakes(competitors)
        diff_gaps = CompetitorAnalyzer.get_differentiation_gaps(competitors)

        # Pain points suggest features
        pain_summary = CompetitorAnalyzer.get_pain_point_summary(competitors)
        pain_features = pain_summary.get("critical", [])[:5] + pain_summary.get("common", [])[:3]

        return {
            "table_stakes": table_stakes,
            "differentiators": diff_gaps,
            "nice_to_have": pain_features,
        }

    @staticmethod
    def analyze(report) -> dict:
        """Run full competitive analysis on a ResearchReport.

        Returns a dict ready for report.competitive_insights.
        """
        competitors = report.competitors
        if not competitors:
            return {
                "table_stakes": [],
                "differentiation_gaps": [],
                "pain_summary": {"critical": [], "common": [], "minor": [], "by_competitor": {}},
                "pricing_landscape": {"range": {}, "most_common_tier": "Unknown", "free_tier_available": True, "competitors": []},
                "must_have_features": {"table_stakes": [], "differentiators": [], "nice_to_have": []},
            }

        return {
            "table_stakes": CompetitorAnalyzer.get_table_stakes(competitors),
            "differentiation_gaps": CompetitorAnalyzer.get_differentiation_gaps(competitors),
            "pain_summary": CompetitorAnalyzer.get_pain_point_summary(competitors),
            "pricing_landscape": CompetitorAnalyzer.get_pricing_landscape(competitors),
            "must_have_features": CompetitorAnalyzer.get_must_have_features(competitors),
        }
