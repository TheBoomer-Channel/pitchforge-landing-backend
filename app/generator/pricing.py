"""Pricing page generator — data-driven from ResearchReport with LLM enhancement."""

from ..research.models import ResearchReport
from ..utils.html import esc_html as _esc


def build_pricing_html(report: ResearchReport) -> str:
    """Build pricing page HTML driven by research data."""
    pricing_raw = report.recommended_pricing_range or "Free / $29 / $99"
    features = report.recommended_mvp_features or []
    competitors = report.competitors or []
    idea = report.idea[:40]

    # Parse pricing tiers from the recommendation string and competitor data
    tiers = _derive_tiers(pricing_raw, competitors, features)

    # Build tier cards
    items_html = ""
    for t in tiers:
        popular_class = "popular" if t.get("popular") else ""
        cta_class = "bg-teal-500 text-white hover:bg-teal-600" if t.get("popular") else "bg-slate-700 text-slate-200 hover:bg-slate-600"
        features_html = "".join(
            f'<li class="flex items-center gap-2 text-slate-300"><svg class="w-5 h-5 text-teal-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>{_esc(f)}</li>'
            for f in t["features"]
        )
        items_html += f"""
        <div class="pricing-card {popular_class}">
            <h3 class="text-xl font-bold text-white mb-1">{_esc(t['name'])}</h3>
            <div class="text-3xl font-bold text-teal-400 mb-4">{_esc(t['price'])}</div>
            <p class="text-slate-400 text-sm mb-6">{_esc(t['desc'])}</p>
            <ul class="space-y-3 mb-8">{features_html}</ul>
            <a href="#" class="block w-full text-center py-3 rounded-lg font-semibold {cta_class} transition">Get Started</a>
        </div>"""

    # Feature comparison table driven by real features + tiers
    all_features = _collect_all_features(tiers, features)
    features_table = ""
    for f in all_features:
        checks = ""
        for t in tiers:
            has = f in t["features"]
            if t.get("popular"):
                checks += f'<td class="py-3 text-center text-teal-400">{"✓" if has else "—"}</td>'
            else:
                checks += f'<td class="py-3 text-center text-slate-400">{"✓" if has else "—"}</td>'
        features_table += f"<tr class='border-b border-slate-700'><td class='py-3 text-slate-300'>{_esc(f)}</td>{checks}</tr>"

    # Competitor pricing context
    comp_context = ""
    comp_prices = [c for c in competitors if c.pricing]
    if comp_prices:
        comp_context = '<p class="text-sm text-slate-500 mt-2">'
        comp_context += " · ".join(f"{_esc(c.name)}: {_esc(c.pricing)}" for c in comp_prices[:3])
        comp_context += "</p>"

    # FAQ (data-driven where possible)
    faq_items = _build_faq(pricing_raw, competitors, features)
    faq_html = "".join(f"""
    <div class="border-b border-slate-700 py-4">
        <button onclick="this.nextElementSibling.classList.toggle('hidden')" class="flex justify-between items-center w-full text-left text-slate-200 font-medium">
            {_esc(q)}<svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </button>
        <div class="hidden mt-2 text-slate-400 text-sm">{_esc(a)}</div>
    </div>""" for q, a in faq_items)

    # Tier headers for comparison table
    tier_headers = "".join(
        f'<th class="py-3 text-center text-slate-400 font-medium">{_esc(t["name"])}</th>'
        + ('<th class="py-3 text-center text-slate-400 font-medium">Free</th>' if i == 0 else '')
        if False else ''
        for i, t in enumerate(tiers)
    )
    # Simple: Free / Starter / Pro
    tier_headers = '<th class="py-3 text-center text-slate-400 font-medium">Free</th><th class="py-3 text-center text-slate-400 font-medium">Starter</th><th class="py-3 text-center text-teal-400 font-medium">Pro</th>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pricing — {_esc(idea)}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'DM Sans', sans-serif; background: #0f172a; color: #e2e8f0; }}
  .pricing-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 32px; transition: transform 0.2s, box-shadow 0.2s; }}
  .pricing-card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 30px rgba(0,0,0,0.3); }}
  .pricing-card.popular {{ border-color: #14b8a6; box-shadow: 0 0 0 1px #14b8a6; }}
</style>
</head>
<body>
<nav class="flex items-center justify-between p-6 max-w-6xl mx-auto">
  <div class="text-xl font-bold text-white">{_esc(idea[:30])}</div>
  <div class="flex gap-6 text-sm text-slate-300">
    <a href="#" class="hover:text-white">Features</a>
    <a href="#" class="text-teal-400 font-semibold">Pricing</a>
    <a href="#" class="hover:text-white">FAQ</a>
  </div>
</nav>

<header class="text-center py-16 px-6">
  <h1 class="text-4xl md:text-5xl font-bold text-white mb-4">Simple, transparent pricing</h1>
  <p class="text-lg text-slate-400 max-w-2xl mx-auto">{_esc(pricing_raw)}</p>
  {comp_context}
  <div class="flex items-center justify-center gap-3 mt-6">
    <span class="text-slate-400">Monthly</span>
    <label class="relative inline-flex items-center cursor-pointer">
      <input type="checkbox" class="sr-only peer" onchange="toggleAnnual()">
      <div class="w-11 h-6 bg-slate-600 rounded-full peer peer-checked:bg-teal-500 after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-full"></div>
    </label>
    <span class="text-slate-400">Annual <span class="text-teal-400 text-sm font-semibold">Save 20%</span></span>
  </div>
</header>

<main class="max-w-6xl mx-auto px-6">
  <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
    {items_html}
  </div>

  <section class="mb-16">
    <h2 class="text-2xl font-bold text-white text-center mb-8">Feature comparison</h2>
    <div class="overflow-x-auto">
      <table class="w-full max-w-3xl mx-auto">
        <thead><tr class="border-b border-slate-600"><th class="py-3 text-left text-slate-400 font-medium">Feature</th>{tier_headers}</tr></thead>
        <tbody>{features_table}</tbody>
      </table>
    </div>
  </section>

  <section class="max-w-2xl mx-auto mb-16">
    <h2 class="text-2xl font-bold text-white text-center mb-8">Frequently asked questions</h2>
    {faq_html}
  </section>

  <section class="text-center py-16 border-t border-slate-700">
    <h2 class="text-3xl font-bold text-white mb-4">Ready to get started?</h2>
    <p class="text-slate-400 mb-8">Start free, upgrade when you need more.</p>
    <a href="#" class="inline-block bg-teal-500 text-white px-8 py-4 rounded-lg font-semibold hover:bg-teal-600 transition">Start Free Trial</a>
  </section>
</main>

<footer class="text-center py-8 text-sm text-slate-500">
  <p>2026 {_esc(idea[:30])}. All rights reserved.</p>
</footer>

<script>
function toggleAnnual() {{
  var isAnnual = document.querySelector('.peer').checked;
  document.querySelectorAll('.pricing-card').forEach(function(card) {{
    var monthly = card.dataset.monthly;
    var annual = card.dataset.annual;
    if (monthly && annual) {{
      card.querySelector('.text-3xl').textContent = isAnnual ? annual : monthly;
    }}
  }});
}}
</script>
</body>
</html>"""


def _derive_tiers(pricing_raw: str, competitors, features) -> list[dict]:
    """Derive pricing tiers from research data instead of hardcoding."""
    import re

    # Extract numbers from pricing string
    numbers = re.findall(r'\$?(\d+)', pricing_raw)
    
    # Default tier structure
    tiers = [
        {
            "name": "Free",
            "price": "$0",
            "desc": "Get started with core features",
            "popular": False,
            "features": (_pick_features(features, 2) if features else ["Basic features", "Community access"]),
        },
        {
            "name": "Starter",
            "price": f"${numbers[0]}" if len(numbers) >= 1 else "$29",
            "desc": "For indie developers and small teams",
            "popular": True,
            "features": (_pick_features(features, 4) if features else ["All Free features", "Advanced features", "Email support", "Custom config"]),
        },
        {
            "name": "Pro",
            "price": f"${numbers[1]}" if len(numbers) >= 2 else f"${numbers[0]}" if len(numbers) == 1 else "$99",
            "desc": "For professional teams that need scale",
            "popular": False,
            "features": (_pick_features(features, 6) if features else ["All Starter features", "Priority support", "API access", "Team management", "SSO", "Dedicated infra"]),
        },
    ]

    # If competitors have pricing, adjust our tiers to be competitive
    comp_prices_nums = []
    for c in competitors:
        if c.pricing:
            nums = [int(n) for n in re.findall(r'\$?(\d+)', c.pricing) if int(n) > 0]
            comp_prices_nums.extend(nums)

    if comp_prices_nums:
        avg_comp = sum(comp_prices_nums) // len(comp_prices_nums)
        # Position Starter slightly below competitor average
        tiers[1]["price"] = f"${max(9, avg_comp - 10)}"
        tiers[2]["price"] = f"${avg_comp * 3}"

    return tiers


def _pick_features(features, count: int) -> list[str]:
    """Pick features from the research data, filling with defaults if needed."""
    defaults = [
        "API access", "Team collaboration", "Analytics dashboard",
        "Email support", "Priority support", "Custom integrations",
        "SSO / SAML", "Dedicated infrastructure",
    ]
    result = []
    for i in range(count):
        if i < len(features):
            result.append(features[i][:60])
        elif i - len(features) < len(defaults):
            result.append(defaults[i - len(features)])
        else:
            result.append(f"Feature {i+1}")
    return result


def _collect_all_features(tiers, mvp_features) -> list[str]:
    """Collect all unique features across tiers for comparison table."""
    seen = set()
    all_f = []
    for t in tiers:
        for f in t["features"]:
            if f not in seen:
                seen.add(f)
                all_f.append(f)
    # Add any remaining MVP features not in tiers
    for f in mvp_features:
        f_short = f[:60]
        if f_short not in seen:
            seen.add(f_short)
            all_f.append(f_short)
    return all_f


def _build_faq(pricing_str, competitors, features) -> list[tuple]:
    """Build FAQ from research context."""
    faq = [
        ("Can I try before buying?", "Yes! Start with our Free tier — no credit card required. Full access to core features."),
        ("Can I upgrade or downgrade anytime?", "Absolutely. Change your plan at any time with prorated billing."),
        ("Is there a discount for annual billing?", "Yes, annual plans are 20% cheaper than monthly."),
    ]

    # Add competitor-specific FAQ
    if competitors:
        comp_names = ", ".join(c.name for c in competitors[:2])
        faq.insert(1, (
            f"How does this compare to {comp_names}?",
            f"We analyzed {len(competitors)} competitors and built specifically for the gaps they miss. "
            f"Better pricing, better features, and no hidden limitations."
        ))

    if features:
        faq.append((
            "What's included in each tier?",
            f"We offer {len(features)} core features across all tiers. "
            "Check the comparison table above for the full breakdown."
        ))

    faq.append((
        "What happens if I exceed my plan limits?",
        "We'll notify you well in advance and suggest the right upgrade path. No surprise bills."
    ))

    return faq



