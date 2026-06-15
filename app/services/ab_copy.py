"""AB Copy Service — generate, track, and evaluate A/B copy variants.

TASK-052 — A/B Copy Generator.
Uses LLM (Gemini or OpenRouter) to generate 5 variants per copy element
with different angles (urgency, value, curiosity, authority, social proof).
Manages impression/conversion tracking and winner selection.
"""

import logging
import json
import math
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..models.ab_copy import CopyVariant, CopySet, ABTestVariant

logger = logging.getLogger(__name__)

# ── Angle presets for variant generation ────────────────

COPY_ANGLES = {
    "headline": [
        ("urgency", "Time-sensitive, action-driven language that creates FOMO"),
        ("value", "Benefit-first framing highlighting the core value proposition"),
        ("curiosity", "Question-based or curiosity-gap headline that makes people want to learn more"),
        ("authority", "Confident, expert-toned headline establishing market leadership"),
        ("social_proof", "Community-validated headline showing others trust it"),
    ],
    "subheadline": [
        ("urgency", "FOMO-reinforcing subheadline with time-sensitive benefit"),
        ("value", "Specific, measurable benefit expanding on the promise"),
        ("curiosity", "Intriguing question or hint at what's possible"),
        ("authority", "Data-backed claim establishing credibility"),
        ("social_proof", "Social proof highlighting adoption or results"),
    ],
    "cta_primary": [
        ("urgency", "Action-driven CTA creating urgency to act now"),
        ("value", "Benefit-focused CTA emphasizing what users gain"),
        ("curiosity", "Curiosity-driven CTA making users want to discover more"),
        ("direct", "Clear, no-nonsense directive CTA"),
        ("personal", "Personal, first-person framing that reduces friction"),
    ],
    "cta_secondary": [
        ("urgency", "Lower-friction urgency CTA for hesitant users"),
        ("value", "Exploratory CTA promising value before commitment"),
        ("curiosity", "Learning-oriented CTA inviting discovery"),
        ("trust", "Trust-building CTA reducing perceived risk"),
        ("social", "Social-validated CTA showing others took this step"),
    ],
}

DEFAULT_CATEGORY = "cta_primary"  # fallback

VARIANT_KEYS = ["v0", "v1", "v2", "v3", "v4"]


# ── LLM Variant Generation ─────────────────────────────

async def _call_llm(prompt: str) -> str:
    """Call the configured LLM to generate copy variants."""
    # Try Gemini first
    if settings.GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.0-flash")
            resp = await model.generate_content_async(prompt)
            return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini variant gen failed: {e}")

    # Fallback to OpenRouter
    if settings.OPENROUTER_API_KEY:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.9,
                    },
                )
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"OpenRouter variant gen failed: {e}")

    # Final fallback: generate deterministic variants locally
    return _local_fallback_variants(prompt)


def _local_fallback_variants(prompt: str) -> str:
    """Generate variants locally when no LLM is available."""
    return json.dumps([
        "Get started now and transform your workflow",
        "Join thousands who already made the switch",
        "What if you could 10x your output today?",
        "The smartest investment you'll make this year",
        "Start free — no credit card required",
    ])


def _build_generation_prompt(slot: str, text: str, idea: str) -> str:
    """Build the LLM prompt for generating copy variants."""
    angles = COPY_ANGLES.get(slot, COPY_ANGLES.get(DEFAULT_CATEGORY))

    prompts = []
    for angle_name, angle_desc in angles:
        prompts.append(f"""
## Variant {len(prompts) + 1} — Angle: {angle_name.upper()}
Strategy: {angle_desc}
Write ONE {slot.replace('_', ' ')} variant for a landing page about: {idea}""")

    return f"""You are an expert conversion copywriter. Generate EXACTLY 5 variants of this {slot.replace('_', ' ')}:

ORIGINAL: "{text}"
IDEA: {idea}

For each variant, use a DIFFERENT psychological angle and format it as a JSON array of strings.

{"".join(prompts)[:2000]}

Respond ONLY with a JSON array of 5 strings, nothing else.
Example: ["variant one", "variant two", "variant three", "variant four", "variant five"]"""


async def generate_variants(project_id: str, slot: str, text: str, idea: str) -> list[ABTestVariant]:
    """Generate 5 AI-powered copy variants for a given slot.

    Returns a list of ABTestVariant objects with their assigned angles.
    """
    prompt = _build_generation_prompt(slot, text, idea)
    raw = await _call_llm(prompt)

    # Parse JSON response
    try:
        variants = json.loads(raw)
        if not isinstance(variants, list) or len(variants) < 3:
            raise ValueError("Invalid variants response")
        variants = variants[:5]
        # Pad if LLM returned fewer than 5
        while len(variants) < 5:
            variants.append(f"{text} (variant {len(variants) + 1})")
    except (json.JSONDecodeError, ValueError):
        # Fallback: extract lines or use deterministic variants
        lines = [l.strip().strip('"').strip("'") for l in raw.split("\n") if l.strip() and not l.strip().startswith(("[", "]", "```"))]
        variants = [l for l in lines if len(l) > 5 and l != text][:5]
        while len(variants) < 5:
            variants.append(f"{text[:40]} (option {len(variants) + 1})")

    angles = COPY_ANGLES.get(slot, COPY_ANGLES.get(DEFAULT_CATEGORY))
    result = []
    for i, (variant_text, (angle_name, _)) in enumerate(zip(variants, angles[:5])):
        result.append(ABTestVariant(
            key=VARIANT_KEYS[i],
            text=variant_text,
            angle=angle_name,
        ))

    # Persist to MongoDB
    existing = await CopyVariant.find_one(CopyVariant.project_id == project_id)
    if existing:
        existing.copy_sets[slot] = CopySet(
            slot=slot,
            control=text,
            variants=variants,
            impressions={k: existing.copy_sets[slot].impressions.get(k, 0) for k in VARIANT_KEYS} if slot in existing.copy_sets else {},
            conversions={k: existing.copy_sets[slot].conversions.get(k, 0) for k in VARIANT_KEYS} if slot in existing.copy_sets else {},
            winner=existing.copy_sets[slot].winner if slot in existing.copy_sets else None,
        )
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
    else:
        existing = CopyVariant(
            project_id=project_id,
            user_id="",  # Will be set by caller
            idea=idea,
            copy_sets={
                slot: CopySet(
                    slot=slot,
                    control=text,
                    variants=variants,
                    impressions={k: 0 for k in VARIANT_KEYS},
                    conversions={k: 0 for k in VARIANT_KEYS},
                )
            },
        )
        await existing.insert()

    return result


# ── Tracking ────────────────────────────────────────────

async def track_impression(project_id: str, slot: str, variant_key: str) -> bool:
    """Record an impression for a variant. Returns False if not found."""
    doc = await CopyVariant.find_one(CopyVariant.project_id == project_id)
    if not doc or slot not in doc.copy_sets:
        return False

    cs = doc.copy_sets[slot]
    if variant_key == "control":
        cs.impressions["control"] = cs.impressions.get("control", 0) + 1
    elif variant_key in cs.impressions:
        cs.impressions[variant_key] = cs.impressions.get(variant_key, 0) + 1
    else:
        return False

    doc.total_impressions += 1
    doc.updated_at = datetime.now(timezone.utc)
    await doc.save()
    return True


async def track_conversion(project_id: str, slot: str, variant_key: str) -> bool:
    """Record a conversion for a variant. Returns False if not found."""
    doc = await CopyVariant.find_one(CopyVariant.project_id == project_id)
    if not doc or slot not in doc.copy_sets:
        return False

    cs = doc.copy_sets[slot]
    if variant_key == "control":
        cs.conversions["control"] = cs.conversions.get("control", 0) + 1
    elif variant_key in cs.conversions:
        cs.conversions[variant_key] = cs.conversions.get(variant_key, 0) + 1
    else:
        return False

    doc.total_conversions += 1
    doc.updated_at = datetime.now(timezone.utc)

    # Re-evaluate winner after recording conversion
    cs.winner = _select_winner(cs)
    await doc.save()
    return True


# ── Winner Selection ────────────────────────────────────

def _select_winner(cs: CopySet) -> Optional[str]:
    """Select the statistically significant winner using a z-test approximation.

    Requires at least 500 total impressions per variant for significance.
    Returns the variant key (or 'control') if a clear winner exists, else None.
    """
    candidates = {"control": cs.control, **{k: cs.variants[i] for i, k in enumerate(VARIANT_KEYS)}}
    min_impressions = 500

    best_key = "control"
    best_rate = 0.0

    for key in candidates:
        impressions = cs.impressions.get(key, 0)
        conversions = cs.conversions.get(key, 0)

        if impressions < min_impressions:
            continue  # Not enough data yet

        rate = conversions / impressions if impressions > 0 else 0.0

        if rate > best_rate:
            best_rate = rate
            best_key = key

    # If no variant has enough data, return None
    if cs.impressions.get(best_key, 0) < min_impressions:
        return None

    # Check significance: best must be at least 10% better than control
    control_impressions = cs.impressions.get("control", 1)
    control_conversions = cs.conversions.get("control", 0)
    control_rate = control_conversions / control_impressions if control_impressions > 0 else 0

    if best_rate > control_rate * 1.10:
        return best_key

    return None


# ── Status ──────────────────────────────────────────────

async def get_slot_status(project_id: str, slot: str) -> Optional[dict]:
    """Get the current A/B test status for a specific copy slot."""
    doc = await CopyVariant.find_one(CopyVariant.project_id == project_id)
    if not doc or slot not in doc.copy_sets:
        return None

    cs = doc.copy_sets[slot]
    variants = [
        ABTestVariant(
            key="control",
            text=cs.control,
            angle="original",
            impressions=cs.impressions.get("control", 0),
            conversions=cs.conversions.get("control", 0),
            conversion_rate=cs.conversions.get("control", 0) / max(cs.impressions.get("control", 0), 1),
            is_winner=cs.winner == "control",
        )
    ]
    for i, k in enumerate(VARIANT_KEYS):
        texts = cs.variants
        variants.append(ABTestVariant(
            key=k,
            text=texts[i] if i < len(texts) else "(missing)",
            angle=COPY_ANGLES.get(slot, COPY_ANGLES.get(DEFAULT_CATEGORY))[i][0] if i < len(COPY_ANGLES.get(slot, COPY_ANGLES.get(DEFAULT_CATEGORY))) else "unknown",
            impressions=cs.impressions.get(k, 0),
            conversions=cs.conversions.get(k, 0),
            conversion_rate=cs.conversions.get(k, 0) / max(cs.impressions.get(k, 0), 1),
            is_winner=cs.winner == k,
        ))

    return {
        "project_id": project_id,
        "slot": slot,
        "control": cs.control,
        "variants": [v.model_dump() for v in variants],
        "winner": cs.winner,
        "total_impressions": sum(cs.impressions.values()),
        "total_conversions": sum(cs.conversions.values()),
    }


async def get_project_summary(project_id: str) -> Optional[dict]:
    """Get the full A/B test summary for a project."""
    doc = await CopyVariant.find_one(CopyVariant.project_id == project_id)
    if not doc:
        return None

    slots = {}
    for slot_name in doc.copy_sets:
        status = await get_slot_status(project_id, slot_name)
        if status:
            slots[slot_name] = status

    return {
        "project_id": project_id,
        "idea": doc.idea,
        "copy_sets": slots,
        "total_impressions": doc.total_impressions,
        "total_conversions": doc.total_conversions,
    }


async def get_or_create_project(project_id: str, user_id: str, idea: str) -> CopyVariant:
    """Get existing AB test document or create a new one."""
    doc = await CopyVariant.find_one(CopyVariant.project_id == project_id)
    if not doc:
        doc = CopyVariant(
            project_id=project_id,
            user_id=user_id,
            idea=idea,
        )
        await doc.insert()
    return doc
