"""Shared HTML utilities — centralized _esc(), theme toggle, i18n switcher, schema builder.

Used by landing.py, pitch.py, and pricing.py generators.
"""


def esc_html(text: str) -> str:
    """HTML-escape text. Safe for None."""
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;"))


def theme_toggle_html() -> str:
    """Theme toggle button HTML (dark/light/system)."""
    return """<button class="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition" aria-label="Toggle theme" data-theme-toggle>
      <svg class="w-5 h-5 text-slate-600 dark:text-slate-300 block dark:hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>
      <svg class="w-5 h-5 text-slate-600 dark:text-slate-300 hidden dark:block" fill="currentColor" viewBox="0 0 24 24"><path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
    </button>"""


def i18n_switcher_html() -> str:
    """Language switcher HTML (EN/ES/DE)."""
    return """<div class="relative" data-lang-switch>
      <button class="flex items-center gap-1.5 px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition text-sm text-slate-600 dark:text-slate-300" aria-label="Switch language" data-lang-toggle>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064"/></svg>
        <span data-lang-label>EN</span>
      </button>
      <div class="absolute right-0 mt-2 w-28 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-lg hidden z-50" data-lang-menu>
        <button class="w-full text-left px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 rounded-t-xl transition" data-lang="en">English</button>
        <button class="w-full text-left px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 rounded-b-xl transition" data-lang="es">Espanol</button>
        <button class="w-full text-left px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 rounded-b-xl transition" data-lang="de">Deutsch</button>
      </div>
    </div>"""


def schema_org_html(idea: str, tagline: str) -> str:
    """Build Schema.org JSON-LD for a SoftwareApplication."""
    return f"""<script type="application/ld+json">
[{{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "{esc_html(idea[:80])}",
  "description": "{esc_html(tagline[:200])}",
  "applicationCategory": "BusinessApplication",
  "operatingSystem": "All",
  "offers": {{
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  }}
}}]
</script>"""
