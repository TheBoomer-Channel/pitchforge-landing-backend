#!/usr/bin/env python3.12
"""PitchForge CLI — research any startup idea from the terminal.

Usage:
    python cli.py research "AI-powered freight marketplace for Angola"
    python cli.py research "freight marketplace" --target "logistics Africa"
    python cli.py report <project_id>
"""

import argparse
import asyncio
import json
import sys
import os
from pathlib import Path

# Add backend to path (supports code/backend/, backend/, and Docker /app/ layouts)
_base = os.path.dirname(__file__)
_backend_path = _base
for candidate in [
    os.path.join(_base, "code", "backend"),
    os.path.join(_base, "backend"),
    _base,  # Docker layout: modules at ./app/
]:
    if os.path.isdir(os.path.join(candidate, "app")):
        _backend_path = candidate
        break
sys.path.insert(0, _backend_path)

from app.research import ResearchEngine, filter_from_research, format_filter_report
from app.research.http_client import ResearchHTTPClient
from app.research.base_source import list_sources, get_enabled_sources
from app.research.models import ResearchReport
from app.worker import report_to_markdown
from app.generator import generate_all
from app.planning import PlanningPipeline


def main():
    parser = argparse.ArgumentParser(description="PitchForge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # research
    rp = sub.add_parser("research", help="Research a startup idea")
    rp.add_argument("idea", help="The startup idea to research")
    rp.add_argument("--target", "-t", help="Target market/industry", default="")
    rp.add_argument("--model", "-m", help="Business model", default="")
    rp.add_argument("--sources", "-s", nargs="*", help="Specific sources to use")
    rp.add_argument("--output", "-o", help="Output directory for report files")
    rp.add_argument("--llm", action="store_true", help="Use LLM synthesis")
    rp.add_argument("--json", action="store_true", help="Output JSON report")
    rp.add_argument("--generate", "-g", action="store_true", help="Also generate pitch/landing/pricing")

    # plan
    pp = sub.add_parser("plan", help="Generate PRD + Functional + Financial + Technical specs")
    pp.add_argument("idea", help="The startup idea to plan")
    pp.add_argument("--json", "-j", help="Path to existing research JSON (skip research phase)", default="")
    pp.add_argument("--output", "-o", help="Output directory", default="")
    pp.add_argument("--codegen", "-c", action="store_true", help="Also generate MVP code (Docker + CRUD + Frontend)")

    # devkit
    import cli_devkit
    cli_devkit.add_devkit_parser(sub)

    # filter
    fp = sub.add_parser("filter", help="Evaluate idea through 3-Gate filter")
    fp.add_argument("idea", help="The startup idea to evaluate")
    fp.add_argument("--target", "-t", help="Target market/industry", default="")
    fp.add_argument("--model", "-m", help="Business model", default="")

    # sources
    sp = sub.add_parser("sources", help="List available research sources")

    args = parser.parse_args()

    if args.command == "sources":
        print("Available sources:")
        for name in list_sources():
            print(f"  - {name}")
        print(f"\nEnabled: {get_enabled_sources()}")
        return

    if args.command == "plan":
        asyncio.run(run_plan(args))
        return

    if args.command == "devkit":
        import cli_devkit
        cli_devkit.run_devkit(args)
        return

    if args.command == "filter":
        asyncio.run(run_filter(args))
        return

    if args.command == "research":
        asyncio.run(run_research(args))


async def run_research(args):
    os.environ["RESEARCH_USE_LLM"] = "true" if args.llm else "false"

    print(f"\n🔬 Researching: {args.idea}")
    if args.target:
        print(f"   Target market: {args.target}")
    if args.model:
        print(f"   Business model: {args.model}")
    print(f"   Sources: {args.sources or 'all enabled'}")
    print()

    http_client = ResearchHTTPClient()
    engine = ResearchEngine(http_client=http_client)

    report = await engine.run(
        idea=args.idea,
        target_market=args.target,
        business_model=args.model,
        source_names=args.sources,
    )

    print(f"\n{'='*60}")
    print(f"✅ RESEARCH COMPLETE")
    print(f"   Duration: {report.research_duration_ms}ms")
    print(f"   Sources: {', '.join(report.sources_used)}")
    print(f"   Competitors found: {len(report.competitors)}")
    print(f"   Opportunity gaps: {len(report.opportunity_gaps)}")
    print(f"{'='*60}")

    if report.summary:
        print(f"\n📋 Summary:")
        print(f"   {report.summary}")

    if report.competitors:
        print(f"\n🏢 Competitors ({len(report.competitors)}):")
        for c in report.competitors[:5]:
            print(f"   • {c.name}")
            if c.description:
                print(f"     {c.description[:120]}")
            if c.pain_points:
                print(f"     ⚠ {c.pain_points[0][:100]}")

    mv = report.market_validation
    if mv:
        print(f"\n📊 Market Validation:")
        print(f"   Reddit: {mv.reddit_posts_found} posts | HN: {mv.hn_mentions} mentions | GH: {mv.gh_similar_projects} projects")
        if mv.common_complaints:
            print(f"   Top complaints: {mv.common_complaints[0][:100]}")
        if mv.common_desires:
            print(f"   Top desires: {mv.common_desires[0][:100]}")

    if report.opportunity_gaps:
        print(f"\n🔍 Opportunity Gaps:")
        for g in report.opportunity_gaps[:3]:
            print(f"   • {g.gap} ({g.severity})")

    if report.recommended_mvp_features:
        print(f"\n✅ Recommended MVP Features:")
        for f in report.recommended_mvp_features:
            print(f"   • {f}")

    if report.recommended_pricing_range:
        print(f"\n💰 Pricing: {report.recommended_pricing_range}")

    if report.recommended_positioning:
        print(f"\n🎯 Positioning: {report.recommended_positioning}")

    if report.risk_factors:
        print(f"\n⚠️ Risk Factors:")
        for r in report.risk_factors:
            print(f"   • {r}")

    # Save to files
    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)

        md = report_to_markdown(report)
        (out_dir / "research_report.md").write_text(md)
        (out_dir / "research_report.json").write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
        )
        print(f"\n📁 Reports saved to {out_dir}/")

    # JSON output
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))

    # Print markdown
    if not args.json:
        print(f"\n📄 Full report:")
        print(report_to_markdown(report))

    # Generate pitch/landing/pricing
    if args.generate:
        print(f"\n🎨 Generating pitch deck, landing page, and pricing...")
        out_dir = Path(args.output) if args.output else Path("generated") / report.idea.lower().replace(" ", "-")[:30]
        results = await generate_all(report, output_dir=str(out_dir))
        for name, path in results.items():
            emoji = {"pitch_deck": "📊", "landing": "🌐", "pricing": "💰"}.get(name, "📄")
            status = "✅" if not str(path).startswith("Error") else "❌"
            print(f"   {status} {emoji} {name}: {path}")


async def run_plan(args):
    """Run the full planning pipeline: PRD → Functional → Financial → Technical."""
    pipeline = PlanningPipeline()

    # Option A: load existing research from JSON
    if args.json:
        json_path = Path(args.json)
        if not json_path.exists():
            print(f"❌ Research JSON not found: {json_path}")
            return
        data = json.loads(json_path.read_text())
        report = ResearchReport(**data)
        print(f"📂 Loaded research from {json_path}")
    else:
        # Option B: run research first
        print(f"\n🔬 Step 1/5: Running market research...")
        http_client = ResearchHTTPClient()
        engine = ResearchEngine(http_client=http_client)
        os.environ["RESEARCH_USE_LLM"] = "true"
        report = await engine.run(idea=args.idea)
        print(f"   ✅ Research complete: {len(report.competitors)} competitors, {len(report.opportunity_gaps)} gaps")

    # Run planning pipeline
    print(f"\n📋 Step 2-5/5: PRD → Functional → Financial → Technical")
    idea_slug = report.idea.lower().replace(" ", "-")[:40]
    out_dir = args.output or f"planning/{idea_slug}"
    results = await pipeline.run_and_save(report, output_dir=out_dir, generate_code=args.codegen)

    print(f"\n{'='*60}")
    print(f"✅ PLANNING COMPLETE")
    print(f"   Duration: {results['duration_ms']}ms")
    print(f"   Files saved to: {out_dir}/")
    print(f"{'='*60}")
    print(f"\n📄 Outputs:")
    for fmt, path in results.items():
        emoji = {"json": "📊", "markdown": "📝", "html": "🌐"}.get(fmt, "📄")
        if fmt in ("duration_ms", "codegen"):
            continue
        print(f"   {emoji} {fmt}: {path}")

    if results.get("codegen") and "error" not in results["codegen"]:
        cg = results["codegen"]
        print(f"\n🏗️  Codegen: {cg['total_files']} files → {cg['output_dir']}")

    # Also try to generate pitch/landing/pricing from the same research
    print(f"\n🎨 Generating pitch deck, landing page, and pricing...")
    from app.generator import generate_all
    gen_results = await generate_all(report, output_dir=out_dir)
    for name, path in gen_results.items():
        emoji = {"pitch_deck": "📊", "landing": "🌐", "pricing": "💰"}.get(name, "📄")
        status = "✅" if not str(path).startswith("Error") else "❌"
        print(f"   {status} {emoji} {name}: {path}")

    # Package all outputs
    print(f"\n📦 All outputs in: {os.path.abspath(out_dir)}/")


async def run_filter(args):
    """Run the 3-Gate idea filter."""
    print(f"\n🚦 3-Gate Idea Filter: {args.idea}")
    print(f"{'='*60}")

    result = filter_from_research(
        idea=args.idea,
        target_market=args.target,
        business_model=args.model,
    )

    print(format_filter_report(result))


if __name__ == "__main__":
    main()
