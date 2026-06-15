"""Landing page builder — fully data-driven from ResearchReport."""

from ..research.models import ResearchReport
from ..utils.html import esc_html, theme_toggle_html, i18n_switcher_html, schema_org_html

_esc = esc_html  # alias for local compatibility
_theme_toggle = theme_toggle_html
_i18n_switcher = i18n_switcher_html
_build_schema = schema_org_html


def build_landing_html(report: ResearchReport, hero_image_url: str | None = None) -> str:
    """Generate a high-quality landing page driven entirely by research data.

    Args:
        report: Research report with market data.
        hero_image_url: Optional URL for a generated hero image.
    """
    idea = report.idea[:80]
    tagline = report.recommended_positioning or f"{idea} — a new approach"
    pricing = report.recommended_pricing_range or "Free to get started"
    features = report.recommended_mvp_features or []
    competitors = report.competitors or []
    risks = report.risk_factors or []
    opps = report.opportunity_gaps or []
    validation = report.market_validation
    sizing = report.market_sizing
    summary = report.summary or ""

    # ── Feature Cards (data-driven) ──
    feature_cards = ""
    icon_list = ["paintbrush", "rocket", "chart", "shield", "zap", "globe"]
    for i, f in enumerate(features[:6]):
        icon = icon_list[i % len(icon_list)]
        fname = f[:50]
        fdesc = f[50:150] if len(f) > 50 else f
        feature_cards += f"""
          <article class="relative bg-white dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700 hover:border-teal-500/50 dark:hover:border-teal-500/50 transition-colors" aria-label="{_esc(fname)}">
            <div class="w-10 h-10 rounded-lg bg-teal-100 dark:bg-teal-500/10 flex items-center justify-center mb-4" aria-hidden="true">
              {_svg_icon(icon)}
            </div>
            <h3 class="text-lg font-semibold text-slate-900 dark:text-white mb-2">{_esc(fname)}</h3>
            <p class="text-sm text-slate-600 dark:text-slate-400 leading-relaxed">{_esc(fdesc)}</p>
          </article>"""

    # ── Data-driven Hero Visual ──
    # Show actual research insights instead of generic image resizer
    research_insights = _build_hero_visual(idea, competitors, opps, features, sizing)

    # ── Data-driven Social Proof / Market Signals ──
    social_proof = _build_social_proof(competitors, opps, validation, features)

    # ── How It Works (based on actual features) ──
    how_it_works = _build_how_it_works(idea, features)

    # ── Competitor Comparison Table ──
    comp_table = ""
    if competitors:
        comp_rows = ""
        for c in competitors[:4]:
            weakness = c.weaknesses[0] if c.weaknesses else "Limited"
            strength = c.strengths[0] if c.strengths else "Established"
            pain = c.pain_points[0] if c.pain_points else ""
            comp_rows += f"""
            <tr class="border-b border-slate-200 dark:border-slate-700">
              <td class="py-3 px-4 text-sm font-medium text-slate-900 dark:text-white">{_esc(c.name[:30])}</td>
              <td class="py-3 px-4 text-sm text-slate-600 dark:text-slate-400">{_esc(strength[:60])}</td>
              <td class="py-3 px-4 text-sm text-amber-700 dark:text-amber-400">{_esc(weakness[:60])}</td>
              <td class="py-3 px-4 text-sm text-slate-500 dark:text-slate-400">{_esc(pain[:60]) if pain else '—'}</td>
            </tr>"""
        comp_table = f"""
        <section class="py-20" aria-label="Competitor comparison">
          <div class="max-w-6xl mx-auto px-6">
            <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-3">
              <span class="lang-en">How We Compare</span>
              <span class="lang-es">Como Comparamos</span>
              <span class="lang-de">Wie Wir Abschneiden</span>
            </h2>
            <p class="text-slate-600 dark:text-slate-400 text-center mb-10 max-w-xl mx-auto">
              <span class="lang-en">Market gaps identified during research</span>
              <span class="lang-es">Oportunidades de mercado identificadas</span>
              <span class="lang-de">Marktlucken aus der Recherche</span>
            </p>
            <div class="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
              <table class="w-full text-left">
                <thead>
                  <tr class="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                    <th class="py-3 px-4 text-sm font-semibold text-teal-700 dark:text-teal-400">
                      <span class="lang-en">Competitor</span>
                      <span class="lang-es">Competidor</span>
                      <span class="lang-de">Wettbewerber</span>
                    </th>
                    <th class="py-3 px-4 text-sm font-semibold text-teal-700 dark:text-teal-400">
                      <span class="lang-en">Strength</span>
                      <span class="lang-es">Fortaleza</span>
                      <span class="lang-de">Starke</span>
                    </th>
                    <th class="py-3 px-4 text-sm font-semibold text-teal-700 dark:text-teal-400">
                      <span class="lang-en">Weakness</span>
                      <span class="lang-es">Debilidad</span>
                      <span class="lang-de">Schwache</span>
                    </th>
                    <th class="py-3 px-4 text-sm font-semibold text-teal-700 dark:text-teal-400">
                      <span class="lang-en">User Pain</span>
                      <span class="lang-es">Dolor de Usuario</span>
                      <span class="lang-de">Nutzerproblem</span>
                    </th>
                  </tr>
                </thead>
                <tbody>{comp_rows}</tbody>
              </table>
            </div>
          </div>
        </section>"""

    # ── Opportunity Gaps ──
    opps_section = ""
    if opps:
        opp_items = ""
        for g in opps[:3]:
            sev_color = {"high": "text-red-600 dark:text-red-400", "medium": "text-amber-600 dark:text-amber-400", "low": "text-green-600 dark:text-green-400"}.get(g.severity, "text-slate-600 dark:text-slate-400")
            opp_items += f"""
            <div class="bg-white dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
              <span class="text-xs font-semibold uppercase tracking-wider {sev_color}">{_esc(g.severity)} priority</span>
              <h3 class="text-white font-medium mt-1 mb-2">{_esc(g.gap[:80])}</h3>
              <p class="text-sm text-slate-600 dark:text-slate-400">{_esc(g.evidence[0][:100]) if g.evidence else ''}</p>
            </div>"""
        opps_section = f"""
        <section class="py-20 bg-slate-50 dark:bg-slate-900/50" aria-label="Opportunity gaps">
          <div class="max-w-6xl mx-auto px-6">
            <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-3">
              <span class="lang-en">Opportunity Gaps</span>
              <span class="lang-es">Oportunidades de Mercado</span>
              <span class="lang-de">Marktchancen</span>
            </h2>
            <p class="text-slate-600 dark:text-slate-400 text-center mb-10 max-w-xl mx-auto">
              <span class="lang-en">Market opportunities from our research</span>
              <span class="lang-es">Oportunidades de mercado de nuestra investigacion</span>
              <span class="lang-de">Marktchancen aus unserer Recherche</span>
            </p>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6">{opp_items}</div>
          </div>
        </section>"""

    # ── Pricing Section (data-driven) ──
    pricing_section = _build_pricing_section(idea, pricing, competitors)

    # ── Risk Factors ──
    risk_items = ""
    for r in risks[:4]:
        risk_items += f'<li class="flex items-start gap-3 text-slate-600 dark:text-slate-400"><svg class="w-5 h-5 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01"/></svg><span>{_esc(r[:120])}</span></li>'

    # ── FAQ (data-driven) ──
    faqs = [
        ("What makes this different?", f"We identified key gaps in {len(opps)} market opportunities that existing solutions miss." if opps else "We built specifically for gaps in existing solutions."),
        ("How does pricing work?", f"{_esc(pricing)}. No hidden fees, cancel anytime."),
        ("Is there an API?", "Yes, API-first by design. Comprehensive docs and SDKs included."),
        ("How fast can I integrate?", "Minutes. Self-serve with ready-to-use endpoints and examples."),
    ]
    if summary:
        faqs.insert(0, ("What's the big insight?", summary[:200]))
    faq_html = ""
    for q, a in faqs[:5]:
        faq_html += f"""
          <details class="group bg-white dark:bg-slate-800 rounded-xl p-5 border border-slate-200 dark:border-slate-700 open:border-teal-500/50 transition-colors" aria-label="{_esc(q)}">
            <summary class="flex items-center justify-between cursor-pointer text-slate-900 dark:text-white font-medium">
              <span>{_esc(q)}</span>
              <svg class="w-5 h-5 text-slate-400 group-open:rotate-180 transition-transform shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
              </svg>
            </summary>
            <p class="mt-3 text-slate-600 dark:text-slate-400 leading-relaxed text-sm">{_esc(a)}</p>
          </details>"""

    # ── Schema.org ──
    schema_org = _build_schema(idea, tagline)

    return _render_full_html(
        idea=idea, tagline=tagline, pricing=pricing,
        feature_cards=feature_cards, research_insights=research_insights,
        social_proof=social_proof, how_it_works=how_it_works,
        comp_table=comp_table, opps_section=opps_section,
        pricing_section=pricing_section, risk_items=risk_items,
        faq_html=faq_html, schema_org=schema_org,
        competitors_count=len(competitors), features_count=len(features),
        opps_count=len(opps), risks_count=min(len(risks), 99),
        hero_image_url=hero_image_url,
    )


# ═══════════════════════════════════════════════════════════
#  SECTION BUILDERS
# ═══════════════════════════════════════════════════════════

def _build_hero_visual(idea, competitors, opps, features, sizing) -> str:
    """Build a data-driven hero visual showing actual research insights."""
    insight_lines = []
    if competitors:
        comp_names = ", ".join(c.name for c in competitors[:4])
        insight_lines.append(f'<div class="flex items-center gap-2 text-slate-300"><svg class="w-4 h-4 text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>{len(competitors)} competitors analyzed: {_esc(comp_names[:100])}...</div>')

    if opps:
        top_gap = opps[0]
        insight_lines.append(f'<div class="flex items-center gap-2 text-slate-300"><svg class="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6"/></svg>Top gap: {_esc(top_gap.gap[:120])}</div>')

    if features:
        insight_lines.append(f'<div class="flex items-center gap-2 text-slate-300"><svg class="w-4 h-4 text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>{len(features)} MVP features identified</div>')

    if sizing and sizing.growth_rate:
        insight_lines.append(f'<div class="flex items-center gap-2 text-slate-300"><svg class="w-4 h-4 text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>Market growing at {_esc(sizing.growth_rate)}</div>')

    if not insight_lines:
        insight_lines.append(f'<div class="text-slate-400">Research-driven insights for {_esc(idea[:60])}</div>')

    insights_html = "\n".join(insight_lines)

    return f"""
      <div class="mt-10 mx-auto max-w-3xl" aria-label="Research insights for {_esc(idea[:50])}">
        <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-lg">
          <div class="flex items-center justify-between px-5 py-4 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
            <div class="flex items-center gap-3">
              <div class="flex gap-1.5" aria-hidden="true">
                <span class="w-3 h-3 rounded-full bg-red-500"></span>
                <span class="w-3 h-3 rounded-full bg-yellow-500"></span>
                <span class="w-3 h-3 rounded-full bg-green-500"></span>
              </div>
              <span class="text-sm font-mono text-slate-500 dark:text-slate-400">research-insights</span>
            </div>
            <span class="px-2 py-0.5 text-xs font-medium bg-teal-100 dark:bg-teal-500/10 text-teal-700 dark:text-teal-400 rounded">VALIDATED</span>
          </div>
          <div class="p-6 space-y-3 text-sm">
            {insights_html}
          </div>
        </div>
      </div>"""


def _build_social_proof(competitors, opps, validation, features) -> str:
    """Build social proof section from real research data, replacing fake testimonials."""
    proofs = []

    # Data point 1: Competitor analysis
    if competitors:
        proofs.append({
            "icon": "search",
            "label_en": f"Competitor Analysis",
            "label_es": f"Analisis de {len(competitors)} Competidores",
            "label_de": f"Analyse von {len(competitors)} Wettbewerbern",
            "desc_en": f"We analyzed {len(competitors)} competitors to find where they fall short — so you don't have to.",
            "desc_es": f"Analizamos {len(competitors)} competidores para encontrar sus debilidades.",
            "desc_de": f"Wir haben {len(competitors)} Wettbewerber analysiert, um ihre Schwachen zu finden.",
        })

    # Data point 2: Market gaps
    if opps:
        proofs.append({
            "icon": "target",
            "label_en": f"Market Gaps Identified",
            "label_es": f"Oportunidades Detectadas",
            "label_de": f"Marktlucken Erkannt",
            "desc_en": f"Found {len(opps)} specific opportunity gaps that current solutions miss.",
            "desc_es": f"Encontramos {len(opps)} oportunidades que las soluciones actuales ignoran.",
            "desc_de": f"{len(opps)} spezifische Marktlucken, die aktuelle Losungen ubersehen.",
        })

    # Data point 3: Community signals
    signals = []
    if validation:
        if validation.reddit_posts_found > 0:
            signals.append(f"{validation.reddit_posts_found} Reddit posts")
        if validation.hn_mentions > 0:
            signals.append(f"{validation.hn_mentions} HN mentions")
        if validation.gh_similar_projects > 0:
            signals.append(f"{validation.gh_similar_projects} GitHub projects")
    if signals:
        proofs.append({
            "icon": "users",
            "label_en": "Community Demand",
            "label_es": "Demanda de la Comunidad",
            "label_de": "Community-Nachfrage",
            "desc_en": f"Real community signals: {', '.join(signals)} show demand exists.",
            "desc_es": f"Senales reales: {', '.join(signals)} muestran que hay demanda.",
            "desc_de": f"Echte Signale: {', '.join(signals)} zeigen bestehende Nachfrage.",
        })

    # Fallback
    if not proofs:
        proofs.append({
            "icon": "rocket",
            "label_en": "Research-Backed",
            "label_es": "Respaldado por Investigacion",
            "label_de": "Forschungsgestutzt",
            "desc_en": f"Every recommendation is based on real market research data.",
            "desc_es": f"Cada recomendacion se basa en datos reales de mercado.",
            "desc_de": f"Jede Empfehlung basiert auf echten Marktforschungsdaten.",
        })

    cards_html = ""
    for p in proofs:
        svg = _svg_icon(p["icon"])
        cards_html += f"""
        <div class="bg-white dark:bg-slate-800/50 rounded-xl p-6 border border-slate-200 dark:border-slate-700 text-center fade-in-up">
          <div class="w-12 h-12 rounded-xl bg-teal-100 dark:bg-teal-500/10 flex items-center justify-center mx-auto mb-4">{svg}</div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white mb-2">
            <span class="lang-en">{_esc(p['label_en'])}</span>
            <span class="lang-es">{_esc(p['label_es'])}</span>
            <span class="lang-de">{_esc(p['label_de'])}</span>
          </h3>
          <p class="text-sm text-slate-600 dark:text-slate-400">
            <span class="lang-en">{_esc(p['desc_en'])}</span>
            <span class="lang-es">{_esc(p['desc_es'])}</span>
            <span class="lang-de">{_esc(p['desc_de'])}</span>
          </p>
        </div>"""

    return f"""
      <section class="py-20" aria-label="Market insights">
        <div class="max-w-6xl mx-auto px-6">
          <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-3">
            <span class="lang-en">Backed by Real Research</span>
            <span class="lang-es">Respaldado por Investigacion Real</span>
            <span class="lang-de">Durch Echte Forschung Gestutzt</span>
          </h2>
          <p class="text-slate-600 dark:text-slate-400 text-center mb-10 max-w-xl mx-auto">
            <span class="lang-en">Every insight comes from actual market data, not guesswork</span>
            <span class="lang-es">Cada insight proviene de datos reales de mercado</span>
            <span class="lang-de">Jede Erkenntnis stammt aus echten Marktdaten</span>
          </p>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-6">{cards_html}</div>
        </div>
      </section>"""


def _build_how_it_works(idea, features) -> str:
    """Build How It Works section based on actual MVP features."""
    steps = []
    # Map first 3 features to steps, or use defaults
    if features:
        step_names = [
            (features[0][:40], "Start with our core feature to solve the main problem."),
            (features[1][:40] if len(features) > 1 else "Integrate", "Connect with your existing tools and workflows."),
            (features[2][:40] if len(features) > 2 else "Scale", "Grow from first user to thousands seamlessly."),
        ]
    else:
        step_names = [
            ("Sign Up", "Create your account in seconds."),
            ("Configure", f"Set up {idea[:30]} to match your needs."),
            ("Launch", "Go live and start getting results."),
        ]

    step_html = ""
    colors = ["teal", "amber", "teal"]
    for i, (name, desc) in enumerate(step_names):
        c = colors[i]
        step_html += f"""
        <div class="text-center">
          <div class="w-14 h-14 rounded-xl bg-{c}-100 dark:bg-{c}-500/10 flex items-center justify-center mx-auto mb-4" aria-hidden="true">
            <span class="text-xl font-bold text-{c}-700 dark:text-{c}-400">{i+1}</span>
          </div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white mb-2">{_esc(name)}</h3>
          <p class="text-sm text-slate-600 dark:text-slate-400">{_esc(desc)}</p>
        </div>"""

    return f"""
      <section id="how-it-works" class="py-20 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-200 dark:border-slate-800" aria-label="How it works">
        <div class="max-w-4xl mx-auto px-6">
          <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-12">
            <span class="lang-en">How It Works</span>
            <span class="lang-es">Como Funciona</span>
            <span class="lang-de">So Funktionierts</span>
          </h2>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-8">{step_html}</div>
        </div>
      </section>"""


def _build_pricing_section(idea, pricing_str, competitors) -> str:
    """Build pricing section from research data."""
    comp_prices = [c for c in competitors if c.pricing]
    comp_note = ""
    if comp_prices:
        comp_names = ", ".join(f"{c.name}: {c.pricing}" for c in comp_prices[:2])
        comp_note = f'<p class="text-sm text-slate-500 mt-2">Competitor pricing: {_esc(comp_names)}</p>'

    return f"""
      <section id="pricing" class="py-20" aria-label="Pricing">
        <div class="max-w-4xl mx-auto px-6 text-center">
          <h2 class="text-3xl font-bold text-slate-900 dark:text-white mb-3">Simple Pricing</h2>
          <p class="text-lg text-slate-600 dark:text-slate-400 mb-4">{_esc(pricing_str)}</p>
          {comp_note}
          <div class="flex flex-wrap justify-center gap-4 mt-8">
            <a href="#" class="px-8 py-4 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl transition-colors" aria-label="Start free trial">
              <span class="lang-en">Start Free Trial</span>
              <span class="lang-es">Prueba Gratis</span>
              <span class="lang-de">Kostenlos Testen</span>
            </a>
            <a href="#faq" class="px-8 py-4 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-semibold rounded-xl border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors" aria-label="View FAQ">
              <span class="lang-en">View FAQ</span>
              <span class="lang-es">Ver FAQ</span>
              <span class="lang-de">FAQ Ansehen</span>
            </a>
          </div>
        </div>
      </section>"""


# ═══════════════════════════════════════════════════════════
#  FULL HTML RENDER
# ═══════════════════════════════════════════════════════════

def _render_full_html(
    idea, tagline, pricing, feature_cards, research_insights,
    social_proof, how_it_works, comp_table, opps_section,
    pricing_section, risk_items, faq_html, schema_org,
    competitors_count, features_count, opps_count, risks_count,
    hero_image_url=None,
) -> str:
    """Assemble the complete HTML page."""

    hero_image_html = ''
    if hero_image_url:
        hero_image_html = f'''
      <div class="mt-10 mx-auto max-w-4xl hero-image-container fade-in-up delay-4">
        <img src="{_esc(hero_image_url)}" alt="Hero illustration for {_esc(idea[:40])}" class="w-full rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700" loading="lazy">
      </div>'''

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(idea)} — {_esc(tagline[:60])}</title>
<meta name="description" content="{_esc(tagline[:160])}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://product.dev">
<meta property="og:type" content="website">
<meta property="og:title" content="{_esc(idea)}">
<meta property="og:description" content="{_esc(tagline[:160])}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(idea)}">
<meta name="twitter:description" content="{_esc(tagline[:160])}">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={{darkMode:'class',theme:{{extend:{{colors:{{primary:{{400:'#2dd4bf',500:'#14b8a6',600:'#0d9488'}}}},fontFamily:{{sans:['DM Sans','system-ui','sans-serif']}}}}}}}}</script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
{schema_org}
<style>
  :root {{
    --sf-primary: oklch(25% 0.10 185);
    --sf-on-primary: oklch(97% 0.003 185);
  }}
  * {{ font-family: 'DM Sans', system-ui, sans-serif; scroll-behavior: smooth; }}
  body {{ margin: 0; line-height: 1.6; }}
  .fade-in {{ animation: fadeIn 0.6s ease-out forwards; opacity: 0; }}
  .fade-in-up {{ animation: fadeInUp 0.6s ease-out forwards; opacity: 0; }}
  @keyframes fadeIn {{ to {{ opacity: 1; }} }}
  @keyframes fadeInUp {{ from {{ opacity: 0; transform: translateY(20px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  @keyframes countUp {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
  .delay-1 {{ animation-delay: 0.1s; }} .delay-2 {{ animation-delay: 0.2s; }}
  .delay-3 {{ animation-delay: 0.3s; }} .delay-4 {{ animation-delay: 0.4s; }} .delay-5 {{ animation-delay: 0.5s; }}
  details[open] summary {{ margin-bottom: 0; }}
  ::selection {{ background: rgba(20,184,166,0.2); }}
  [data-lang="es"] .lang-en, [data-lang="de"] .lang-en {{ display: none; }}
  [data-lang="en"] .lang-es, [data-lang="de"] .lang-es {{ display: none; }}
  [data-lang="en"] .lang-de, [data-lang="es"] .lang-de {{ display: none; }}
  .stat-value {{ font-size: 2.25rem; font-weight: 800; color: var(--sf-primary); animation: countUp 0.5s ease-out both; }}
  @media (prefers-reduced-motion: reduce) {{ .fade-in, .fade-in-up, .stat-value {{ animation: none; opacity: 1; }} }}
</style>
</head>
<body class="bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 transition-colors duration-200">

<header class="fixed top-0 w-full z-50 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-950/95 backdrop-blur-sm" role="banner">
  <nav class="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
    <a href="/" class="text-lg font-bold text-teal-700 dark:text-teal-400">{_esc(idea[:30])}</a>
    <div class="flex items-center gap-3">
      <a href="#features" class="text-sm text-slate-600 dark:text-slate-300 hover:text-teal-700 dark:hover:text-teal-400 transition hidden md:block lang-en">Features</a>
      <a href="#features" class="text-sm text-slate-600 dark:text-slate-300 hover:text-teal-700 dark:hover:text-teal-400 transition hidden md:block lang-es">Caracteristicas</a>
      <a href="#features" class="text-sm text-slate-600 dark:text-slate-300 hover:text-teal-700 dark:hover:text-teal-400 transition hidden md:block lang-de">Funktionen</a>
      <a href="#pricing" class="text-sm text-slate-600 dark:text-slate-300 hover:text-teal-700 dark:hover:text-teal-400 transition hidden md:block lang-en">Pricing</a>
      <a href="#pricing" class="text-sm text-slate-600 dark:text-slate-300 hover:text-teal-700 dark:hover:text-teal-400 transition hidden md:block lang-es">Precios</a>
      <a href="#pricing" class="text-sm text-slate-600 dark:text-slate-300 hover:text-teal-700 dark:hover:text-teal-400 transition hidden md:block lang-de">Preise</a>
      {_theme_toggle()}
      {_i18n_switcher()}
    </div>
  </nav>
</header>

<main>
  <!-- HERO -->
  <section class="pt-32 pb-20" aria-label="Hero">
    <div class="max-w-6xl mx-auto px-6 text-center">
      <div class="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-teal-100 dark:bg-teal-500/10 border border-teal-200 dark:border-teal-500/20 text-teal-700 dark:text-teal-400 text-sm font-medium mb-6 fade-in">
        <span class="w-2 h-2 rounded-full bg-teal-500" aria-hidden="true"></span>
        <span class="lang-en">Research-Backed</span>
        <span class="lang-es">Respaldado por Investigacion</span>
        <span class="lang-de">Forschungsgestutzt</span>
      </div>
      <h1 class="text-4xl md:text-6xl font-bold text-slate-900 dark:text-white leading-tight tracking-tight mb-5 fade-in-up">
        {_esc(idea[:50])}
      </h1>
      <p class="text-lg md:text-xl text-slate-600 dark:text-slate-400 max-w-2xl mx-auto mb-8 fade-in-up delay-2">
        {_esc(tagline[:150])}
      </p>
      <div class="flex flex-wrap justify-center gap-4 fade-in-up delay-3">
        <a href="#" class="px-8 py-4 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl transition-colors">
          <span class="lang-en">Get Started</span>
          <span class="lang-es">Comenzar</span>
          <span class="lang-de">Loslegen</span>
        </a>
        <a href="#how-it-works" class="px-8 py-4 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-semibold rounded-xl border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
          <span class="lang-en">See How</span>
          <span class="lang-es">Ver Como</span>
          <span class="lang-de">Wie Es Funktioniert</span>
        </a>
      </div>
      {research_insights}
      {hero_image_html}
    </div>
  </section>

  <!-- STATS -->
  <section class="py-16 bg-slate-50 dark:bg-slate-900/50 border-t border-b border-slate-200 dark:border-slate-800" aria-label="Key metrics">
    <div class="max-w-4xl mx-auto px-6">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
        <div class="fade-in-up delay-1">
          <div class="stat-value" data-count="{competitors_count}">0</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-en">Competitors Analyzed</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-es">Competidores</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-de">Wettbewerber</div>
        </div>
        <div class="fade-in-up delay-2">
          <div class="stat-value" data-count="{features_count}">0</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-en">MVP Features</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-es">Funcionalidades</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-de">MVP Features</div>
        </div>
        <div class="fade-in-up delay-3">
          <div class="stat-value" data-count="{opps_count}">0</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-en">Market Gaps</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-es">Oportunidades</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-de">Marktlucken</div>
        </div>
        <div class="fade-in-up delay-4">
          <div class="stat-value" data-count="{risks_count}">0</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-en">Risks Assessed</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-es">Riesgos Evaluados</div>
          <div class="text-sm text-slate-600 dark:text-slate-400 mt-2 lang-de">Risiken Bewertet</div>
        </div>
      </div>
    </div>
  </section>

  {how_it_works}

  <!-- FEATURES -->
  <section id="features" class="py-20" aria-label="Features">
    <div class="max-w-6xl mx-auto px-6">
      <div class="text-center mb-12">
        <h2 class="text-3xl font-bold text-slate-900 dark:text-white mb-3 lang-en">Everything You Need</h2>
        <h2 class="text-3xl font-bold text-slate-900 dark:text-white mb-3 lang-es">Todo Lo Que Necesitas</h2>
        <h2 class="text-3xl font-bold text-slate-900 dark:text-white mb-3 lang-de">Alles Was Du Brauchst</h2>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {feature_cards if feature_cards else '<p class="text-slate-500 text-center col-span-full">Features coming soon.</p>'}
      </div>
    </div>
  </section>

  {social_proof}

  {comp_table}

  {opps_section}

  {pricing_section}

  <!-- NEWSLETTER -->
  <section class="py-16 bg-teal-50 dark:bg-teal-500/5 border-t border-teal-200 dark:border-teal-500/10" aria-label="Newsletter">
    <div class="max-w-lg mx-auto px-6 text-center">
      <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-en">Stay in the Loop</h2>
      <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-es">Mantente al Dia</h2>
      <h2 class="text-2xl font-bold text-teal-800 dark:text-teal-300 mb-3 lang-de">Bleib auf dem Laufenden</h2>
      <form class="flex gap-2 max-w-md mx-auto" onsubmit="event.preventDefault();alert('Subscribed!')">
        <input type="email" placeholder="you@email.com" required class="flex-1 px-4 py-3 rounded-xl border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:border-teal-500 transition">
        <button type="submit" class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap lang-en">Subscribe</button>
        <button type="submit" class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap lang-es">Suscribirse</button>
        <button type="submit" class="px-6 py-3 bg-teal-600 hover:bg-teal-500 text-white font-semibold rounded-xl text-sm transition-colors whitespace-nowrap lang-de">Abonnieren</button>
      </form>
    </div>
  </section>

  <!-- RISKS -->
  <section class="py-20 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-200 dark:border-slate-800" aria-label="Considerations">
    <div class="max-w-3xl mx-auto px-6">
      <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-3 lang-en">What We're Solving For</h2>
      <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-3 lang-es">Lo Que Estamos Resolviendo</h2>
      <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-3 lang-de">Woran Wir Arbeiten</h2>
      <ul class="space-y-3 max-w-xl mx-auto mt-10">
        {risk_items if risk_items else '<li class="text-slate-500 text-center">No major risks identified</li>'}
      </ul>
    </div>
  </section>

  <!-- FAQ -->
  <section id="faq" class="py-20" aria-label="FAQ">
    <div class="max-w-2xl mx-auto px-6">
      <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-10 lang-en">Frequently Asked Questions</h2>
      <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-10 lang-es">Preguntas Frecuentes</h2>
      <h2 class="text-3xl font-bold text-slate-900 dark:text-white text-center mb-10 lang-de">Haufige Fragen</h2>
      <div class="space-y-3">{faq_html}</div>
    </div>
  </section>

  <!-- CTA -->
  <section class="py-24 bg-teal-700 dark:bg-teal-900" aria-label="Call to action">
    <div class="max-w-3xl mx-auto px-6 text-center">
      <h2 class="text-3xl md:text-4xl font-bold text-white mb-4 lang-en">Ready to Get Started?</h2>
      <h2 class="text-3xl md:text-4xl font-bold text-white mb-4 lang-es">Listo para Empezar?</h2>
      <h2 class="text-3xl md:text-4xl font-bold text-white mb-4 lang-de">Bereit zum Starten?</h2>
      <p class="text-lg text-teal-100 mb-8 max-w-xl mx-auto lang-en">Start free today with no credit card required.</p>
      <p class="text-lg text-teal-100 mb-8 max-w-xl mx-auto lang-es">Empieza gratis hoy sin tarjeta de credito.</p>
      <p class="text-lg text-teal-100 mb-8 max-w-xl mx-auto lang-de">Starte noch heute kostenlos.</p>
      <a href="#" class="inline-block px-10 py-5 bg-white text-teal-800 font-bold text-lg rounded-xl hover:bg-teal-50 transition-colors lang-en">Start Building</a>
      <a href="#" class="inline-block px-10 py-5 bg-white text-teal-800 font-bold text-lg rounded-xl hover:bg-teal-50 transition-colors lang-es">Empieza a Construir</a>
      <a href="#" class="inline-block px-10 py-5 bg-white text-teal-800 font-bold text-lg rounded-xl hover:bg-teal-50 transition-colors lang-de">Jetzt Bauen</a>
    </div>
  </section>
</main>

<footer class="border-t border-slate-200 dark:border-slate-800 py-10 bg-white dark:bg-slate-950" role="contentinfo">
  <div class="max-w-6xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
    <p class="text-sm text-slate-500">2026 {_esc(idea[:30])}</p>
    <div class="flex gap-6 text-sm text-slate-500">
      <a href="#privacy" class="hover:text-teal-700 dark:hover:text-teal-400 transition lang-en">Privacy</a>
      <a href="#privacy" class="hover:text-teal-700 dark:hover:text-teal-400 transition lang-es">Privacidad</a>
      <a href="#privacy" class="hover:text-teal-700 dark:hover:text-teal-400 transition lang-de">Datenschutz</a>
      <a href="#terms" class="hover:text-teal-700 dark:hover:text-teal-400 transition lang-en">Terms</a>
      <a href="#terms" class="hover:text-teal-700 dark:hover:text-teal-400 transition lang-es">Terminos</a>
      <a href="#terms" class="hover:text-teal-700 dark:hover:text-teal-400 transition lang-de">AGB</a>
    </div>
  </div>
</footer>

<button id="back-to-top" onclick="window.scrollTo({{ top: 0, behavior: 'smooth' }})" class="fixed bottom-6 right-6 z-50 w-12 h-12 rounded-full bg-teal-600 hover:bg-teal-500 text-white shadow-lg flex items-center justify-center opacity-0 translate-y-4 pointer-events-none transition-all duration-300" aria-label="Back to top">
  <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M18 15l-6-6-6 6"/></svg>
</button>

<script>
(function() {{
  var html = document.documentElement;
  var toggle = document.querySelector('[data-theme-toggle]');
  function setTheme(t) {{
    if (t === 'system') {{
      var dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      html.classList.toggle('dark', dark);
      html.setAttribute('data-theme', dark ? 'dark' : 'light');
    }} else {{
      html.classList.toggle('dark', t === 'dark');
      html.setAttribute('data-theme', t);
    }}
    localStorage.setItem('theme', t);
  }}
  setTheme(localStorage.getItem('theme') || 'system');
  if (toggle) toggle.addEventListener('click', function() {{
    var c = html.getAttribute('data-theme');
    setTheme(c === 'dark' ? 'light' : c === 'light' ? 'system' : 'dark');
  }});
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {{
    if (localStorage.getItem('theme') === 'system') setTheme('system');
  }});

  // i18n
  var root = document.body;
  var lt = document.querySelector('[data-lang-toggle]');
  var lm = document.querySelector('[data-lang-menu]');
  var ll = document.querySelector('[data-lang-label]');
  function setLang(l) {{
    root.setAttribute('data-lang', l);
    localStorage.setItem('lang', l);
    if (ll) ll.textContent = l.toUpperCase();
    if (lm) lm.classList.add('hidden');
  }}
  setLang(localStorage.getItem('lang') || 'en');
  if (lt) lt.addEventListener('click', function() {{ lm && lm.classList.toggle('hidden'); }});
  document.addEventListener('click', function(e) {{ if (!e.target.closest('[data-lang-switch]') && lm) lm.classList.add('hidden'); }});
  document.querySelectorAll('[data-lang]').forEach(function(b) {{ b.addEventListener('click', function() {{ setLang(b.getAttribute('data-lang')); }}); }});

  // Back to top
  var btt = document.getElementById('back-to-top');
  window.addEventListener('scroll', function() {{
    if (btt) {{
      if (window.scrollY > 400) btt.classList.remove('opacity-0', 'translate-y-4', 'pointer-events-none');
      else btt.classList.add('opacity-0', 'translate-y-4', 'pointer-events-none');
    }}
  }}, {{ passive: true }});

  // Stat counters
  var statObserver = new IntersectionObserver(function(entries) {{
    entries.forEach(function(e) {{
      if (e.isIntersecting) {{
        var el = e.target;
        var target = parseInt(el.getAttribute('data-count')) || 0;
        var current = 0;
        var step = Math.ceil(target / 50);
        var timer = setInterval(function() {{
          current += step;
          if (current >= target) {{ current = target; clearInterval(timer); }}
          el.textContent = current;
        }}, 16);
        statObserver.unobserve(el);
      }}
    }});
  }}, {{ threshold: 0.5 }});
  document.querySelectorAll('.stat-value[data-count]').forEach(function(el) {{ statObserver.observe(el); }});
}})();
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
#  HELPERS
def _svg_icon(name: str) -> str:
    icons = {
        "paintbrush": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg>',
        "rocket": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z"/></svg>',
        "chart": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/></svg>',
        "shield": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/></svg>',
        "zap": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"/></svg>',
        "globe": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"/></svg>',
        "search": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"/></svg>',
        "target": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
        "users": '<svg class="w-5 h-5 text-teal-600 dark:text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>',
    }
    return icons.get(name, icons["zap"])



