"""Generators — turns ResearchReport into pitch deck, landing page, and pricing."""

import logging
from pathlib import Path
from typing import Optional

from ..research.models import ResearchReport
from ..utils.paths import GENERATED_DIR, make_output_dir

logger = logging.getLogger(__name__)


# ── Pitch Deck Generator ───────────────────────────────

async def generate_pitch(report: ResearchReport, output_dir: Optional[Path] = None) -> str:
    """Generate HTML pitch deck with Gemini-powered slide images."""
    try:
        from .pitch import build_pitch_html
        from .narrative import generate_narrative

        narrative = generate_narrative(report)

        # Generate slide images if output_dir provided and Gemini key available
        image_urls = None
        if output_dir and report.idea:
            try:
                from .images import generate_slide_images
                slides_data = [
                    {"title": s.title, "key_points": s.key_points, "narrative_hook": s.narrative_hook}
                    for s in narrative.slides
                ]
                image_urls = await generate_slide_images(slides_data, output_dir, report.idea)
                if any(image_urls):
                    logger.info(f"Generated {sum(1 for u in image_urls if u)}/{len(image_urls)} slide images")
            except Exception as img_e:
                logger.warning(f"Slide image generation skipped: {img_e}")

        # Pass pre-computed narrative to avoid double generation
        html = build_pitch_html(report, image_urls=image_urls, narrative=narrative)
        return html
    except Exception as e:
        logger.warning(f"Pitch builder failed: {e}")
        return _fallback_pitch_html(report)


# ── Landing Page Generator ─────────────────────────────

async def generate_landing(report: ResearchReport, output_dir: Optional[Path] = None) -> str:
    """Generate a landing page with Gemini-powered hero image."""
    try:
        from .landing import build_landing_html

        # Generate hero image if output_dir provided
        hero_image_url = None
        if output_dir and report.idea:
            try:
                from .images import generate_hero_image
                tagline = report.recommended_positioning or report.idea[:60]
                hero_image_url = await generate_hero_image(report.idea, tagline, output_dir)
                if hero_image_url:
                    logger.info(f"Hero image generated: {hero_image_url}")
            except Exception as img_e:
                logger.warning(f"Hero image generation skipped: {img_e}")

        return build_landing_html(report, hero_image_url=hero_image_url)
    except Exception as e:
        logger.warning(f"Landing builder failed: {e}")
        return _fallback_landing_html(report)


# ── Pricing Page Generator ─────────────────────────

async def generate_pricing(report: ResearchReport) -> str:
    """Generate a pricing page. Uses deterministic builder (fast)."""
    try:
        from .pricing import build_pricing_html
        return build_pricing_html(report)
    except Exception as e:
        logger.warning(f"Pricing builder failed: {e}")
        return _fallback_pricing_html(report)


# ── Full Generation ────────────────────────────────────

async def generate_all(report: ResearchReport, output_dir: Optional[str] = None) -> dict:
    """Generate pitch deck, landing page, and pricing from research report.
    Generates AI images for pitch slides and landing hero when GEMINI_API_KEY is set.
    
    TASK-063 — Assets are saved in outputs/assets/ subdirectory.
    """
    out = Path(output_dir) if output_dir else make_output_dir(report.idea, GENERATED_DIR)
    assets_dir = out / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    for name, gen_fn in [
        ("pitch_deck", lambda r: generate_pitch(r, output_dir=out)),
        ("landing", lambda r: generate_landing(r, output_dir=out)),
        ("pricing", generate_pricing),
    ]:
        try:
            logger.info(f"Generating {name}...")
            html = await gen_fn(report)
            path = assets_dir / f"{name}.html"
            path.write_text(html)
            results[name] = str(path)
            logger.info(f"  → {path}")
        except Exception as e:
            logger.error(f"Failed to generate {name}: {e}")
            results[name] = f"Error: {e}"

    return results


def _fallback_pricing_html(report: ResearchReport) -> str:
    """Minimal fallback if the pricing builder fails."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Pricing — {report.idea[:40]}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>body {{ font-family: 'DM Sans', sans-serif; background: #0f172a; color: #e2e8f0; }}</style>
</head>
<body class="p-8">
<div class="max-w-4xl mx-auto">
<h1 class="text-3xl font-bold text-white mb-4">Pricing</h1>
<p class="text-slate-400 mb-8">{report.recommended_pricing_range or 'Contact us for pricing'}</p>
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
  <div class="bg-slate-800 rounded-xl p-6"><h2 class="text-xl font-bold text-white mb-2">Free</h2><p class="text-3xl font-bold text-teal-400 mb-4">$0</p><p class="text-slate-400 text-sm">Get started</p></div>
  <div class="bg-slate-800 rounded-xl p-6 border border-teal-500"><h2 class="text-xl font-bold text-white mb-2">Starter</h2><p class="text-3xl font-bold text-teal-400 mb-4">$29</p><p class="text-slate-400 text-sm">For indie developers</p></div>
  <div class="bg-slate-800 rounded-xl p-6"><h2 class="text-xl font-bold text-white mb-2">Pro</h2><p class="text-3xl font-bold text-teal-400 mb-4">$99</p><p class="text-slate-400 text-sm">For teams</p></div>
</div>
</div>
</body>
</html>"""


# ── Fallback Helpers ────────────────────────────────────

def _fallback_pitch_html(report: ResearchReport) -> str:
    """Minimal fallback if the pitch builder fails."""
    idea = report.idea[:50]
    tagline = report.recommended_positioning or "A new approach"
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pitch Deck — {idea}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>body {{ font-family: 'DM Sans', sans-serif; background: #0f172a; color: #e2e8f0; display: flex; align-items: center; justify-content: center; min-height: 100vh; }}</style>
</head>
<body>
<div class="text-center max-w-2xl p-8">
  <h1 class="text-5xl font-bold text-white mb-4">{idea}</h1>
  <p class="text-xl text-slate-400 mb-8">{tagline}</p>
  <p class="text-slate-500">Full pitch deck generation failed. Please retry.</p>
</div>
</body>
</html>"""


def _fallback_landing_html(report: ResearchReport) -> str:
    """Minimal fallback if the landing builder fails."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report.idea[:50]}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>body {{ font-family: 'DM Sans', sans-serif'; background: #0f172a; color: #e2e8f0; }}</style>
</head>
<body class="min-h-screen flex items-center justify-center p-8">
  <div class="text-center max-w-2xl">
    <h1 class="text-5xl font-bold text-white mb-4">{report.idea[:60]}</h1>
    <p class="text-xl text-slate-400 mb-8">{report.recommended_positioning or 'Coming soon'}</p>
    <div class="flex justify-center gap-4">
      <a href="#" class="px-6 py-3 bg-teal-500 rounded-lg text-white font-medium">Get Started</a>
    </div>
  </div>
</body>
</html>"""
