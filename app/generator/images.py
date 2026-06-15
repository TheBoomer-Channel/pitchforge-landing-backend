"""Image generation service — uses Gemini 2.0 Flash to generate images.

Generates:
- Pitch deck slide illustrations
- Landing page hero / feature images
- Caches generated images to disk (one-time generation per prompt)
"""

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

# Lazy import to avoid crash if package missing
_genai = None


def _ensure_genai():
    global _genai
    if _genai is not None:
        return _genai
    try:
        import google.generativeai as genai
        _genai = genai
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            logger.info("Gemini configured for image generation")
        else:
            logger.warning("GEMINI_API_KEY not set — image generation disabled")
        return _genai
    except ImportError:
        logger.warning("google-generativeai not installed — image generation disabled")
        return None
    except Exception as e:
        logger.warning(f"Gemini init failed: {e}")
        return None


def _image_cache_dir(output_dir: Path) -> Path:
    """Get/create the image cache subdirectory."""
    cache_dir = output_dir / ".images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_key(prompt: str) -> str:
    """Deterministic cache key for a prompt."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:24]


def _cached_image_path(output_dir: Path, prompt: str) -> Path:
    """Path where the generated image would be cached."""
    return _image_cache_dir(output_dir) / f"{_cache_key(prompt)}.png"


async def generate_image(
    prompt: str,
    output_dir: Path,
    aspect_ratio: str = "16:9",
    regenerate: bool = False,
) -> Optional[str]:
    """Generate an image using Gemini and cache it to disk.

    Args:
        prompt: Image description prompt.
        output_dir: Output directory for the generated artifact (cache stored in .images/ subdir).
        aspect_ratio: Image aspect ratio ("16:9", "1:1", "4:3", "3:4", "9:16").
        regenerate: Force regeneration even if cached.

    Returns:
        Relative URL path to the image file (for HTML src), or None if generation failed.
    """
    genai = _ensure_genai()
    if genai is None or not settings.GEMINI_API_KEY:
        return None

    cache_path = _cached_image_path(output_dir, prompt)
    if cache_path.exists() and not regenerate:
        return _relative_url(cache_path, output_dir)

    # Aspect ratio → size hint for Gemini
    size_hints = {
        "16:9": "a wide landscape image, 16:9 aspect ratio",
        "1:1": "a square image, 1:1 aspect ratio",
        "4:3": "a standard image, 4:3 aspect ratio",
        "3:4": "a portrait image, 3:4 aspect ratio",
        "9:16": "a tall portrait image, 9:16 aspect ratio",
    }
    size_text = size_hints.get(aspect_ratio, "a wide landscape image, 16:9 aspect ratio")

    full_prompt = (
        f"Generate a professional, high-quality {size_text} for a startup pitch deck. "
        f"It should be a clean, modern visual — not cheesy stock photos. "
        f"Use a dark, elegant color palette (deep navy, teal accents) suitable for a tech presentation. "
        f"The image should convey: {prompt}"
    )

    try:
        logger.info(f"Generating image via Gemini: {prompt[:60]}...")

        # Run Gemini in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: genai.GenerativeModel("gemini-2.0-flash-exp").generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    response_modalities=["Image", "Text"],
                    temperature=0.4,
                ),
            )
        )

        # Extract image from response parts
        image_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data is not None:
                if part.inline_data.mime_type and "image" in part.inline_data.mime_type:
                    image_data = part.inline_data.data
                    break

        if image_data:
            cache_path.write_bytes(image_data)
            logger.info(f"Image saved: {cache_path} ({len(image_data)} bytes)")
            return _relative_url(cache_path, output_dir)
        else:
            logger.warning(f"No image in Gemini response for: {prompt[:60]}")
            return None

    except Exception as e:
        logger.error(f"Image generation failed for '{prompt[:40]}': {e}")
        return None


def _relative_url(image_path: Path, output_dir: Path) -> str:
    """Convert absolute path to relative URL for HTML."""
    try:
        rel = image_path.relative_to(output_dir)
        return str(rel)
    except ValueError:
        return str(image_path.name)


# ── Batch generation helpers ───────────────────────────

async def generate_slide_images(
    slides_data: list[dict],
    output_dir: Path,
    idea: str,
) -> list[Optional[str]]:
    """Generate images for a list of slides in parallel.

    slides_data: list of dicts with 'title', 'key_points', 'narrative_hook'
    Returns: list of relative image URLs (or None for failed gens)
    """
    tasks = []
    for i, slide in enumerate(slides_data):
        prompt = f"Slide {i+1}: {slide['title']}. Context: {' '.join(slide.get('key_points', [])[:3])}. Narrative: {slide.get('narrative_hook', '')[:100]}"
        prompt = prompt[:200]  # Keep it concise
        tasks.append(generate_image(prompt, output_dir, aspect_ratio="16:9"))

    # Run up to 3 in parallel to avoid rate limits
    results = []
    for i in range(0, len(tasks), 3):
        batch = tasks[i:i+3]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)
        for r in batch_results:
            if isinstance(r, Exception):
                logger.warning(f"Slide image gen failed: {r}")
                results.append(None)
            else:
                results.append(r)
        await asyncio.sleep(0.5)  # Small delay between batches

    return results


async def generate_hero_image(
    idea: str,
    tagline: str,
    output_dir: Path,
    style: str = "professional product showcase",
) -> Optional[str]:
    """Generate a hero image for the landing page."""
    prompt = f"Hero image for {idea}: {tagline}. Style: {style}. Modern tech startup landing page."
    return await generate_image(prompt, output_dir, aspect_ratio="16:9")
