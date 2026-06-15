"""Stripe Setup — creates products and prices for PitchForge tiers.

Usage: cd code/backend && python scripts/setup_stripe.py
"""

import os
import sys
from pathlib import Path

import stripe
from dotenv import load_dotenv

# Load .env from backend directory
load_dotenv()

STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_KEY:
    print("ERROR: STRIPE_SECRET_KEY not found in .env")
    sys.exit(1)

stripe.api_key = STRIPE_KEY
print(f"✓ Stripe API key configured (prefix: {STRIPE_KEY[:12]}...)\n")

TIERS = {
    "free": {
        "name": "Free",
        "metadata": {
            "tier": "free",
            "max_tokens": "2000",
            "max_research_per_day": "1",
            "max_projects_per_month": "3",
        },
    },
    "starter": {
        "name": "Starter",
        "metadata": {
            "tier": "starter",
            "max_tokens": "10000",
            "max_research_per_day": "5",
            "max_projects_per_month": "15",
        },
        "price": {"amount": 900, "currency": "eur", "interval": "month"},
    },
    "pro": {
        "name": "Pro",
        "metadata": {
            "tier": "pro",
            "max_tokens": "50000",
            "max_research_per_day": "20",
            "max_projects_per_month": "50",
        },
        "price": {"amount": 2900, "currency": "eur", "interval": "month"},
    },
    "code_mvp": {
        "name": "Code MVP",
        "metadata": {
            "tier": "code_mvp",
            "max_tokens": "100000",
            "max_research_per_day": "50",
            "max_projects_per_month": "100",
        },
        "price": {"amount": 49900, "currency": "eur", "interval": None},
    },
}


def main():
    results = {}

    for tier_id, cfg in TIERS.items():
        print(f"--- {cfg['name']} ({tier_id}) ---")

        # Find or create product
        existing = None
        products = stripe.Product.list(limit=100, active=True)
        for p in products.data:
            meta = dict(p.metadata or {})
            if meta.get("tier") == tier_id:
                existing = p
                break

        if existing:
            product = stripe.Product.modify(
                existing.id,
                name=cfg["name"],
                metadata=cfg["metadata"],
            )
            print(f"  Updated product: {product.id}")
        else:
            product = stripe.Product.create(
                name=cfg["name"],
                metadata=cfg["metadata"],
            )
            print(f"  Created product: {product.id}")

        # Find or create price
        price_id = None
        price_cfg = cfg.get("price")
        if price_cfg:
            existing_prices = stripe.Price.list(product=product.id, active=True, limit=5)
            if existing_prices.data:
                price_id = existing_prices.data[0].id
                print(f"  Using existing price: {price_id}")
            else:
                price_params = {
                    "product": product.id,
                    "currency": price_cfg["currency"],
                    "unit_amount": price_cfg["amount"],
                }
                if price_cfg["interval"]:
                    price_params["recurring"] = {"interval": price_cfg["interval"]}

                price = stripe.Price.create(**price_params)
                price_id = price.id
                print(f"  Created price: {price_id} ({price_cfg['amount']}¢/{price_cfg['interval'] or 'once'})")
        else:
            print(f"  No price (free tier)")

        results[tier_id] = price_id
        print()

    # Print .env additions
    print("=" * 50)
    print("ADD THESE TO YOUR .env FILE:\n")
    for tier_id, price_id in results.items():
        if price_id:
            print(f"PRICE_{tier_id.upper()}={price_id}")

    print("\nTIER LIMITS (from metadata):\n")
    for tier_id, cfg in TIERS.items():
        meta = cfg["metadata"]
        print(f"  {tier_id:12s} | tokens={meta['max_tokens']:>6s} | research/day={meta['max_research_per_day']:>2s} | projects/month={meta['max_projects_per_month']:>3s}")

    return results


if __name__ == "__main__":
    main()
