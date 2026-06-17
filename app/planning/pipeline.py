"""Planning Pipeline — orchestrates PRD → Functional → Financial → Technical generation.

Runs all 4 specs sequentially against the research report, then produces
structured JSON + markdown report + HTML dashboard.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.research.models import ResearchReport

from .models import PlanningOutput
from .prd import generate_prd
from .functional import generate_functional
from .financial import generate_financial
from .technical import generate_technical

from .codegen import CodegenPipeline
from .document_catalog import resolve_documents, get_document_label

logger = logging.getLogger(__name__)


class PlanningPipeline:
    """Orchestrates the full planning pipeline."""

    def __init__(self):
        self.start_time: float = 0.0

    async def run(self, report: ResearchReport, documents: list[str] | None = None, use_llm: bool = True) -> PlanningOutput:
        """Run generators for selected documents and return combined output.

        TASK-065: documents param controls which docs to generate.
        None or ['all'] → all 4 core specs.
        Specific list → only those selected.
        """
        self.start_time = time.monotonic()
        idea = report.idea
        selected = set(resolve_documents(documents))

        logger.info(f"📋 Planning pipeline started for: {idea}")
        logger.info(f"   Selected documents: {len(selected)} ({', '.join(sorted(selected)[:10])}...)" if len(selected) > 10 else f"   Selected documents: {', '.join(sorted(selected))}")

        # Phase 1: PRD
        prd = None
        if "prd" in selected:
            logger.info("  Phase: PRD...")
            prd = await generate_prd(report, use_llm=use_llm)
            logger.info(f"  ✅ PRD: {prd.product_name or 'generated'}")
        else:
            prd = PRDSpec()

        # Phase 2: Functional
        functional = None
        if "memoria_funcional" in selected:
            logger.info("  Phase: Functional Spec...")
            functional = await generate_functional(report, use_llm=use_llm)
            logger.info(f"  ✅ Functional: {len(functional.core_features)} features")
        else:
            functional = FunctionalSpec()

        # Phase 3: Financial
        financial = None
        if "pricing" in selected:
            logger.info("  Phase: Financial Model...")
            financial = await generate_financial(report, use_llm=use_llm)
            logger.info(f"  ✅ Financial: {len(financial.pricing_tiers)} tiers")
        else:
            financial = FinancialModel()

        # Phase 4: Technical
        technical = None
        if "memoria_tecnica" in selected:
            logger.info("  Phase: Technical Spec...")
            technical = await generate_technical(report, use_llm=use_llm)
            logger.info(f"  ✅ Technical: {len(technical.stack_table)} stack layers")
        else:
            technical = TechnicalSpec()

        # TASK-065 — New documents (generated as structured JSON via LLM)
        # Skip extra doc generation when use_llm=false (would be slow + requires LLM)
        extra_docs = {}
        if not use_llm:
            logger.info("  Skipping extra docs (use_llm=false)")
            new_doc_ids = set()
        else:
            new_doc_ids = selected - {"prd", "memoria_funcional", "pricing", "memoria_tecnica"}
        for doc_id in sorted(new_doc_ids):
            label = get_document_label(doc_id)
            logger.info(f"  Generating: {label} ({doc_id})...")
            try:
                from .document_generators import generate_document
                doc_content = await generate_document(report, doc_id)
                extra_docs[doc_id] = doc_content
                logger.info(f"  ✅ {label}")
            except Exception as e:
                logger.warning(f"  ⚠️ Failed to generate {label}: {e}")
                extra_docs[doc_id] = {"error": str(e), "label": label}

        duration_ms = int((time.monotonic() - self.start_time) * 1000)

        output = PlanningOutput(
            idea=idea,
            research_summary=report.summary or "",
            prd=prd,
            functional=functional,
            financial=financial,
            technical=technical,
            extra_docs=extra_docs,
            generated_at=datetime.utcnow(),
            generation_duration_ms=duration_ms,
        )

        logger.info(f"✅ Planning pipeline complete in {duration_ms}ms ({len(extra_docs)} extra docs)")
        return output

    async def run_and_save(
        self,
        report: ResearchReport,
        output_dir: str,
        generate_code: bool = False,
        documents: list[str] | None = None,
        use_llm: bool = True,
    ) -> dict:
        """Run pipeline and save JSON + markdown + HTML. Optionally generate code.
        
        TASK-065: documents param selects which docs to generate.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        output = await self.run(report, documents=documents, use_llm=use_llm)

        # 1. JSON
        json_path = out / "planning_report.json"
        json_path.write_text(
            json.dumps(output.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )

        # 1.5 Extra docs — save each to its own JSON file (TASK-065)
        docs_dir = out / "documents"
        docs_dir.mkdir(exist_ok=True)
        for doc_id, content in output.extra_docs.items():
            doc_path = docs_dir / f"{doc_id}.json"
            doc_path.write_text(json.dumps(content, indent=2, ensure_ascii=False))
            logger.info(f"  📄 Saved: {doc_id}.json")

        # 2. Markdown
        md_path = out / "planning_report.md"
        md_path.write_text(planning_to_markdown(output))

        # 3. HTML Dashboard
        html_path = out / "planning_dashboard.html"
        html_path.write_text(planning_to_html(output))

        # 4. Codegen (optional)
        codegen_result = None
        if generate_code:
            logger.info("  Generating MVP code...")
            try:
                cp = CodegenPipeline()
                codegen_result = await cp.run(output, str(out / "generated"))
                logger.info(f"  ✅ Codegen: {codegen_result['total_files']} files")
            except Exception as e:
                logger.error(f"Codegen failed: {e}")
                codegen_result = {"error": str(e)}

        return {
            "json": str(json_path),
            "markdown": str(md_path),
            "html": str(html_path),
            "duration_ms": output.generation_duration_ms,
            "codegen": codegen_result,
        }


# ─── Markdown Renderer ─────────────────────────────────

def planning_to_markdown(output: PlanningOutput) -> str:
    """Convert PlanningOutput to readable markdown."""
    lines = []

    # Header
    lines.append(f"# Planning Report: {output.idea}")
    lines.append("")
    lines.append(f"**Generated:** {output.generated_at.isoformat()}")
    lines.append(f"**Duration:** {output.generation_duration_ms}ms")
    lines.append("")
    if output.research_summary:
        lines.append(f"> {output.research_summary}")
        lines.append("")

    prd = output.prd
    func = output.functional
    fin = output.financial
    tech = output.technical

    # ── 1. PRD ──
    lines.append("---")
    lines.append("# 📋 1. Product Requirements Document")
    lines.append("")
    if prd.product_name:
        lines.append(f"**Product:** {prd.product_name}")
    if prd.tagline:
        lines.append(f"**Tagline:** {prd.tagline}")
    if prd.problem_statement:
        lines.append(f"**Problem:** {prd.problem_statement}")
    if prd.proposed_solution:
        lines.append(f"**Solution:** {prd.proposed_solution}")
    lines.append("")

    if prd.target_audience:
        lines.append("## Target Audience")
        for seg in prd.target_audience:
            name = seg.get("segment", "Unknown")
            pain = seg.get("pain", "")
            size = seg.get("size", "")
            lines.append(f"- **{name}** — {pain}" + (f" ({size})" if size else ""))
        lines.append("")

    if prd.user_stories:
        lines.append("## User Stories")
        for s in prd.user_stories:
            lines.append(f"- {s}")
        lines.append("")

    if prd.success_criteria:
        lines.append("## Success Criteria (KPIs)")
        for c in prd.success_criteria:
            lines.append(f"- {c}")
        lines.append("")

    if prd.risks:
        lines.append("## Risks & Mitigations")
        for r in prd.risks:
            risk = r.get("risk", "")
            impact = r.get("impact", "medium")
            mit = r.get("mitigation", "")
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "🟡")
            lines.append(f"- {icon} **{risk}** (impact: {impact})")
            if mit:
                lines.append(f"  - Mitigation: {mit}")
        lines.append("")

    # ── 2. Functional ──
    lines.append("---")
    lines.append("# 🎯 2. Functional Specification")
    lines.append("")

    if func.user_personas:
        lines.append("## User Personas")
        for p in func.user_personas:
            name = p.get("name", "Persona")
            role = p.get("role", "")
            goals = p.get("goals", [])
            pains = p.get("pain_points", [])
            lines.append(f"### {name} ({role})")
            if goals:
                lines.append("**Goals:** " + ", ".join(goals[:3]))
            if pains:
                lines.append("**Pain Points:** " + ", ".join(pains[:3]))
            lines.append("")

    if func.core_features:
        lines.append("## Core Features")
        priorities = {"P0": "🔴", "P1": "🟡", "P2": "🟢"}
        for f in func.core_features:
            fid = f.get("id", "")
            name = f.get("name", "")
            desc = f.get("description", "")
            prio = f.get("priority", "P1")
            effort = f.get("effort", "medium")
            icon = priorities.get(prio, "🟡")
            lines.append(f"- {icon} **{fid}: {name}** [{prio}, {effort}]")
            if desc:
                lines.append(f"  {desc}")
        lines.append("")

    if func.user_journeys:
        lines.append("## User Journeys")
        for j in func.user_journeys:
            scenario = j.get("scenario", "Flow")
            steps = j.get("steps", [])
            lines.append(f"### {scenario}")
            for i, step in enumerate(steps, 1):
                lines.append(f"  {i}. {step}")
            lines.append("")

    if func.ui_principles:
        lines.append("## UI Principles")
        for p in func.ui_principles:
            lines.append(f"- {p}")
        lines.append("")

    # ── 3. Financial ──
    lines.append("---")
    lines.append("# 💰 3. Financial Model")
    lines.append("")

    if fin.executive_summary:
        lines.append(fin.executive_summary)
        lines.append("")

    if fin.pricing_tiers:
        lines.append("## Pricing Tiers")
        for t in fin.pricing_tiers:
            monthly = f"${t.price_monthly:.0f}/mo" if t.price_monthly is not None else "Free"
            yearly = f"${t.price_yearly:.0f}/yr" if t.price_yearly is not None else ""
            lines.append(f"- **{t.name}**: {monthly} {yearly} — {t.description}")
            for f in t.features:
                lines.append(f"  - {f}")
        lines.append("")

    if fin.unit_economics:
        lines.append("## Unit Economics")
        ue = fin.unit_economics
        for key in ["cac", "ltv", "ltv_cac_ratio", "gross_margin_pct", "monthly_churn_pct", "payback_period_months"]:
            if key in ue and ue[key] is not None:
                label = key.replace("_", " ").title()
                value = ue[key]
                suffix = "%" if "pct" in key else ("mo" if "period" in key else ("x" if "ratio" in key else "$" if key in ("cac", "ltv") else ""))
                lines.append(f"- **{label}**: ${value}{suffix}" if "$" in str(value) and "ratio" not in key else f"- **{label}**: {value}{suffix}")
        lines.append("")

    if fin.revenue_projection:
        lines.append("## Revenue Projection (12 months)")
        lines.append("| Month | Users | MRR | Expenses | Profit | Cumulative |")
        lines.append("|-------|-------|-----|----------|--------|------------|")
        for r in fin.revenue_projection:
            m = r.get("month", 0)
            u = r.get("users", 0)
            mrr = r.get("mrr", 0)
            exp = r.get("expenses", 0)
            profit = r.get("profit", 0)
            cum = r.get("cumulative_profit", 0)
            lines.append(f"| {m} | {u} | ${mrr:.0f} | ${exp:.0f} | ${profit:.0f} | ${cum:.0f} |")
        lines.append("")

    if fin.break_even_month:
        lines.append(f"**Break-even:** Month {fin.break_even_month} (~{fin.break_even_users or '?'} users)")
        lines.append("")

    # ── 4. Technical ──
    lines.append("---")
    lines.append("# 🛠️ 4. Technical Specification")
    lines.append("")

    if tech.stack_recommendation:
        lines.append(f"**Stack:** {tech.stack_recommendation}")
        lines.append("")

    if tech.stack_table:
        lines.append("## Technology Stack")
        for s in tech.stack_table:
            layer = s.get("layer", "")
            tech_name = s.get("technology", "")
            rationale = s.get("rationale", "")
            lines.append(f"- **{layer}**: {tech_name} — {rationale}")
        lines.append("")

    if tech.data_model:
        lines.append("## Data Model")
        for entity in tech.data_model:
            e_name = entity.get("entity", "")
            fields = entity.get("fields", [])
            relations = entity.get("relations", [])
            lines.append(f"### {e_name}")
            for f in fields:
                fname = f.get("name", "")
                ftype = f.get("type", "")
                notes = f.get("notes", "")
                lines.append(f"- `{fname}`: {ftype}" + (f" — {notes}" if notes else ""))
            for r in relations:
                lines.append(f"- *{r}*")
            lines.append("")

    if tech.api_endpoints:
        lines.append("## API Endpoints")
        for ep in tech.api_endpoints:
            method = ep.get("method", "GET")
            path = ep.get("path", "/")
            desc = ep.get("description", "")
            auth = ep.get("auth", "public")
            lines.append(f"- **{method}** `{path}` — {desc} ({auth})")
        lines.append("")

    if tech.development_phases:
        lines.append("## Development Phases")
        for phase in tech.development_phases:
            pname = phase.get("phase", "")
            tasks = phase.get("tasks", [])
            duration = phase.get("duration", "")
            lines.append(f"### {pname} ({duration})")
            for t in tasks:
                lines.append(f"- {t}")
            lines.append("")

    if tech.estimated_effort:
        lines.append(f"**Estimated Effort:** {tech.estimated_effort}")
    if tech.estimated_infra_cost_monthly:
        lines.append(f"**Estimated Infra Cost:** ${tech.estimated_infra_cost_monthly:.0f}/month")

    lines.append("")
    lines.append("---")
    lines.append("*Generated by PitchForge Planning Pipeline*")
    lines.append(f"*{output.generated_at.isoformat()}*")

    return "\n".join(lines)


# ─── HTML Dashboard ────────────────────────────────────

def planning_to_html(output: PlanningOutput) -> str:
    """Generate a complete HTML dashboard showing all 4 planning specs."""
    prd = output.prd
    func = output.functional
    fin = output.financial
    tech = output.technical

    def esc(t):
        """Escape HTML and handle None."""
        if t is None:
            return ""
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def risk_icon(impact):
        return {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "🟡")

    def prio_icon(p):
        return {"P0": "🔴", "P1": "🟡", "P2": "🟢"}.get(p, "🟡")

    # Build PRD section
    prd_html = f"""<section id="prd" class="mb-16">
      <h2 class="text-3xl font-bold text-white mb-2">📋 Product Requirements Document</h2>
      <p class="text-slate-400 mb-8">{esc(prd.tagline)}</p>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div class="bg-slate-800 rounded-xl p-6">
          <h3 class="text-lg font-semibold text-teal-400 mb-3">Problem Statement</h3>
          <p class="text-slate-300">{esc(prd.problem_statement)}</p>
        </div>
        <div class="bg-slate-800 rounded-xl p-6">
          <h3 class="text-lg font-semibold text-teal-400 mb-3">Proposed Solution</h3>
          <p class="text-slate-300">{esc(prd.proposed_solution)}</p>
        </div>
      </div>"""

    if prd.target_audience:
        prd_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">🎯 Target Audience</h3>
      <div class="space-y-3">"""
        for seg in prd.target_audience:
            name = esc(seg.get("segment", "Unknown"))
            pain = esc(seg.get("pain", ""))
            size = esc(seg.get("size", ""))
            size_html = f'<p class="text-xs text-slate-500 mt-1">Size: {size}</p>' if size else ""
            prd_html += f'<div class="bg-slate-700 rounded-lg p-4"><p class="font-medium text-white">{name}</p><p class="text-sm text-slate-400">{pain}</p>{size_html}</div>'
        prd_html += "</div></div>"

    if prd.user_stories:
        prd_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">📝 User Stories</h3><ul class="space-y-2">"""
        for s in prd.user_stories:
            prd_html += f'<li class="text-slate-300 pl-4 border-l-2 border-teal-500">{esc(s)}</li>'
        prd_html += "</ul></div>"

    if prd.success_criteria:
        prd_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">✅ Success Criteria (KPIs)</h3><ul class="space-y-2">"""
        for c in prd.success_criteria:
            prd_html += f'<li class="text-slate-300"><span class="text-green-400 mr-2">✓</span>{esc(c)}</li>'
        prd_html += "</ul></div>"

    if prd.risks:
        prd_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">⚠️ Risks & Mitigations</h3><div class="space-y-3">"""
        for r in prd.risks:
            risk = esc(r.get("risk", ""))
            impact = r.get("impact", "medium")
            mit = esc(r.get("mitigation", ""))
            mit_html = f'<p class="text-sm text-slate-400 mt-1">→ {mit}</p>' if mit else ""
            prd_html += f'<div class="bg-slate-700 rounded-lg p-4"><p class="text-white">{risk_icon(impact)} <strong>{risk}</strong> <span class="text-xs text-slate-400">({impact})</span></p>{mit_html}</div>'
        prd_html += "</div></div>"

    prd_html += "</section>"

    # Build Functional section
    func_html = """<section id="functional" class="mb-16">
      <h2 class="text-3xl font-bold text-white mb-8">🎯 Functional Specification</h2>"""

    if func.core_features:
        func_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">Core Features</h3><div class="space-y-3">"""
        for f in func.core_features:
            fid = esc(f.get("id", ""))
            name = esc(f.get("name", ""))
            desc = esc(f.get("description", ""))
            prio = f.get("priority", "P1")
            effort = esc(f.get("effort", "medium"))
            func_html += f'<div class="bg-slate-700 rounded-lg p-4"><p class="text-white font-medium">{prio_icon(prio)} {fid}: {name} <span class="text-xs text-slate-400">[{prio}, {effort}]</span></p><p class="text-sm text-slate-400 mt-1">{desc}</p></div>'
        func_html += "</div></div>"

    if func.user_personas:
        func_html += """<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">"""
        for p in func.user_personas:
            name = esc(p.get("name", "Persona"))
            role = esc(p.get("role", ""))
            goals = p.get("goals", [])
            pains = p.get("pain_points", [])
            func_html += f'<div class="bg-slate-800 rounded-xl p-6"><h4 class="text-white font-medium mb-1">{name}</h4><p class="text-sm text-slate-400 mb-3">{role}</p>'
            if goals:
                func_html += '<p class="text-xs text-slate-500 mb-1">Goals:</p><ul class="text-sm text-slate-300 space-y-1 mb-2">' + "".join(f'<li>🎯 {esc(g)}</li>' for g in goals[:3]) + '</ul>'
            if pains:
                func_html += '<p class="text-xs text-slate-500 mb-1">Pain Points:</p><ul class="text-sm text-slate-300 space-y-1">' + "".join(f'<li>⚠️ {esc(p)}</li>' for p in pains[:3]) + '</ul>'
            func_html += "</div>"
        func_html += "</div>"

    if func.user_journeys:
        func_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">User Journeys</h3>"""
        for j in func.user_journeys:
            scenario = esc(j.get("scenario", "Flow"))
            steps = j.get("steps", [])
            func_html += f'<div class="mb-4"><h4 class="text-white mb-2">{scenario}</h4><div class="flex flex-wrap gap-2">'
            for i, step in enumerate(steps, 1):
                func_html += f'<div class="bg-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300"><span class="text-teal-400 mr-1">{i}.</span>{esc(step)}</div>'
            func_html += "</div></div>"
        func_html += "</div>"

    func_html += "</section>"

    # Build Financial section
    fin_html = """<section id="financial" class="mb-16">
      <h2 class="text-3xl font-bold text-white mb-8">💰 Financial Model</h2>"""

    if fin.executive_summary:
        fin_html += f'<div class="bg-slate-800 rounded-xl p-6 mb-8"><p class="text-slate-300">{esc(fin.executive_summary)}</p></div>'

    if fin.pricing_tiers:
        fin_html += """<div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">"""
        for t in fin.pricing_tiers:
            monthly = f"${t.price_monthly:.0f}" if t.price_monthly is not None else "Free"
            yearly = f"${t.price_yearly:.0f}/yr" if t.price_yearly is not None else ""
            is_highlight = "Starter" in t.name  # highlight recommended tier
            border = "border-teal-500 ring-2 ring-teal-500/20" if is_highlight else "border-slate-600"
            yearly_html = f'<p class="text-sm text-slate-400 mb-4">{yearly}</p>' if yearly else '<p class="text-sm text-slate-400 mb-4">&nbsp;</p>'
            fin_html += f'<div class="bg-slate-800 rounded-xl p-6 border {border}"><h3 class="text-xl font-bold text-white mb-2">{esc(t.name)}</h3><p class="text-4xl font-bold text-teal-400 mb-1">{monthly}</p>{yearly_html}<p class="text-sm text-slate-400 mb-4">{esc(t.description)}</p><ul class="space-y-2 text-sm">' + "".join(f'<li class="text-slate-300">✓ {esc(f)}</li>' for f in t.features[:4]) + '</ul></div>'
        fin_html += "</div>"

    if fin.revenue_projection:
        months_data = fin.revenue_projection
        max_mrr = max((r.get("mrr", 0) for r in months_data), default=1)
        fin_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">Revenue Projection</h3>
      <div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="text-slate-400 border-b border-slate-700">"""
        fin_html += "<th class='text-left py-2'>Month</th><th class='text-right py-2'>Users</th><th class='text-right py-2'>MRR</th><th class='text-right py-2'>Expenses</th><th class='text-right py-2'>Profit</th>"
        fin_html += "</tr></thead><tbody>"
        for r in months_data:
            m = r.get("month", 0)
            u = r.get("users", 0)
            mrr = r.get("mrr", 0)
            exp = r.get("expenses", 0)
            profit = r.get("profit", 0)
            profit_color = "text-green-400" if profit >= 0 else "text-red-400"
            fin_html += f'<tr class="border-b border-slate-700/50"><td class="py-2 text-white">Month {m}</td><td class="py-2 text-right text-slate-300">{u}</td><td class="py-2 text-right text-teal-400">${mrr:.0f}</td><td class="py-2 text-right text-slate-300">${exp:.0f}</td><td class="py-2 text-right {profit_color}">${profit:.0f}</td></tr>'
        fin_html += "</tbody></table></div></div>"

        # Mini bar chart (CSS-only)
        fin_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">MRR Growth (visual)</h3><div class="space-y-2">"""
        for r in months_data:
            m = r.get("month", 0)
            mrr = r.get("mrr", 0)
            pct = (mrr / max_mrr) * 100 if max_mrr > 0 else 0
            fin_html += f'<div class="flex items-center gap-2"><span class="text-xs text-slate-500 w-12">M{m}</span><div class="flex-1 bg-slate-700 rounded-full h-5 overflow-hidden"><div class="bg-gradient-to-r from-teal-500 to-teal-400 h-full rounded-full" style="width:{pct:.1f}%"></div></div><span class="text-xs text-slate-400 w-16 text-right">${mrr:.0f}</span></div>'
        fin_html += "</div></div>"

    if fin.unit_economics:
        ue = fin.unit_economics
        fin_html += """<div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">"""
        for key, label in [("cac", "CAC"), ("ltv", "LTV"), ("ltv_cac_ratio", "LTV/CAC"), ("gross_margin_pct", "Margin"), ("monthly_churn_pct", "Churn"), ("payback_period_months", "Payback")]:
            val = ue.get(key)
            if val is not None:
                suffix = "%" if "pct" in key else "x" if "ratio" in key else "mo" if "period" in key else ""
                fin_html += f'<div class="bg-slate-700 rounded-lg p-4 text-center"><p class="text-2xl font-bold text-teal-400">{val}{suffix}</p><p class="text-xs text-slate-400 mt-1">{label}</p></div>'
        fin_html += "</div>"

    fin_html += "</section>"

    # Build Technical section
    tech_html = """<section id="technical" class="mb-16">
      <h2 class="text-3xl font-bold text-white mb-8">🛠️ Technical Specification</h2>"""

    if tech.stack_recommendation:
        tech_html += f'<div class="bg-slate-800 rounded-xl p-6 mb-8"><h3 class="text-lg font-semibold text-teal-400 mb-3">Stack Recommendation</h3><p class="text-slate-300">{esc(tech.stack_recommendation)}</p></div>'

    if tech.stack_table:
        tech_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">Technology Stack</h3><div class="grid grid-cols-1 md:grid-cols-2 gap-4">"""
        for s in tech.stack_table:
            layer = esc(s.get("layer", ""))
            tech_name = esc(s.get("technology", ""))
            rationale = esc(s.get("rationale", ""))
            tech_html += f'<div class="bg-slate-700 rounded-lg p-4"><h4 class="text-white font-medium mb-1">{layer}</h4><p class="text-teal-400 text-sm mb-1">{tech_name}</p><p class="text-xs text-slate-400">{rationale}</p></div>'
        tech_html += "</div></div>"

    if tech.data_model:
        tech_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">Data Model</h3><div class="grid grid-cols-1 md:grid-cols-2 gap-4">"""
        for entity in tech.data_model:
            e_name = esc(entity.get("entity", ""))
            fields = entity.get("fields", [])
            relations = entity.get("relations", [])
            tech_html += f'<div class="bg-slate-700 rounded-lg p-4"><h4 class="text-white font-medium mb-2">{e_name}</h4><ul class="text-sm text-slate-300 space-y-1">' + "".join(f'<li><code class="text-teal-400">{esc(f.get("name",""))}</code>: <span class="text-slate-400">{esc(f.get("type",""))}</span>{" — " + esc(f.get("notes","")) if f.get("notes") else ""}</li>' for f in fields) + "</ul>" + ("".join(f'<p class="text-xs text-slate-500 mt-1">↔ {esc(r)}</p>' for r in relations) if relations else "") + "</div>"
        tech_html += "</div></div>"

    if tech.api_endpoints:
        tech_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">API Endpoints</h3><div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="text-slate-400 border-b border-slate-700"><th class='text-left py-2'>Method</th><th class='text-left py-2'>Path</th><th class='text-left py-2'>Description</th><th class='text-left py-2'>Auth</th></tr></thead><tbody>"""
        for ep in tech.api_endpoints:
            method = esc(ep.get("method", "GET"))
            path = esc(ep.get("path", "/"))
            desc = esc(ep.get("description", ""))
            auth = esc(ep.get("auth", "public"))
            method_color = {"GET": "text-green-400", "POST": "text-blue-400", "PUT": "text-yellow-400", "DELETE": "text-red-400"}.get(method, "text-slate-300")
            tech_html += f'<tr class="border-b border-slate-700/50"><td class="py-2 font-mono {method_color}">{method}</td><td class="py-2 font-mono text-white">{path}</td><td class="py-2 text-slate-300">{desc}</td><td class="py-2"><span class="text-xs {"text-green-400" if auth == "public" else "text-yellow-400"}">{auth}</span></td></tr>'
        tech_html += "</tbody></table></div></div>"

    if tech.development_phases:
        tech_html += """<div class="bg-slate-800 rounded-xl p-6 mb-8">
      <h3 class="text-lg font-semibold text-teal-400 mb-4">Development Phases</h3><div class="space-y-4">"""
        for phase in tech.development_phases:
            pname = esc(phase.get("phase", ""))
            tasks = phase.get("tasks", [])
            duration = esc(phase.get("duration", ""))
            tech_html += f'<div class="bg-slate-700 rounded-lg p-4"><div class="flex justify-between items-center mb-2"><h4 class="text-white font-medium">{pname}</h4><span class="text-xs text-teal-400">{duration}</span></div><ul class="space-y-1">' + "".join(f'<li class="text-sm text-slate-300 pl-4 border-l-2 border-slate-600">{esc(t)}</li>' for t in tasks) + '</ul></div>'
        tech_html += "</div></div>"

    tech_html += "</section>"

    # Navigation tabs
    nav_items = [
        ("prd", "📋 PRD"),
        ("functional", "🎯 Functional"),
        ("financial", "💰 Financial"),
        ("technical", "🛠️ Technical"),
    ]
    nav_links = "".join(f'<a href="#{id}" class="text-slate-400 hover:text-teal-400 transition px-3 py-1">{label}</a>' for id, label in nav_items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Planning Dashboard — {esc(output.idea[:50])}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ font-family: 'DM Sans', sans-serif; }}
  html {{ scroll-behavior: smooth; }}
  body {{ background: #0f172a; color: #e2e8f0; }}
  .section-nav a {{ border-bottom: 2px solid transparent; }}
  .section-nav a:hover {{ border-color: #14b8a6; }}
</style>
</head>
<body class="min-h-screen">
  <div class="max-w-6xl mx-auto px-4 py-8">
    <!-- Header -->
    <header class="mb-12 text-center">
      <h1 class="text-4xl font-bold text-white mb-2">📊 {esc(output.idea[:60])}</h1>
      <p class="text-slate-400">Startup Planning Dashboard</p>
      <p class="text-xs text-slate-500 mt-2">Generated {output.generated_at.strftime('%Y-%m-%d %H:%M UTC')} · {output.generation_duration_ms}ms</p>
      {f'<p class="text-sm text-slate-400 mt-4 italic">{esc(output.research_summary[:200])}</p>' if output.research_summary else ""}
    </header>

    <!-- Navigation -->
    <nav class="section-nav flex justify-center gap-4 mb-12 text-sm bg-slate-800 rounded-full px-6 py-3 max-w-xl mx-auto">
      {nav_links}
    </nav>

    <!-- Sections -->
    {prd_html}
    {func_html}
    {fin_html}
    {tech_html}

    <footer class="text-center text-xs text-slate-600 mt-16 pb-8">
      Generated by PitchForge Planning Pipeline
    </footer>
  </div>
</body>
</html>"""
