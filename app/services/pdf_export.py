"""PDF Export Service — professional editorial PDF generation.

TASK-054: Generates investment-grade PDFs with:
- Editorial layout (cover page, TOC, headers/footers, page numbers)
- Watermark support (CONFIDENTIAL / DRAFT)
- Brand customization (colors, logo, fonts)
- Async generation with signed download URLs
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..utils.paths import GENERATED_DIR, make_output_dir

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────

PDF_SECRET = os.getenv("PDF_SIGNING_SECRET", "pdf-dev-secret-change-in-prod")
PDF_EXPIRY_HOURS = int(os.getenv("PDF_EXPIRY_HOURS", "24"))

# ── Editorial HTML Template ────────────────────────────

EDITORIAL_CSS = """
@page {
    size: A4;
    margin: 25mm 20mm 30mm 20mm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 8pt;
        color: #94a3b8;
    }
    @top-right {
        content: "{brand_name}";
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 7pt;
        color: #94a3b8;
    }
}

@page cover {
    margin: 0;
    @bottom-center { content: none; }
    @top-right { content: none; }
}

@page toc {
    @bottom-center { content: none; }
}

body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.6;
    color: {text_color};
    counter-reset: section;
}

/* ── Cover Page ── */
.cover-page {
    page: cover;
    page-break-after: always;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    height: 297mm;
    background: linear-gradient(135deg, {primary_color} 0%, {secondary_color} 100%);
    color: white;
    padding: 40mm;
}

.cover-page h1 {
    font-size: 28pt;
    font-weight: 700;
    margin-bottom: 12pt;
    letter-spacing: -0.5pt;
}

.cover-page .subtitle {
    font-size: 14pt;
    opacity: 0.9;
    margin-bottom: 24pt;
}

.cover-page .meta {
    font-size: 9pt;
    opacity: 0.7;
    margin-top: 12pt;
}

.cover-page .watermark-cover {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(-30deg);
    font-size: 48pt;
    font-weight: 900;
    opacity: 0.08;
    color: white;
    letter-spacing: 8pt;
}

/* ── Table of Contents ── */
.toc-page {
    page: toc;
    page-break-after: always;
}

.toc-page h2 {
    font-size: 18pt;
    font-weight: 700;
    color: {primary_color};
    margin-bottom: 16pt;
    padding-bottom: 8pt;
    border-bottom: 2px solid {primary_color};
}

.toc-item {
    display: flex;
    justify-content: space-between;
    padding: 6pt 0;
    border-bottom: 1px dotted #e2e8f0;
    font-size: 10pt;
}

.toc-item .title { color: {text_color}; }
.toc-item .page { color: #94a3b8; font-variant-numeric: tabular-nums; }

/* ── Section Headers ── */
h2.section {
    font-size: 16pt;
    font-weight: 700;
    color: {primary_color};
    margin-top: 20pt;
    margin-bottom: 10pt;
    padding-bottom: 6pt;
    border-bottom: 2px solid {primary_color};
    counter-increment: section;
}

h2.section::before {
    content: counter(section) ". ";
}

h3 {
    font-size: 12pt;
    font-weight: 600;
    color: {secondary_color};
    margin-top: 14pt;
    margin-bottom: 6pt;
}

/* ── Content ── */
p {
    margin-bottom: 6pt;
    text-align: justify;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0;
    font-size: 9pt;
}

table th {
    background-color: {primary_color};
    color: white;
    padding: 6pt 8pt;
    text-align: left;
    font-weight: 600;
}

table td {
    padding: 5pt 8pt;
    border-bottom: 1px solid #e2e8f0;
}

table tr:nth-child(even) td {
    background-color: #f8fafc;
}

ul, ol {
    margin-bottom: 6pt;
    padding-left: 18pt;
}

li {
    margin-bottom: 3pt;
}

code {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 8pt;
    background-color: #f1f5f9;
    padding: 1pt 4pt;
    border-radius: 2pt;
}

pre {
    background-color: #1e293b;
    color: #e2e8f0;
    padding: 8pt 12pt;
    border-radius: 4pt;
    font-size: 7.5pt;
    line-height: 1.4;
    overflow-x: auto;
    margin: 8pt 0;
}

.page-break {
    page-break-before: always;
}

/* ── Badges ── */
.badge {
    display: inline-block;
    padding: 2pt 6pt;
    border-radius: 3pt;
    font-size: 7pt;
    font-weight: 600;
    text-transform: uppercase;
}

.badge-p0 { background-color: #fef2f2; color: #dc2626; }
.badge-p1 { background-color: #fffbeb; color: #d97706; }
.badge-p2 { background-color: #f0fdf4; color: #16a34a; }

/* ── Watermark (body pages) ── */
.watermark-body {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(-30deg);
    font-size: 96pt;
    font-weight: 900;
    opacity: 0.04;
    color: {watermark_color};
    pointer-events: none;
    z-index: -1;
    letter-spacing: 12pt;
}

/* ── Stats cards ── */
.stats-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 8pt;
    margin: 10pt 0;
}

.stat-card {
    flex: 1;
    min-width: 100pt;
    padding: 10pt;
    background-color: #f8fafc;
    border-radius: 4pt;
    text-align: center;
    border-left: 3px solid {primary_color};
}

.stat-card .value {
    font-size: 16pt;
    font-weight: 700;
    color: {primary_color};
}

.stat-card .label {
    font-size: 7pt;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
}

/* ── Footer section ── */
.footer-note {
    margin-top: 20pt;
    padding-top: 10pt;
    border-top: 1px solid #e2e8f0;
    font-size: 7.5pt;
    color: #94a3b8;
    text-align: center;
}
"""


def _build_cover_html(title: str, subtitle: str, watermark: str = "", brand: dict = None) -> str:
    """Build the cover page HTML."""
    wm = watermark.strip().upper()
    wm_html = f'<div class="watermark-cover">{wm}</div>' if wm else ""
    meta = brand or {}
    date = datetime.now().strftime("%B %d, %Y")
    return f"""
<div class="cover-page">
    {wm_html}
    <h1>{_esc(title)}</h1>
    <div class="subtitle">{_esc(subtitle)}</div>
    <div class="meta">
        Generated by PitchForge · {date}
        {f' · {meta.get("company", "")}' if meta.get("company") else ''}
    </div>
</div>"""


def _build_toc_html(sections: list[dict]) -> str:
    """Build table of contents from section list."""
    items = "\n".join(
        f'<div class="toc-item"><span class="title">{_esc(s["title"])}</span><span class="page">{s.get("page", "")}</span></div>'
        for s in sections
    )
    return f"""
<div class="toc-page">
    <h2>Table of Contents</h2>
    {items}
</div>"""


def _build_watermark_html(text: str) -> str:
    """Build watermark overlay for body pages."""
    if not text:
        return ""
    return f'<div class="watermark-body">{_esc(text.upper())}</div>'


def _esc(text: str) -> str:
    """HTML-escape a string."""
    if not text:
        return ""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))


# ── PDF Generator ──────────────────────────────────────

def generate_pdf(
    html_content: str,
    title: str = "Document",
    subtitle: str = "",
    watermark: str = "",
    brand: Optional[dict] = None,
    output_dir: Optional[Path] = None,
    filename: str = "document.pdf",
) -> Optional[Path]:
    """Generate a professional PDF from HTML content.

    Args:
        html_content: Raw HTML body content (without full document wrapper).
        title: Document title for cover page.
        subtitle: Subtitle for cover page.
        watermark: 'CONFIDENTIAL', 'DRAFT', or empty for none.
        brand: Dict with primary_color, secondary_color, text_color,
               watermark_color, brand_name, company, logo_url.
        output_dir: Directory to save PDF. Auto-creates if None.
        filename: Output filename (must end in .pdf).

    Returns:
        Path to generated PDF, or None if generation failed.
    """
    try:
        import weasyprint
    except ImportError:
        logger.warning("weasyprint not installed. Install with: pip install weasyprint")
        return None

    brand = brand or {}
    primary = brand.get("primary_color", "#0d9488")  # teal-600
    secondary = brand.get("secondary_color", "#155e75")  # teal-800
    text_color = brand.get("text_color", "#1e293b")
    wm_color = brand.get("watermark_color", "#dc2626")  # red for confidential
    brand_name = brand.get("brand_name", "PitchForge")

    # Build full HTML document
    css = EDITORIAL_CSS.format(
        primary_color=primary,
        secondary_color=secondary,
        text_color=text_color,
        watermark_color=wm_color,
        brand_name=_esc(brand_name),
    )

    # Build sections for TOC (auto-detect from h2.section elements)
    sections = []

    # Cover + watermark
    cover = _build_cover_html(title, subtitle, watermark, brand)
    wm_body = _build_watermark_html(watermark)

    # Full HTML
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_esc(title)}</title>
<style>{css}</style>
</head>
<body>
{cover}
{wm_body}
<div class="content">
{html_content}
</div>
</body>
</html>"""

    # Generate PDF
    out_dir = output_dir or Path("/tmp/pitchforge-pdf")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / filename

    try:
        doc = weasyprint.HTML(string=full_html)
        doc.write_pdf(str(pdf_path))
        logger.info(f"✅ PDF generated: {pdf_path} ({pdf_path.stat().st_size / 1024:.0f} KB)")
        return pdf_path
    except Exception as e:
        logger.error(f"❌ PDF generation failed: {e}")
        return None


# ── Signed URL Generation ──────────────────────────────

def generate_signed_url(project_id: str, doc_type: str, expires_hours: int = PDF_EXPIRY_HOURS) -> str:
    """Generate a signed temporary URL for PDF download.

    Uses HMAC-SHA256 signing to prevent unauthorized access.
    """
    expires_at = int(time.time()) + (expires_hours * 3600)
    payload = f"{project_id}:{doc_type}:{expires_at}"
    signature = hmac.new(
        PDF_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]

    return f"/api/pdf/download/{project_id}/{doc_type}?expires={expires_at}&sig={signature}"


def verify_signed_url(project_id: str, doc_type: str, expires_at: int, signature: str) -> bool:
    """Verify a signed PDF download URL."""
    # Check expiry
    if time.time() > expires_at:
        logger.warning(f"PDF URL expired: {project_id}/{doc_type}")
        return False

    # Verify signature
    expected = hmac.new(
        PDF_SECRET.encode(),
        f"{project_id}:{doc_type}:{expires_at}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]

    if not hmac.compare_digest(expected, signature):
        logger.warning(f"Invalid PDF signature: {project_id}/{doc_type}")
        return False

    return True


# ── Content Builders ───────────────────────────────────

def build_pitch_deck_html(report_json: dict) -> str:
    """Convert research report JSON into editorial pitch deck HTML."""
    parts = []
    idea = report_json.get("idea", "Startup")
    summary = report_json.get("summary", "")

    parts.append(f'<h2 class="section">Executive Summary</h2>')
    parts.append(f"<p>{_esc(summary)}</p>" if summary else "")

    # Competitors
    competitors = report_json.get("competitors", [])
    if competitors:
        parts.append(f'<h2 class="section">Competitive Landscape</h2>')
        parts.append(f"<p>Analysis of {len(competitors)} competitors in this space.</p>")
        parts.append('<div class="stats-grid">')
        parts.append(f'<div class="stat-card"><div class="value">{len(competitors)}</div><div class="label">Competitors</div></div>')
        gaps = report_json.get("opportunity_gaps", [])
        parts.append(f'<div class="stat-card"><div class="value">{len(gaps)}</div><div class="label">Opportunity Gaps</div></div>')
        features = report_json.get("recommended_mvp_features", [])
        parts.append(f'<div class="stat-card"><div class="value">{len(features)}</div><div class="label">MVP Features</div></div>')
        risks = report_json.get("risk_factors", [])
        parts.append(f'<div class="stat-card"><div class="value">{len(risks)}</div><div class="label">Risk Factors</div></div>')
        parts.append("</div>")

        parts.append('<table><thead><tr><th>Competitor</th><th>Model</th><th>Target</th><th>Pricing</th></tr></thead><tbody>')
        for c in competitors[:8]:
            name = _esc(c.get("name", ""))
            model = _esc(c.get("business_model", "-"))
            target = _esc(c.get("target_market", "-"))
            pricing = _esc(c.get("pricing", "-"))
            parts.append(f"<tr><td>{name}</td><td>{model}</td><td>{target}</td><td>{pricing}</td></tr>")
        parts.append("</tbody></table>")

    # Market Validation
    mv = report_json.get("market_validation", {})
    if mv:
        parts.append(f'<h2 class="section">Market Validation</h2>')
        parts.append('<div class="stats-grid">')
        parts.append(f'<div class="stat-card"><div class="value">{mv.get("reddit_posts_found", 0)}</div><div class="label">Reddit Posts</div></div>')
        parts.append(f'<div class="stat-card"><div class="value">{mv.get("hn_mentions", 0)}</div><div class="label">HN Mentions</div></div>')
        parts.append(f'<div class="stat-card"><div class="value">{mv.get("gh_similar_projects", 0)}</div><div class="label">GitHub Projects</div></div>')
        parts.append("</div>")

        complaints = mv.get("common_complaints", [])
        if complaints:
            parts.append(f"<h3>Common Complaints</h3><ul>" + "".join(f"<li>{_esc(c)}</li>" for c in complaints[:5]) + "</ul>")

    # MVP Features
    if features:
        parts.append(f'<h2 class="section">Recommended MVP Features</h2>')
        parts.append("<ol>" + "".join(f"<li>{_esc(f)}</li>" for f in features) + "</ol>")

    # Risk Factors
    if risks:
        parts.append(f'<h2 class="section">Risk Factors</h2>')
        parts.append("<ul>" + "".join(f"<li>{_esc(r)}</li>" for r in risks) + "</ul>")

    parts.append('<div class="footer-note">This document was generated by PitchForge based on real-time market research and competitive analysis.</div>')
    return "\n".join(parts)


def build_planning_report_html(planning_data: dict) -> str:
    """Convert planning output into editorial report HTML."""
    parts = []
    idea = planning_data.get("idea", "Project")
    prd = planning_data.get("prd", {})
    functional = planning_data.get("functional", {})
    financial = planning_data.get("financial", {})
    technical = planning_data.get("technical", {})

    # PRD
    if prd:
        parts.append(f'<h2 class="section">Product Requirements Document</h2>')
        parts.append(f"<p><strong>Product:</strong> {_esc(prd.get('product_name', ''))}</p>")
        parts.append(f"<p><strong>Tagline:</strong> {_esc(prd.get('tagline', ''))}</p>")
        parts.append(f"<p><strong>Problem:</strong> {_esc(prd.get('problem_statement', ''))}</p>")
        stories = prd.get("user_stories", [])
        if stories:
            parts.append("<h3>User Stories</h3><ul>" + "".join(f"<li>{_esc(s)}</li>" for s in stories[:6]) + "</ul>")

    # Functional
    if functional:
        parts.append(f'<h2 class="section">Functional Specification</h2>')
        features = functional.get("core_features", [])
        if features:
            parts.append("<table><thead><tr><th>ID</th><th>Feature</th><th>Priority</th><th>Effort</th></tr></thead><tbody>")
            for f in features[:10]:
                fid = _esc(f.get("id", ""))
                name = _esc(f.get("name", ""))
                prio = f.get("priority", "P1")
                badge_class = {"P0": "badge-p0", "P1": "badge-p1", "P2": "badge-p2"}.get(prio, "badge-p1")
                effort = _esc(f.get("effort", ""))
                parts.append(f"<tr><td>{fid}</td><td>{name}</td><td><span class='badge {badge_class}'>{prio}</span></td><td>{effort}</td></tr>")
            parts.append("</tbody></table>")

    # Financial
    if financial:
        parts.append(f'<h2 class="section">Financial Model</h2>')
        summary = financial.get("executive_summary", "")
        if summary:
            parts.append(f"<p>{_esc(summary)}</p>")
        tiers = financial.get("pricing_tiers", [])
        if tiers:
            parts.append("<table><thead><tr><th>Tier</th><th>Monthly</th><th>Yearly</th><th>Description</th></tr></thead><tbody>")
            for t in tiers:
                name = _esc(t.get("name", ""))
                monthly = f"${t.get('price_monthly', 0):.0f}" if t.get("price_monthly") is not None else "Free"
                yearly = f"${t.get('price_yearly', 0):.0f}" if t.get("price_yearly") is not None else "-"
                desc = _esc(t.get("description", ""))
                parts.append(f"<tr><td>{name}</td><td>{monthly}</td><td>{yearly}</td><td>{desc}</td></tr>")
            parts.append("</tbody></table>")

    # Technical
    if technical:
        parts.append(f'<h2 class="section">Technical Specification</h2>')
        stack = technical.get("stack_table", [])
        if stack:
            parts.append("<table><thead><tr><th>Layer</th><th>Technology</th></tr></thead><tbody>")
            for s in stack[:8]:
                layer = _esc(s.get("layer", ""))
                tech = _esc(s.get("technology", ""))
                parts.append(f"<tr><td>{layer}</td><td>{tech}</td></tr>")
            parts.append("</tbody></table>")

    parts.append('<div class="footer-note">Generated by PitchForge Planning Pipeline</div>')
    return "\n".join(parts)


def build_landing_html(landing_html: str) -> str:
    """Extract content from a landing page HTML for PDF."""
    return landing_html  # Use the full HTML as-is
