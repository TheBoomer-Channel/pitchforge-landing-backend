"""Report synthesis — takes raw source data and produces structured ResearchReport.

Uses DeepSeek LLM to analyze all source results and generate:
competitors, market validation, opportunity gaps, recommendations.

Falls back to deterministic extraction if LLM is unavailable.
"""

import json
import logging
import os
import re
from typing import Optional

from app.services.llm import llm

from .models import (
    BaseSourceResult,
    Competitor,
    MarketSizing,
    MarketValidation,
    OpportunityGap,
    ResearchReport,
)
from .competitor_analyzer import CompetitorAnalyzer

# Common English words and tech terms that should NOT be treated as competitor names
_COMPETITOR_STOP_WORDS = frozenset({
    'the', 'for', 'and', 'with', 'from', 'your', 'this', 'that',
    'what', 'when', 'where', 'which', 'there', 'their', 'they',
    'about', 'have', 'been', 'would', 'could', 'should', 'will',
    'into', 'over', 'after', 'before', 'between', 'under', 'above',
    'more', 'some', 'than', 'then', 'also', 'just', 'like', 'make',
    'does', 'most', 'only', 'other', 'such', 'very',
    'ask', 'how', 'why', 'who', 'can', 'now', 'new', 'one', 'two',
    'way', 'get', 'use', 'see', 'need', 'want', 'know', 'think',
    'show', 'tell', 'help', 'find', 'work', 'first', 'still',
    'here', 'using', 'used', 'built', 'made', 'wrote', 'tried',
    'update', 'review', 'guide', 'list', 'tips', 'best', 'top',
    # Tech terms that are not competitor names
    'api', 'aws', 'react', 'next', 'node', 'docker', 'github', 'gitlab',
    'python', 'javascript', 'typescript', 'golang', 'rust', 'ruby',
    'sdk', 'cli', 'css', 'html', 'json', 'xml', 'http', 'https',
    'ios', 'android', 'web', 'mobile', 'cloud', 'server', 'database',
    'ai', 'ml', 'llm', 'gpt', 'openai', 'chatgpt', 'copilot',
    'vscode', 'intellij', 'vim', 'emacs', 'sublime', 'notion',
    'slack', 'discord', 'telegram', 'whatsapp', 'zoom', 'teams',
    # Brand names that show up as noise from HN
    'uber', 'google', 'apple', 'meta', 'amazon', 'microsoft', 'netflix',
    'tesla', 'spotify', 'stripe', 'airbnb', 'twitter', 'facebook',
    'instagram', 'tiktok', 'youtube', 'linkedin', 'reddit',
})

logger = logging.getLogger(__name__)


class ReportSynthesizer:
    """Synthesizes raw research data into a structured ResearchReport."""

    def __init__(self):
        self.use_llm = os.getenv("RESEARCH_USE_LLM", "true").lower() == "true"

    async def synthesize(
        self,
        idea: str,
        query: str,
        target_market: str,
        raw_results: dict[str, BaseSourceResult],
    ) -> ResearchReport:
        """Synthesize all source results into a structured report."""
        
        # Try LLM synthesis first
        if self.use_llm:
            try:
                return await self._synthesize_with_llm(idea, query, target_market, raw_results)
            except Exception as e:
                logger.warning(f"LLM synthesis failed, falling back to deterministic: {e}")

        # Fallback: deterministic extraction
        return self._synthesize_deterministic(idea, raw_results)

    async def _synthesize_with_llm(
        self,
        idea: str,
        query: str,
        target_market: str,
        raw_results: dict[str, BaseSourceResult],
    ) -> ResearchReport:
        """Use DeepSeek LLM to synthesize the report."""
        
        # Build a compact summary of all source results for the LLM
        source_summaries = []
        for name, result in raw_results.items():
            if not result.success:
                source_summaries.append(f"## {name} — FAILED: {result.error or 'unknown error'}")
                continue
            summary = self._summarize_source(result)
            source_summaries.append(f"## {name} — {len(result.data)} results\n{summary}")

        sources_text = "\n\n".join(source_summaries)

        prompt = f"""You are a startup market research analyst. Analyze the following raw research data for the startup idea:

IDEA: {idea}
TARGET MARKET: {target_market or "Not specified"}
QUERY: {query}

=== RAW RESEARCH DATA ===

{sources_text}

=== TASK ===

Produce a structured JSON report with EXACTLY this shape (no markdown, no explanation, JUST the JSON object):

```json
{{
  "summary": "2-3 sentence executive summary of findings",
  "competitors": [
    {{
      "name": "Company name",
      "description": "What they do",
      "website": "URL if found",
      "funding": "Funding info if available (e.g. 'Series B $20M' or 'Bootstrapped')",
      "funding_source": "Crunchbase/Crunchbase",
      "business_model": "How they make money (SaaS, commission, marketplace, etc.)",
      "target_market": "Who they serve",
      "pain_points": ["User complaints about this competitor"],
      "strengths": ["What they do well"],
      "weaknesses": ["Where they fall short"],
      "source": "tavily/reddit/etc",
      "source_urls": ["relevant URLs"],
      "confidence": 0.8
    }}
  ],
  "market_validation": {{
    "reddit_posts_found": 0,
    "reddit_sentiment": "positive/negative/mixed/null",
    "reddit_top_posts": [],
    "hn_mentions": 0,
    "hn_top_posts": [],
    "gh_similar_projects": 0,
    "gh_projects": [],
    "common_complaints": ["what people complain about"],
    "common_desires": ["what people say they want/need"],
    "overall_sentiment": "positive/negative/mixed"
  }},
  "market_sizing": {{
    "tam": "Total Addressable Market estimate with source",
    "tam_source": "Source of TAM data",
    "tam_confidence": 0.0,
    "sam": "Serviceable Addressable Market estimate with source",
    "sam_source": "Source of SAM data",
    "sam_confidence": 0.0,
    "growth_rate": "Market growth rate if available",
    "growth_source": "Source of growth data",
    "key_trends": ["relevant market trends"]
  }},
  "opportunity_gaps": [
    {{
      "gap": "Description of gap in the market",
      "evidence": ["Evidence supporting this gap from research"],
      "severity": "high/medium/low",
      "source": "reddit/tavily/etc"
    }}
  ],
  "recommended_mvp_features": ["Feature 1", "Feature 2"],
  "recommended_pricing_range": "e.g. '$29-99/month or 5-10% commission'",
  "recommended_positioning": "1-sentence positioning statement",
  "risk_factors": ["Risk 1", "Risk 2"]
}}
```

Rules:
- Only include competitors that actually exist and are related to the idea
- If no data for a field, use null or empty array — do NOT invent data
- pain_points should come from actual user complaints found in the data
- confidence reflects how reliable the data seems (0.3=guess, 0.8=verified)
- Keep descriptions under 200 chars each
- The summary should highlight the single most important finding
- BE HONEST: if there's not enough data, say so in the summary"""
        
        result = await self._call_llm(prompt)
        
        # Parse JSON from response using llm's extractor
        report_dict = llm._extract_json(result)
        if not report_dict:
            raise ValueError("Failed to parse LLM output as JSON")

        return self._dict_to_report(report_dict, idea)

    def _summarize_source(self, result: BaseSourceResult) -> str:
        """Create a compact text summary of source data for LLM context."""
        parts = []
        
        # ── Summarize data items (title + description) ──
        if result.data:
            data_parts = []
            for item in result.data[:8]:
                title = item.get("title", "") or item.get("name", "") or ""
                desc = item.get("description", "") or item.get("extract", "") or item.get("content", "") or item.get("snippet", "") or ""
                url = item.get("url", "") or item.get("website", "") or ""
                if title:
                    entry = f"- {title[:150]}"
                    if desc:
                        entry += f": {desc[:200]}"
                    if url:
                        entry += f" [{url[:80]}]"
                    data_parts.append(entry)
            if data_parts:
                parts.append("data:\n" + "\n".join(data_parts))
        
        # ── Add metadata keys ──
        meta = result.raw_metadata or {}
        for key in ["sentiment", "signal_level", "total_points", "posts_found", "total_stars",
                     "total_results", "repos_found", "pages_found", "mentions"]:
            if key in meta and meta[key] is not None and meta[key] != "":
                val = meta[key]
                parts.append(f"{key}: {val}")

        # Add complaints/desires
        for key in ["common_complaints", "common_desires"]:
            items = meta.get(key, [])
            if items:
                parts.append(f"{key}: {'; '.join(items[:5])}")

        # Add top posts titles
        for top_key in ["top_posts", "top_repos"]:
            posts = meta.get(top_key, [])
            if posts:
                titles = []
                for p in posts[:3]:
                    t = p.get("title", "") or p.get("name", "") or ""
                    if t:
                        titles.append(t[:100])
                if titles:
                    parts.append(f"top {top_key}: " + " | ".join(titles))

        # Add positive/negative signals
        for sig_key in ["positive_signals", "negative_signals"]:
            sigs = meta.get(sig_key, [])
            if sigs:
                parts.append(f"{sig_key}: {'; '.join(str(s)[:100] for s in sigs[:3])}")
        
        text = ". ".join(parts) if not any("\n" in p for p in parts) else "\n".join(parts)
        # Truncate to avoid blowing up context
        if len(text) > 2500:
            text = text[:2500] + "..."
        return text

    def _synthesize_deterministic(
        self,
        idea: str,
        raw_results: dict[str, BaseSourceResult],
    ) -> ResearchReport:
        """Fallback: extract what we can without LLM.
        
        Extracts competitors from ALL successful sources:
        - tavily/duckduckgo/brave: web search results → competitors
        - hacker_news: titles mentioning products/companies → competitors + market signals
        - github: repos → similar projects/competitors + features
        - wikipedia: page summaries → competitor profiles + market data
        - reddit: complaints/desires → market validation
        """
        competitors = []
        complaints = []
        desires = []
        projects = []
        features = []
        risks = []
        gaps = []
        reddit_posts = 0
        reddit_sentiment = None
        hn_mentions = 0
        hn_top = []
        hn_signal = ""
        hn_positive = []
        hn_negative = []
        seen_comp_names = set()

        for name, result in raw_results.items():
            if not result.success:
                continue
            meta = result.raw_metadata or {}

            # ── Web search sources: direct competitor extraction ──
            if name in ("tavily", "duckduckgo", "brave") and result.data:
                for item in result.data[:10]:
                    title = item.get("title", "")
                    content = item.get("content", "") or item.get("snippet", "") or item.get("description", "")
                    url = item.get("url", "")
                    if title and content and title.lower() not in seen_comp_names:
                        seen_comp_names.add(title.lower())
                        competitors.append(Competitor(
                            name=title[:80],
                            description=content[:300],
                            website=url,
                            source=name,
                            source_urls=[url] if url else [],
                            confidence=0.4,
                        ))

            # ── Hacker News: extract companies/products from titles ──
            if name == "hacker_news":
                hn_meta = meta
                hn_mentions = hn_meta.get("mentions", 0)
                hn_signal = hn_meta.get("signal_level", "")
                hn_top = hn_meta.get("top_posts", [])[:5]
                hn_positive = hn_meta.get("positive_signals", [])
                hn_negative = hn_meta.get("negative_signals", [])
                
                # Extract competitor-like entries from HN titles
                # Look for: "Show HN: ProductName", "Ask HN: alternatives to X", product launches
                for post in hn_top:
                    title = post.get("title", "")
                    points = post.get("points", 0)
                    url = post.get("url", "") or post.get("hn_url", "")
                    
                    # Extract product name from "Show HN: ProductName — description"
                    show_hn_match = re.match(r'Show\s+HN:\s*(.+?)(?:\s*[—\-–]\s*|$)', title, re.IGNORECASE)
                    if show_hn_match:
                        product_name = show_hn_match.group(1).strip()[:80]
                        if product_name.lower() not in seen_comp_names and points >= 2:
                            seen_comp_names.add(product_name.lower())
                            competitors.append(Competitor(
                                name=product_name,
                                description=title[:300],
                                website=url,
                                source="hacker_news",
                                source_urls=[url] if url else [],
                                confidence=0.3 + min(0.3, points / 200),
                            ))
                    
                    # Extract company/product names from regular titles (capitalized words, high points)
                    elif points >= 20:
                        # Look for capitalized multi-word phrases (more likely company names)
                        for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b', title):
                            candidate = match.group(1).strip()
                            words_lower = candidate.lower().split()
                            # Skip if all words are in stop list
                            if all(w in _COMPETITOR_STOP_WORDS for w in words_lower):
                                continue
                            if candidate.lower() not in seen_comp_names:
                                seen_comp_names.add(candidate.lower())
                                competitors.append(Competitor(
                                    name=candidate[:80],
                                    description=title[:300],
                                    website=url,
                                    source="hacker_news",
                                    source_urls=[url] if url else [],
                                    confidence=0.25,
                                ))
                                break  # One competitor per post

                # Use HN signal for market sizing insights
                if hn_signal in ("strong_interest", "moderate_interest"):
                    features.append(f"Strong tech community interest ({hn_mentions} HN discussions)")

                # Extract complaints from Ask HN posts
                for neg_title in hn_negative[:3]:
                    complaints.append(neg_title[:200])

                # Extract desires from Show HN posts
                for pos_title in hn_positive[:3]:
                    desires.append(pos_title[:200])

            # ── GitHub: repos as similar projects/competitors ──
            if name == "github" and result.data:
                for r in result.data[:8]:
                    repo_name = r.get("name", "")
                    description = r.get("description", "")
                    stars = r.get("stars", 0)
                    url = r.get("url", "")
                    
                    projects.append({
                        "name": repo_name,
                        "stars": stars,
                        "description": description,
                        "url": url,
                    })
                    
                    # Repos with high stars are potential competitors
                    if stars >= 10 and repo_name.lower() not in seen_comp_names:
                        seen_comp_names.add(repo_name.lower())
                        competitors.append(Competitor(
                            name=repo_name[:80],
                            description=description[:300] or f"GitHub project with {stars} stars",
                            website=url,
                            source="github",
                            source_urls=[url] if url else [],
                            strengths=[f"{stars} stars on GitHub"] if stars > 0 else [],
                            confidence=0.3 + min(0.4, stars / 1000),
                        ))
                    
                    # Extract feature ideas from repo descriptions (skip meta/boilerplate descriptions)
                    if description and len(description) > 30:
                        lower_desc = description.lower()
                        # Skip boilerplate: "a simple...", "a demo...", "a sample...", "todo", "hello world"
                        boilerplate_starts = ('a simple', 'a demo', 'a sample', 'a basic', 'todo app', 'hello world', 'example of', 'test repo')
                        if not lower_desc.startswith(boilerplate_starts) and 'todo' not in lower_desc[:20]:
                            features.append(description[:200])

            # ── Wikipedia: structured competitor data ──
            if name == "wikipedia" and result.data:
                for page in result.data[:8]:
                    title = page.get("title", "")
                    extract = page.get("extract", "")
                    url = page.get("url", "")
                    
                    # Skip list pages, use actual company/industry pages
                    is_list = title.startswith("[List]")
                    clean_title = title.replace("[List] ", "")
                    
                    if not is_list and clean_title.lower() not in seen_comp_names and len(extract) > 50:
                        seen_comp_names.add(clean_title.lower())
                        
                        # Try to extract funding info from the summary
                        funding_match = re.search(r'(?:raised|funding|valuation|Series\s+[A-D]|\$[\d.]+\s*(?:million|billion|M|B))', extract, re.IGNORECASE)
                        funding = funding_match.group(0) if funding_match else None
                        
                        competitors.append(Competitor(
                            name=clean_title[:80],
                            description=extract[:300],
                            website=url,
                            funding=funding,
                            source="wikipedia",
                            source_urls=[url] if url else [],
                            confidence=0.6 if funding else 0.5,
                        ))
                    
                    # Extract market trends from industry/overview pages
                    is_industry = any(kw in clean_title.lower() for kw in ("industry", "market", "economy", "sector", "overview", "list"))
                    if is_industry or is_list:
                        gaps.append(OpportunityGap(
                            gap=f"Industry overview from Wikipedia: {clean_title}",
                            evidence=[extract[:300]],
                            severity="medium" if is_industry else "low",
                            source="wikipedia",
                        ))

            # ── Reddit: sentiment and community signals ──
            if name == "reddit" and meta:
                rmeta = meta
                complaints.extend(rmeta.get("common_complaints", [])[:5])
                desires.extend(rmeta.get("common_desires", [])[:5])
                reddit_posts = rmeta.get("posts_found", 0)
                reddit_sentiment = rmeta.get("sentiment")
                
                # Derive features from desires
                for desire in desires[:5]:
                    if desire not in features:
                        features.append(desire[:200])
                
                # Derive risks from complaints
                for complaint in complaints[:5]:
                    if complaint not in risks:
                        risks.append(complaint[:200])

        # ── Post-processing: deduplicate and enrich ──
        
        # Deduplicate features (keep first 8)
        seen_features = set()
        unique_features = []
        for f in features:
            key = f.lower()[:50]
            if key not in seen_features and len(f) > 10:
                seen_features.add(key)
                unique_features.append(f[:200])
        features = unique_features[:8]

        # Deduplicate competitors by name
        unique_comps = []
        seen_names = set()
        for c in competitors:
            key = c.name.lower()[:40]
            if key not in seen_names:
                seen_names.add(key)
                unique_comps.append(c)
        competitors = unique_comps

        # Build summary with real counts
        parts = []
        if competitors:
            parts.append(f"{len(competitors)} potential competitors identified")
        if complaints:
            parts.append(f"{len(complaints)} user complaints found")
        if hn_mentions:
            parts.append(f"{hn_mentions} Hacker News discussions")
        if projects:
            parts.append(f"{len(projects)} GitHub projects")
        if reddit_posts:
            parts.append(f"{reddit_posts} Reddit posts")
        
        summary = ". ".join(parts) + "." if parts else f"Research complete for '{idea[:60]}'. Limited data found — try more specific search terms or enable LLM synthesis for richer results."

        # Derive risk factors from data
        if not risks:
            if len(competitors) > 5:
                risks.append(f"Highly competitive market with {len(competitors)} identified players")
            if hn_signal == "minimal" or hn_signal == "no_mentions":
                risks.append("Low tech community engagement — may indicate limited developer demand")
            if not features:
                risks.append("No clear MVP features identified — need deeper research")

        # Derive gaps from competitor analysis
        if not gaps and competitors:
            gaps.append(OpportunityGap(
                gap=f"Competitive analysis of {len(competitors)} players needed to identify differentiation opportunities",
                evidence=[f"Found {len(competitors)} competitors across multiple sources"],
                severity="high",
                source="synthesis",
            ))

        # Default features if none found
        if not features:
            features = [
                f"Core {idea[:30]} functionality",
                "User authentication and profiles",
                "Payment/subscription integration",
                "Mobile-responsive interface",
            ]

        report = ResearchReport(
            idea=idea,
            summary=summary,
            competitors=competitors,
            market_validation=MarketValidation(
                reddit_posts_found=reddit_posts,
                reddit_sentiment=reddit_sentiment,
                hn_mentions=hn_mentions,
                hn_top_posts=hn_top,
                common_complaints=complaints[:8],
                common_desires=desires[:8],
                gh_similar_projects=len(projects),
                gh_projects=projects[:5],
                overall_sentiment=reddit_sentiment or hn_signal,
            ),
            opportunity_gaps=gaps[:6],
            recommended_mvp_features=features,
            recommended_pricing_range=self._derive_pricing(competitors),
            recommended_positioning=self._derive_positioning(idea, competitors),
            risk_factors=risks[:6],
        )
        # TASK-064 — Run competitive analysis
        if competitors:
            report.competitive_insights = CompetitorAnalyzer.analyze(report)
        return report

    @staticmethod
    def _derive_pricing(competitors: list[Competitor]) -> str:
        """Derive pricing recommendation from competitor data."""
        if not competitors:
            return "Freemium with $9-29/month paid tiers"
        comp_count = len(competitors)
        if comp_count <= 2:
            return "Premium positioning possible — $29-99/month"
        elif comp_count <= 5:
            return "Competitive market — $9-49/month with free tier"
        else:
            return "Highly competitive — freemium with $5-19/month, differentiate on UX"

    @staticmethod
    def _derive_positioning(idea: str, competitors: list[Competitor]) -> str:
        """Derive positioning statement from competitor analysis."""
        comp_count = len(competitors)
        if comp_count == 0:
            return f"{idea[:60]} — pioneer in an underserved market"
        elif comp_count <= 3:
            return f"{idea[:60]} — focused alternative to fragmented incumbents"
        else:
            return f"{idea[:60]} — differentiated by superior execution and user experience"

    # ── LLM Helpers ─────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        """Call DeepSeek Flash for synthesis — faster and more reliable for structured JSON.
        
        Uses Flash (deepseek-chat) instead of Pro (deepseek-reasoner) because:
        - Flash is cheaper, faster, and more reliable for structured JSON output
        - Pro can return empty content with reasoning in a separate field
        - Flash handles the large synthesis prompt well at 8192 tokens
        """
        return await llm.chat(prompt, temperature=0.3, max_tokens=8192, timeout=300)



    @staticmethod
    def _dict_to_report(d: dict, idea: str = "") -> ResearchReport:
        """Convert dict to ResearchReport with proper nesting."""
        competitors_raw = [
            Competitor(**c) if isinstance(c, dict) else c
            for c in d.get("competitors", [])
        ]
        report = ResearchReport(
            idea=d.get("idea", idea),
            summary=d.get("summary", ""),
            competitors=competitors_raw,
            market_validation=MarketValidation(**(d.get("market_validation", {}) or {})),
            market_sizing=MarketSizing(**(d.get("market_sizing", {}) or {})),
            opportunity_gaps=[
                OpportunityGap(**g) if isinstance(g, dict) else g
                for g in d.get("opportunity_gaps", [])
            ],
            recommended_mvp_features=d.get("recommended_mvp_features", []),
            recommended_pricing_range=d.get("recommended_pricing_range"),
            recommended_positioning=d.get("recommended_positioning"),
            risk_factors=d.get("risk_factors", []),
        )
        # TASK-064 — Run competitive analysis
        if competitors_raw:
            report.competitive_insights = CompetitorAnalyzer.analyze(report)
        return report
