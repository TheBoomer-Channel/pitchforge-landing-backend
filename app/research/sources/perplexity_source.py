"""Perplexity research source — competitor search and Reddit pain analysis.

Adapted from Startup Engine's api/app/services/perplexity.py
Integrated as a BaseSource for the research engine — June 2026
"""

import json
import logging
import re
from typing import Optional

import httpx

from ..base_source import BaseSource
from ..models import BaseSourceResult
from ...config import settings

logger = logging.getLogger(__name__)


class PerplexitySource(BaseSource):
    """Research source using Perplexity API for competitor search and pain analysis."""

    name = "perplexity"
    display_name = "Perplexity AI"
    description = "Competitor search and Reddit pain point analysis via Perplexity API"

    BASE_URL = "https://api.perplexity.ai/chat/completions"
    MODEL = "sonar-pro"
    TEMPERATURE = 0.3
    TIMEOUT = 30.0

    async def search(self, idea: str, target_market: str = "", **kwargs) -> BaseSourceResult:
        """Run both competitor search and pain analysis via Perplexity."""
        if not settings.PERPLEXITY_API_KEY:
            return BaseSourceResult(
                source=self.name,
                success=False,
                error="PERPLEXITY_API_KEY not configured",
                data={},
            )

        results = {}
        errors = []
        raw_output = []

        # ── Competitor search ──
        try:
            competitors = await self._search_competitors(idea, target_market)
            results["competitors"] = competitors
            raw_output.append(f"=== COMPETITORS ===\n{json.dumps(competitors, indent=2)}")
        except Exception as e:
            errors.append(f"Competitor search failed: {e}")

        # ── Reddit pain analysis ──
        try:
            pain_points = await self._search_reddit_pain(idea)
            results["pain_points"] = pain_points
            raw_output.append(f"=== PAIN POINTS ===\n{json.dumps(pain_points, indent=2)}")
        except Exception as e:
            errors.append(f"Pain analysis failed: {e}")

        if not results:
            return BaseSourceResult(
                source=self.name,
                success=False,
                error="; ".join(errors),
                data=[],
            )

        # Flatten results dict into a list for BaseSourceResult.data (expects list[dict])
        flat_data = []
        if "competitors" in results:
            for comp in results["competitors"]:
                comp["_type"] = "competitor"
                flat_data.append(comp)
        if "pain_points" in results:
            for pp in results["pain_points"]:
                if isinstance(pp, str):
                    flat_data.append({"_type": "pain_point", "text": pp})
                elif isinstance(pp, dict):
                    pp["_type"] = "pain_point"
                    flat_data.append(pp)

        return BaseSourceResult(
            source=self.name,
            success=True,
            data=flat_data,
            raw_metadata={"raw_output": "\n\n".join(raw_output), "errors": errors},
            error="; ".join(errors) if errors else None,
        )

    async def _search_competitors(self, idea: str, target_market: str = "") -> list:
        """Search for competitors using Perplexity."""
        market_context = f" in the {target_market} space" if target_market else ""

        prompt = f"""Analyze the startup idea "{idea}"{market_context}.

Return a JSON object with:
- "competitors": array of 3-5 competitor objects, each with:
  - "name": company name
  - "description": what they do
  - "funding": estimated funding if known
  - "users": estimated user base if known
  - "pricing": pricing model
  - "weakness": key weakness or gap
- "market_trend": brief market trend description
- "tam": total addressable market estimate
- "recommendation": "GO" / "ITERATE" / "PIVOT" with brief reasoning

Return ONLY valid JSON, no markdown formatting."""

        response = await self._call_api(prompt)
        try:
            data = json.loads(response)
            return data.get("competitors", [])
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            return self._extract_json_array(response, "competitors")

    async def _search_reddit_pain(self, idea: str) -> list:
        """Search for pain points via Perplexity."""
        prompt = f"""Find 5-7 specific user pain points and frustrations people have with solutions
in the "{idea}" space. Focus on real complaints from Reddit, forums, and review sites.

Return a JSON array of strings, each describing a specific pain point.
Return ONLY valid JSON, no markdown formatting."""

        response = await self._call_api(prompt)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return self._extract_json_array(response, "pain_points")

    async def _call_api(self, prompt: str) -> str:
        """Make a Perplexity API call."""
        headers = {
            "Authorization": f"Bearer {settings.PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.TEMPERATURE,
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    @staticmethod
    def _extract_json_array(text: str, key: str) -> list:
        """Try to extract a JSON array from LLM output."""
        # Try to find array between [ and ]
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        # Try to parse full response as JSON
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            return data.get(key, [])
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"Could not parse Perplexity response for key={key}")
            return []
