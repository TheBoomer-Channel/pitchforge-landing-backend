"""Pitch deck builder — data-driven from ResearchReport + Narrative Engine.

Generates:
- HTML pitch deck with scroll-snap slides
- Speaker notes (visible in presenter mode)
- i18n EN/ES/DE
- Dark/light mode toggle
- Fullscreen presentation mode
- Print/PDF export
"""

from typing import List, Optional, Tuple

from ..research.models import ResearchReport
from .narrative import generate_narrative, format_narrative_markdown, SlideNarrative
from ..utils.html import esc_html as _esc


def build_pitch_html(report: ResearchReport, image_urls: list[str | None] | None = None, narrative: SlideNarrative | None = None) -> str:
    """Build pitch deck HTML from research data + narrative engine.

    Args:
        report: Research report with market data.
        image_urls: Optional list of image URLs (relative paths) for each slide.
        narrative: Pre-computed narrative (to avoid double generation).
    """
    if narrative is None:
        narrative = generate_narrative(report)
    idea = report.idea[:50]
    tagline = report.recommended_positioning or f"A new approach to {idea}"

    # Build slides HTML
    slides_html = ""
    icon_map = {
        "rocket": _svg_rocket,
        "alert": _svg_alert,
        "cross": _svg_cross,
        "check": _svg_check,
        "trending": _svg_trending,
        "shield": _svg_shield,
        "chart": _svg_chart,
        "dollar": _svg_dollar,
    }

    for i, slide in enumerate(narrative.slides):
        active = "active" if i == 0 else ""
        icon_fn = icon_map.get(slide.icon, _svg_zap)
        icon_svg = icon_fn()

        # Build key points as list items with i18n (data-driven, no i18n needed for data)
        bullets = "".join(
            f'<li class="slide-bullet">{_esc(point)}</li>'
            for point in slide.key_points
        )

        # Slide image (if available)
        img_url = (image_urls[i] if image_urls and i < len(image_urls) and image_urls[i] else None)
        img_html = f'<div class="slide-image" style="background-image: url(\'{_esc(img_url)}\')" role="img" aria-label="Slide illustration"></div>' if img_url else ''

        slides_html += f"""
<section class="slide {active}" data-index="{i}" aria-label="Slide {i+1}: {_esc(slide.title)}">
  {img_html}
  <div class="slide-inner">
    <div class="slide-number">0{i+1}</div>
    <div class="slide-icon">{icon_svg}</div>
    <h2 class="slide-title">{_esc(slide.title)}</h2>
    <ul class="slide-bullets">{bullets}</ul>
    <div class="speaker-notes" aria-label="Speaker notes">
      <span class="lang-en">🎤 Speaker:</span>
      <span class="lang-es">🎤 Orador:</span>
      <span class="lang-de">🎤 Sprecher:</span>
      <em>{_esc(slide.speaker_notes[:300])}</em>
    </div>
    <div class="narrative-hook" aria-label="Narrative hook">
      <span class="lang-en">💡 Hook:</span>
      <span class="lang-es">💡 Gancho:</span>
      <span class="lang-de">💡 Aufhänger:</span>
      {_esc(slide.narrative_hook[:200])}
    </div>
  </div>
</section>"""

    # Narrative script as hidden markdown (for export)
    script_md = format_narrative_markdown(narrative)

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pitch Deck — {_esc(idea)}</title>
<meta name="description" content="{_esc(tagline[:160])}">
<meta name="robots" content="index, follow">
<meta property="og:title" content="Pitch Deck: {_esc(idea)}">
<meta property="og:description" content="{_esc(tagline[:160])}">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={{darkMode:'class',theme:{{extend:{{colors:{{primary:{{400:'#2dd4bf',500:'#14b8a6',600:'#0d9488'}}}},fontFamily:{{sans:['DM Sans','system-ui','sans-serif']}}}}}}}}</script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  /* ========================================
     DESIGN TOKENS — WCAG AA (OKLCH)
     ======================================== */
  :root {{
    --sf-primary: oklch(25% 0.10 185);
    --sf-on-primary: oklch(97% 0.003 185);
  }}
  .dark {{
    --sf-primary: oklch(72% 0.12 185);
    --sf-on-primary: oklch(8% 0.02 185);
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ font-size: 16px; scroll-behavior: smooth; }}
  body {{
    font-family: 'DM Sans', system-ui, sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }}
  body.light {{
    background: #f8fafc;
    color: #0f172a;
  }}

  /* Slide container */
  .slides-container {{
    height: 100vh;
    overflow-y: scroll;
    scroll-snap-type: y mandatory;
    scroll-behavior: smooth;
  }}

  /* Individual slide */
  .slide {{
    height: 100vh;
    scroll-snap-align: start;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 60px 40px;
    position: relative;
  }}
  .slide-inner {{
    max-width: 800px;
    width: 100%;
  }}
  .slide-number {{
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    color: #14b8a6;
    letter-spacing: 0.1em;
    margin-bottom: 16px;
  }}
  .slide-icon {{
    margin-bottom: 24px;
  }}
  .slide-icon svg {{
    width: 48px;
    height: 48px;
  }}
  .slide-title {{
    font-size: clamp(1.75rem, 3vw, 2.5rem);
    font-weight: 800;
    color: #fff;
    margin-bottom: 32px;
    letter-spacing: -0.02em;
  }}
  body.light .slide-title {{ color: #0f172a; }}
  .slide-bullets {{
    list-style: none;
    padding: 0;
  }}
  .slide-bullet {{
    font-size: 1.1rem;
    color: #cbd5e1;
    padding: 10px 0 10px 28px;
    position: relative;
    line-height: 1.6;
    max-width: 650px;
  }}
  body.light .slide-bullet {{ color: #334155; }}
  .slide-bullet::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 18px;
    width: 8px;
    height: 8px;
    background: #14b8a6;
    border-radius: 50%;
  }}

  /* Slide image */
  .slide-image {{
    position: absolute;
    top: 0;
    right: 0;
    width: 45%;
    height: 100%;
    background-size: cover;
    background-position: center;
    opacity: 0.3;
    mask-image: linear-gradient(to left, black 40%, transparent 100%);
    -webkit-mask-image: linear-gradient(to left, black 40%, transparent 100%);
    pointer-events: none;
    z-index: 0;
  }}
  body.light .slide-image {{ opacity: 0.15; }}
  .slide-inner {{ position: relative; z-index: 1; }}

  /* Speaker notes */
  .speaker-notes {{
    margin-top: 32px;
    padding-top: 20px;
    border-top: 1px solid #1e293b;
    font-size: 0.8rem;
    color: #64748b;
    line-height: 1.5;
    opacity: 0.6;
    transition: opacity 0.2s;
  }}
  .speaker-notes:hover {{ opacity: 1; }}
  body.light .speaker-notes {{ border-top-color: #e2e8f0; color: #94a3b8; }}
  .narrative-hook {{
    margin-top: 8px;
    font-size: 0.75rem;
    color: #14b8a6;
    opacity: 0.5;
    font-style: italic;
  }}

  /* Nav controls */
  .nav-bar {{
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    background: rgba(15,23,42,0.9);
    backdrop-filter: blur(12px);
    border-top: 1px solid #1e293b;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 12px 24px;
  }}
  body.light .nav-bar {{
    background: rgba(248,250,252,0.9);
    border-top-color: #e2e8f0;
  }}
  .nav-btn {{
    background: #1e293b;
    border: 1px solid #334155;
    color: #e2e8f0;
    padding: 8px 16px;
    border-radius: 8px;
    font-family: 'DM Sans', system-ui, sans-serif;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .nav-btn:hover {{ background: #334155; border-color: #14b8a6; }}
  body.light .nav-btn {{ background: #fff; border-color: #cbd5e1; color: #0f172a; }}
  body.light .nav-btn:hover {{ background: #f1f5f9; }}
  .slide-counter {{
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
    color: #64748b;
    min-width: 60px;
    text-align: center;
  }}
  .fullscreen-btn {{
    background: none;
    border: 1px solid #334155;
    color: #64748b;
    padding: 8px 12px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
  }}
  .fullscreen-btn:hover {{ border-color: #14b8a6; color: #14b8a6; }}

  /* Theme + i18n toggles */
  .top-bar {{
    position: fixed;
    top: 0;
    right: 0;
    z-index: 100;
    display: flex;
    gap: 8px;
    padding: 16px 24px;
  }}
  .top-btn {{
    background: rgba(30,41,59,0.8);
    border: 1px solid #334155;
    color: #94a3b8;
    padding: 6px 12px;
    border-radius: 8px;
    font-family: 'DM Sans', system-ui, sans-serif;
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.15s;
    backdrop-filter: blur(8px);
  }}
  .top-btn:hover {{ border-color: #14b8a6; color: #e2e8f0; }}

  /* i18n */
  [data-lang="es"] .lang-en, [data-lang="de"] .lang-en {{ display: none; }}
  [data-lang="en"] .lang-es, [data-lang="de"] .lang-es {{ display: none; }}
  [data-lang="en"] .lang-de, [data-lang="es"] .lang-de {{ display: none; }}

  /* Print / PDF */
  @media print {{
    body {{ overflow: visible; background: #fff; }}
    .slide {{ height: auto; min-height: 100vh; page-break-after: always; scroll-snap-align: none; }}
    .nav-bar, .top-bar {{ display: none; }}
    .speaker-notes {{ opacity: 1; display: block !important; }}
  }}

  @media (max-width: 640px) {{
    .slide {{ padding: 40px 20px; }}
    .slide-bullet {{ font-size: 0.95rem; }}
    .slide-title {{ font-size: 1.5rem; }}
  }}

  @media (prefers-reduced-motion: reduce) {{
    .slides-container {{ scroll-behavior: auto; }}
  }}
</style>
</head>
<body data-lang="en">
<div class="top-bar">
  <button class="top-btn" onclick="toggleTheme()" aria-label="Toggle theme">
    <span class="lang-en">🌓 Theme</span>
    <span class="lang-es">🌓 Tema</span>
    <span class="lang-de">🌓 Theme</span>
  </button>
  <select class="top-btn" onchange="setLang(this.value)" aria-label="Language" style="appearance:none;cursor:pointer;">
    <option value="en">EN</option>
    <option value="es">ES</option>
    <option value="de">DE</option>
  </select>
  <button class="top-btn" onclick="toggleFullscreen()" aria-label="Fullscreen">
    <span class="lang-en">⛶ Full</span>
    <span class="lang-es">⛶ Completa</span>
    <span class="lang-de">⛶ Vollbild</span>
  </button>
</div>

<div class="slides-container" id="slidesContainer">
  {slides_html}
</div>

<nav class="nav-bar" aria-label="Slide navigation">
  <button class="nav-btn" onclick="navigate(-1)" aria-label="Previous slide">← <span class="lang-en">Prev</span><span class="lang-es">Ant</span><span class="lang-de">Zurück</span></button>
  <span class="slide-counter" id="slideCounter">1 / {narrative.total_slides}</span>
  <button class="nav-btn" onclick="navigate(1)" aria-label="Next slide"><span class="lang-en">Next</span><span class="lang-es">Sig</span><span class="lang-de">Weiter</span> →</button>
  <button class="fullscreen-btn" onclick="window.print()" aria-label="Export PDF" title="Export to PDF">
    <span class="lang-en">📄 PDF</span>
    <span class="lang-es">📄 PDF</span>
    <span class="lang-de">📄 PDF</span>
  </button>
</nav>

<!-- Hidden narrative script for copy/paste -->
<textarea id="narrativeScript" style="display:none;" aria-hidden="true">{_esc(script_md[:5000])}</textarea>

<script>
(function() {{
  const container = document.getElementById('slidesContainer');
  const slides = container.querySelectorAll('.slide');
  const counter = document.getElementById('slideCounter');
  const totalSlides = slides.length;

  container.addEventListener('scroll', function() {{
    const index = Math.round(container.scrollTop / container.clientHeight);
    counter.textContent = (index + 1) + ' / ' + totalSlides;
  }});

  window.navigate = function(dir) {{
    const current = Math.round(container.scrollTop / container.clientHeight);
    const next = Math.max(0, Math.min(totalSlides - 1, current + dir));
    container.scrollTo({{ top: next * container.clientHeight, behavior: 'smooth' }});
  }};

  document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight' || e.key === 'PageDown') {{ e.preventDefault(); navigate(1); }}
    if (e.key === 'ArrowUp' || e.key === 'ArrowLeft' || e.key === 'PageUp') {{ e.preventDefault(); navigate(-1); }}
    if (e.key === 'Home') {{ e.preventDefault(); container.scrollTo({{ top: 0, behavior: 'smooth' }}); }}
    if (e.key === 'End') {{ e.preventDefault(); container.scrollTo({{ top: (totalSlides - 1) * container.clientHeight, behavior: 'smooth' }}); }}
    if (e.key === 'f' && !e.ctrlKey && !e.metaKey) {{ e.preventDefault(); toggleFullscreen(); }}
  }});

  // Touch support
  var touchStartY = 0;
  container.addEventListener('touchstart', function(e) {{ touchStartY = e.touches[0].clientY; }});
  container.addEventListener('touchend', function(e) {{
    var diff = touchStartY - e.changedTouches[0].clientY;
    if (Math.abs(diff) > 50) navigate(diff > 0 ? 1 : -1);
  }});

  // Theme
  window.toggleTheme = function() {{
    document.body.classList.toggle('light');
    localStorage.setItem('pitch_theme', document.body.classList.contains('light') ? 'light' : 'dark');
  }};
  if (localStorage.getItem('pitch_theme') === 'light') document.body.classList.add('light');

  // Fullscreen
  window.toggleFullscreen = function() {{
    if (!document.fullscreenElement) {{
      document.documentElement.requestFullscreen().catch(function() {{}});
    }} else {{
      document.exitFullscreen();
    }}
  }};

  // i18n
  window.setLang = function(l) {{
    document.body.setAttribute('data-lang', l);
    localStorage.setItem('pitch_lang', l);
  }};
  setLang(localStorage.getItem('pitch_lang') || 'en');
}})();
</script>
</body>
</html>"""


# ── SVG Icons ─────────────────────────────────────

def _svg_rocket() -> str:
    return '<svg class="text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z"/></svg>'


def _svg_alert() -> str:
    return '<svg class="text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>'


def _svg_cross() -> str:
    return '<svg class="text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M18.364 5.636l-12.728 12.728M5.636 5.636l12.728 12.728"/></svg>'


def _svg_check() -> str:
    return '<svg class="text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'


def _svg_trending() -> str:
    return '<svg class="text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>'


def _svg_shield() -> str:
    return '<svg class="text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/></svg>'


def _svg_chart() -> str:
    return '<svg class="text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/></svg>'


def _svg_dollar() -> str:
    return '<svg class="text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'


def _svg_zap() -> str:
    return '<svg class="text-teal-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>'
