#!/usr/bin/env python3.12
"""PitchForge TUI — interactive terminal interface for the full pipeline.

Usage:
    python3.12 cli_tui.py

Powered by Textual — keyboard-driven, mouse-friendly, dark themed.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
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

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Log,
    Markdown,
    ProgressBar,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.theme import Theme


# ═══════════════════════════════════════════════════════
#  BRAND THEME
# ═══════════════════════════════════════════════════════

STARTUP_THEME = Theme(
    name="startup-factory",
    primary="#14b8a6",
    secondary="#0d9488",
    accent="#2dd4bf",
    success="#22c55e",
    warning="#f59e0b",
    error="#ef4444",
    foreground="#e2e8f0",
    background="#0f172a",
    surface="#0f172a",
    panel="#1e293b",
    dark=True,
)


# ═══════════════════════════════════════════════════════
#  MODALS
# ═══════════════════════════════════════════════════════

class AboutModal(ModalScreen):
    """About dialog."""

    def compose(self) -> ComposeResult:
        yield Container(
            Label("🏭 PitchForge", classes="modal-title"),
            Label("v2.0.0 — CodeGen 2.0", classes="modal-subtitle"),
            Label(""),
            Label("AI-powered startup idea validation & MVP generation"),
            Label(""),
            Label("Stack: FastAPI · React · PostgreSQL · Docker"),
            Label(""),
            Label("Press ESC to close", classes="modal-hint"),
            classes="modal-content",
        )

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss()


class HelpModal(ModalScreen):
    """Keyboard shortcuts help."""

    def compose(self) -> ComposeResult:
        yield Container(
            Label("⌨️  Keyboard Shortcuts", classes="modal-title"),
            Label(""),
            Label("Global"),
            Label("  Ctrl+Q    Quit"),
            Label("  F1        Show this help"),
            Label("  Tab       Navigate between widgets"),
            Label(""),
            Label("Main Screen"),
            Label("  1-5       Select menu item by number"),
            Label("  R         Start research"),
            Label("  P         Start planning"),
            Label("  G         Start codegen"),
            Label(""),
            Label("Press ESC to close", classes="modal-hint"),
            classes="modal-content",
        )

    BINDINGS = [Binding("escape", "dismiss", "Close")]


# ═══════════════════════════════════════════════════════
#  SCREENS
# ═══════════════════════════════════════════════════════

class MainScreen(Screen):
    """Main menu screen."""

    BINDINGS = [
        Binding("r", "research", "Research"),
        Binding("p", "plan", "Plan"),
        Binding("g", "codegen", "CodeGen"),
        Binding("d", "devkit", "DevKit"),
        Binding("a", "assets", "Assets"),
        Binding("f1", "show_help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Label("", classes="spacer-sm"),
            Label("🏭  STARTUP FACTORY  v2.0", classes="title"),
            Label("AI-Powered Startup Validation & MVP Generation", classes="subtitle"),
            Label(""),
            Container(
                Label("🔬  Research", classes="menu-label"),
                Label("Analyze competitors, market validation, opportunity gaps"),
                Button("Start Research [R]", id="btn-research", variant="primary"),
                classes="menu-item",
            ),
            Container(
                Label("📋  Plan", classes="menu-label"),
                Label("PRD → Functional → Financial → Technical specs"),
                Button("Start Planning [P]", id="btn-plan", variant="primary"),
                classes="menu-item",
            ),
            Container(
                Label("🏗️  CodeGen", classes="menu-label"),
                Label("Generate MVP project: Docker, API, Frontend, Tests"),
                Button("Generate Code [G]", id="btn-codegen", variant="primary"),
                classes="menu-item",
            ),
            Container(
                Label("🔧  DevKit", classes="menu-label"),
                Label("Autonomous development: setup, cycle, status"),
                Button("Open DevKit [D]", id="btn-devkit", variant="default"),
                classes="menu-item",
            ),
            Container(
                Label("🎨  Assets", classes="menu-label"),
                Label("Generate landing pages, pitch decks, pricing"),
                Button("Generate Assets [A]", id="btn-assets", variant="default"),
                classes="menu-item",
            ),
            Label(""),
            Label("Ctrl+Q to quit · F1 for help · Tab to navigate", classes="footer-hint"),
            classes="main-container",
        )
        yield Footer()

    @on(Button.Pressed, "#btn-research")
    def action_research(self):
        self.app.switch_screen("research")

    @on(Button.Pressed, "#btn-plan")
    def action_plan(self):
        self.app.switch_screen("plan")

    @on(Button.Pressed, "#btn-codegen")
    def action_codegen(self):
        self.app.switch_screen("codegen")

    @on(Button.Pressed, "#btn-devkit")
    def action_devkit(self):
        self.app.switch_screen("devkit")

    @on(Button.Pressed, "#btn-assets")
    def action_assets(self):
        self.app.switch_screen("assets")

    def action_show_help(self):
        self.app.push_screen(HelpModal())


class ResearchScreen(Screen):
    """Research flow screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+r", "run_research", "Run"),
    ]

    idea = reactive("")
    target = reactive("")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Label("🔬  Market Research", classes="screen-title"),
            Label("Research your startup idea against competitors and market data.", classes="screen-desc"),
            Label(""),
            Label("💡  Startup Idea"),
            Input(placeholder="e.g., AI-powered freight marketplace for Angola", id="idea-input"),
            Label(""),
            Label("🎯  Target Market (optional)"),
            Input(placeholder="e.g., logistics, healthcare, fintech", id="target-input"),
            Label(""),
            Horizontal(
                Button("▶  Run Research", id="btn-run", variant="primary"),
                Button("←  Back", id="btn-back", variant="default"),
                classes="button-row",
            ),
            Label(""),
            RichLog(id="research-log", highlight=True, markup=True),
            Label(""),
            ProgressBar(id="research-progress", total=100, show_eta=False),
            classes="screen-container",
        )
        yield Footer()

    def on_mount(self):
        self.query_one("#research-progress", ProgressBar).update(progress=0)

    @on(Button.Pressed, "#btn-run")
    async def action_run_research(self):
        idea = self.query_one("#idea-input", Input).value.strip()
        target = self.query_one("#target-input", Input).value.strip()

        if not idea:
            self.query_one("#research-log", RichLog).write("[bold red]Please enter a startup idea.[/]")
            return

        log = self.query_one("#research-log", RichLog)
        progress = self.query_one("#research-progress", ProgressBar)

        log.clear()
        log.write(f"[bold cyan]🔬 Researching:[/] {idea}")
        if target:
            log.write(f"[dim]Target market: {target}[/]")
        log.write("")

        progress.update(progress=10)

        try:
            from app.research import ResearchEngine
            from app.research.http_client import ResearchHTTPClient

            log.write("[dim]Initializing research engine...[/]")
            progress.update(progress=20)

            try:
                http_client = ResearchHTTPClient()
                engine = ResearchEngine(http_client=http_client)
            except ValueError as ve:
                log.write(f"[bold red]❌ Configuration error: {ve}[/]")
                log.write("[dim]Tip: Check your API keys in config or environment variables.[/]")
                progress.update(progress=0)
                return
            except ConnectionError as ce:
                log.write(f"[bold red]❌ Connection error: {ce}[/]")
                log.write("[dim]Tip: Check your internet connection and API endpoints.[/]")
                progress.update(progress=0)
                return

            log.write("[dim]Running multi-source research...[/]")
            progress.update(progress=40)

            report = await engine.run(
                idea=idea,
                target_market=target,
            )
            progress.update(progress=80)

            log.write("")
            log.write(f"[bold green]✅ Research complete![/]")
            log.write(f"  Duration: {report.research_duration_ms}ms")
            log.write(f"  Sources: {', '.join(report.sources_used) if report.sources_used else 'all'}")
            log.write(f"  Competitors found: {len(report.competitors)}")
            log.write(f"  Opportunity gaps: {len(report.opportunity_gaps)}")
            log.write("")

            if report.summary:
                log.write(f"[bold]📋 Summary:[/] {report.summary[:300]}")
                log.write("")

            if report.competitors:
                log.write("[bold]🏢 Top Competitors:[/]")
                for c in report.competitors[:5]:
                    log.write(f"  • [cyan]{c.name}[/] — {c.description[:80] if c.description else 'No description'}")

            if report.recommended_positioning:
                log.write(f"\n[bold]🎯 Positioning:[/] {report.recommended_positioning}")

            if report.recommended_pricing_range:
                log.write(f"[bold]💰 Pricing:[/] {report.recommended_pricing_range}")

            # Save results for subsequent planning
            self.app.research_report = report
            self.app.research_idea = idea
            log.write(f"\n[bold green]✓[/] Research saved for planning phase.")

            progress.update(progress=100)

        except Exception as e:
            log.write(f"\n[bold red]❌ Error:[/] {str(e)}")
            progress.update(progress=0)

    @on(Button.Pressed, "#btn-back")
    def action_back(self):
        self.app.switch_screen("main")


class PlanScreen(Screen):
    """Planning flow screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+p", "run_planning", "Run"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Label("📋  Strategic Planning", classes="screen-title"),
            Label("Generate PRD, Functional, Financial, and Technical specs.", classes="screen-desc"),
            Label(""),
            Label("💡  Idea"),
            Input(placeholder="Startup idea or use research results", id="plan-idea"),
            Label(""),
            Switch(value=False, id="use-research"),
            Label("  Use existing research results", classes="switch-label"),
            Label(""),
            Switch(value=False, id="run-codegen"),
            Label("  Also generate MVP code (Docker, API, Frontend)", classes="switch-label"),
            Label(""),
            Horizontal(
                Button("▶  Run Planning", id="btn-plan-run", variant="primary"),
                Button("←  Back", id="btn-plan-back", variant="default"),
                classes="button-row",
            ),
            Label(""),
            RichLog(id="plan-log", highlight=True, markup=True),
            Label(""),
            ProgressBar(id="plan-progress", total=100, show_eta=False),
            classes="screen-container",
        )
        yield Footer()

    @on(Button.Pressed, "#btn-plan-run")
    async def action_run_planning(self):
        idea = self.query_one("#plan-idea", Input).value.strip()
        use_research = self.query_one("#use-research", Switch).value
        run_codegen = self.query_one("#run-codegen", Switch).value

        log = self.query_one("#plan-log", RichLog)
        progress = self.query_one("#plan-progress", ProgressBar)
        log.clear()

        # Get idea from research or input
        if use_research and hasattr(self.app, "research_report"):
            report = self.app.research_report
            idea = report.idea
            log.write(f"[dim]Using research results for: {idea}[/]")
        elif not idea:
            log.write("[bold red]Please enter an idea or use research results.[/]")
            return
        else:
            log.write(f"[bold cyan]📋 Planning:[/] {idea}")
            log.write("[dim]Running research first...[/]")
            progress.update(progress=10)

            try:
                from app.research import ResearchEngine
                from app.research.http_client import ResearchHTTPClient

                http_client = ResearchHTTPClient()
                engine = ResearchEngine(http_client=http_client)
                report = await engine.run(idea=idea)
                progress.update(progress=30)
                log.write(f"[dim]Research: {len(report.competitors)} competitors found[/]")
            except Exception as e:
                log.write(f"[bold red]Research failed: {e}[/]")
                return

        progress.update(progress=40)

        try:
            from app.planning import PlanningPipeline

            pipeline = PlanningPipeline()
            log.write("[dim]Running planning pipeline (PRD → Functional → Financial → Technical)...[/]")
            progress.update(progress=50)

            output = await pipeline.run(report)
            progress.update(progress=70)

            log.write("")
            log.write("[bold green]✅ Planning complete![/]")
            log.write(f"  Product: {output.prd.product_name or idea}")
            log.write(f"  Tagline: {output.prd.tagline or 'N/A'}")
            log.write(f"  Features: {len(output.functional.core_features)}")
            log.write(f"  Pricing tiers: {len(output.financial.pricing_tiers)}")
            log.write(f"  Stack layers: {len(output.technical.stack_table)}")
            log.write(f"  Development phases: {len(output.technical.development_phases)}")
            log.write(f"  Duration: {output.generation_duration_ms}ms")
            log.write("")

            # Save for codegen
            self.app.planning_output = output
            self.app.research_report = report

            progress.update(progress=85)

            if run_codegen:
                log.write("[bold cyan]🏗️ Generating MVP code...[/]")
                try:
                    from app.planning.codegen import CodegenPipeline
                    idea_slug = idea.lower().replace(" ", "-")[:30]
                    out_dir = f"generated/{idea_slug}"
                    cp = CodegenPipeline()
                    result = await cp.run(output, out_dir)
                    log.write(f"[bold green]✅ Codegen:[/] {result['total_files']} files → {out_dir}")
                    log.write(f"  Validation: {'✅ passed' if result['validation']['success'] else '❌ issues'}")
                    progress.update(progress=100)
                except Exception as e:
                    log.write(f"[bold red]Codegen failed: {e}[/]")

        except Exception as e:
            log.write(f"\n[bold red]❌ Error:[/] {str(e)}")

    @on(Button.Pressed, "#btn-plan-back")
    def action_back(self):
        self.app.switch_screen("main")


class CodeGenScreen(Screen):
    """Code generation screen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+g", "run_codegen", "Generate"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Label("🏗️  Code Generation", classes="screen-title"),
            Label("Generate a complete MVP project from planning specs.", classes="screen-desc"),
            Label(""),
            Label("📂  Output Directory"),
            Input(placeholder="generated/my-startup", id="output-dir", value="generated/startup-mvp"),
            Label(""),
            Switch(value=True, id="gen-speckit"),
            Label("  Generate speckit artifacts (SPEC.md, PLAN.md, TASK-*.md)", classes="switch-label"),
            Label(""),
            Switch(value=True, id="gen-scaffold"),
            Label("  Generate Docker, CI/CD, i18n, theme", classes="switch-label"),
            Label(""),
            Horizontal(
                Button("▶  Generate Code", id="btn-gen", variant="primary"),
                Button("←  Back", id="btn-gen-back", variant="default"),
                classes="button-row",
            ),
            Label(""),
            RichLog(id="codegen-log", highlight=True, markup=True),
            Label(""),
            ProgressBar(id="codegen-progress", total=100, show_eta=False),
            classes="screen-container",
        )
        yield Footer()

    @on(Button.Pressed, "#btn-gen")
    async def action_run_codegen(self):
        log = self.query_one("#codegen-log", RichLog)
        progress = self.query_one("#codegen-progress", ProgressBar)
        log.clear()

        if not hasattr(self.app, "planning_output"):
            log.write("[bold red]No planning data. Please run the Planning phase first.[/]")
            return

        output = self.app.planning_output
        out_dir = self.query_one("#output-dir", Input).value.strip() or "generated/startup-mvp"

        try:
            from app.planning.codegen import CodegenPipeline

            pipeline = CodegenPipeline()
            progress.update(progress=10)
            log.write(f"[bold cyan]🏗️ Generating MVP project...[/]")
            log.write(f"  Output: {out_dir}")
            log.write("")

            progress.update(progress=30)
            result = await pipeline.run(output, out_dir)
            progress.update(progress=80)

            log.write(f"[bold green]✅ Project generated![/]")
            log.write(f"  Total files: {result['total_files']}")
            log.write(f"  Duration: {result['duration_ms']}ms")
            log.write("")
            stats = result.get("stats", {})
            for key, val in stats.items():
                log.write(f"  {key}: {val}")
            log.write("")

            validation = result.get("validation", {})
            if validation.get("success"):
                log.write("[bold green]✅ Validation gate passed[/]")
            else:
                log.write(f"[bold yellow]⚠️ Validation issues:[/]")
                for d in validation.get("missing_dirs", []):
                    log.write(f"  Missing dir: {d}")
                for f in validation.get("missing_files", []):
                    log.write(f"  Missing file: {f}")

            log.write(f"\n[bold cyan]📂 Output:[/] {Path(out_dir).resolve()}")
            log.write(f"[bold cyan]🚀 Run:[/] cd {out_dir} && make dev")

            progress.update(progress=100)

        except Exception as e:
            log.write(f"\n[bold red]❌ Error:[/] {str(e)}")
            import traceback
            log.write(f"[dim]{traceback.format_exc()}[/]")

    @on(Button.Pressed, "#btn-gen-back")
    def action_back(self):
        self.app.switch_screen("main")


class DevKitScreen(Screen):
    """DevKit screen for autonomous development."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Label("🔧  DevKit — Autonomous Development", classes="screen-title"),
            Label("Initialize and manage autonomous development cycles.", classes="screen-desc"),
            Label(""),
            Label("📂  Project Directory"),
            Input(placeholder="path/to/project", id="devkit-dir", value="generated/startup-mvp"),
            Label(""),
            Horizontal(
                Button("🔧  Setup", id="btn-setup", variant="primary"),
                Button("📊  Status", id="btn-status", variant="default"),
                Button("🔄  Run Cycle", id="btn-cycle", variant="default"),
                Button("←  Back", id="btn-devkit-back", variant="default"),
                classes="button-row",
            ),
            Label(""),
            RichLog(id="devkit-log", highlight=True, markup=True),
            classes="screen-container",
        )
        yield Footer()

    def _get_project_dir(self):
        return self.query_one("#devkit-dir", Input).value.strip()

    @on(Button.Pressed, "#btn-setup")
    def action_setup(self):
        log = self.query_one("#devkit-log", RichLog)
        log.clear()
        project_dir = self._get_project_dir()

        if not Path(project_dir).exists():
            log.write(f"[bold red]Directory not found: {project_dir}[/]")
            return

        try:
            from app.devkit import DevAgent

            agent = DevAgent(project_dir)
            result = agent.setup()
            log.write(f"[bold green]✅ Dev environment ready![/]")
            log.write(f"  Vault files: {len(result['vault_files'])}")
            log.write(f"  Tasks created: {result['tasks_created']}")
            log.write(f"  Docker: {'✅' if result['docker_available'] else '❌'}")
        except Exception as e:
            log.write(f"[bold red]Error: {e}[/]")

    @on(Button.Pressed, "#btn-status")
    def action_status(self):
        log = self.query_one("#devkit-log", RichLog)
        log.clear()
        project_dir = self._get_project_dir()

        try:
            from app.devkit import DevAgent

            agent = DevAgent(project_dir)
            status = agent.status()
            log.write(f"[bold cyan]📊 Project Status[/]")
            log.write(f"  Tasks: {status['tasks']['completed']}/{status['tasks']['total']} done")
            log.write(f"  Docker: {'✅' if status['docker_available'] else '❌'}")
            if status.get("next_task"):
                log.write(f"  Next: {status['next_task']['id']} — {status['next_task']['title']}")
        except Exception as e:
            log.write(f"[bold red]Error: {e}[/]")

    @on(Button.Pressed, "#btn-cycle")
    async def action_cycle(self):
        log = self.query_one("#devkit-log", RichLog)
        log.clear()
        project_dir = self._get_project_dir()

        try:
            from app.devkit import DevAgent

            agent = DevAgent(project_dir)
            result = agent.run_cycle()
            log.write(f"[bold cyan]🔄 Cycle {result['cycle']}[/]")
            if result["status"] == "all_done":
                log.write(f"[bold green]🎉 MVP complete! {result.get('message', '')}[/]")
            else:
                task = result["task"]
                log.write(f"  Task: {task['id']} — {task['title']}")
                log.write(f"  Priority: {task['priority']}")
        except Exception as e:
            log.write(f"[bold red]Error: {e}[/]")

    @on(Button.Pressed, "#btn-devkit-back")
    def action_back(self):
        self.app.switch_screen("main")


class AssetsScreen(Screen):
    """Asset generation screen."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(
            Label("🎨  Asset Generation", classes="screen-title"),
            Label("Generate pitch decks, landing pages, and pricing pages.", classes="screen-desc"),
            Label(""),
            Label("💡  Idea (or use research from previous phase)"),
            Input(placeholder="Startup idea", id="assets-idea"),
            Label(""),
            Horizontal(
                Button("▶  Generate All", id="btn-assets-gen", variant="primary"),
                Button("←  Back", id="btn-assets-back", variant="default"),
                classes="button-row",
            ),
            Label(""),
            RichLog(id="assets-log", highlight=True, markup=True),
            Label(""),
            ProgressBar(id="assets-progress", total=100, show_eta=False),
            classes="screen-container",
        )
        yield Footer()

    @on(Button.Pressed, "#btn-assets-gen")
    async def action_generate_assets(self):
        idea = self.query_one("#assets-idea", Input).value.strip()
        log = self.query_one("#assets-log", RichLog)
        progress = self.query_one("#assets-progress", ProgressBar)
        log.clear()

        if hasattr(self.app, "research_report"):
            report = self.app.research_report
            log.write(f"[dim]Using research data for: {report.idea}[/]")
        elif idea:
            log.write(f"[bold cyan]Running quick research for: {idea}[/]")
            progress.update(progress=10)
            try:
                from app.research import ResearchEngine
                from app.research.http_client import ResearchHTTPClient

                http_client = ResearchHTTPClient()
                engine = ResearchEngine(http_client=http_client)
                report = await engine.run(idea=idea)
                progress.update(progress=30)
            except Exception as e:
                log.write(f"[bold red]Research failed: {e}[/]")
                return
        else:
            log.write("[bold red]Please enter an idea or run Research first.[/]")
            return

        try:
            from app.generator import generate_all

            progress.update(progress=40)
            log.write("[dim]Generating assets...[/]")

            result = await generate_all(report)
            progress.update(progress=90)

            log.write("[bold green]✅ Assets generated![/]")
            for name, path in result.items():
                emoji = {"pitch_deck": "📊", "landing": "🌐", "pricing": "💰"}.get(name, "📄")
                status = "✅" if not str(path).startswith("Error") else "❌"
                log.write(f"  {status} {emoji} {name}: {path}")

            progress.update(progress=100)

        except Exception as e:
            log.write(f"[bold red]❌ Error: {e}[/]")

    @on(Button.Pressed, "#btn-assets-back")
    def action_back(self):
        self.app.switch_screen("main")


# ═══════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════

class StartupFactoryApp(App):
    """PitchForge — AI-Powered Startup Validation & MVP Generation."""

    CSS = """
    Screen {
        background: #0f172a;
    }

    .main-container {
        padding: 2 4;
        max-width: 80;
        margin: 0 auto;
    }

    .screen-container {
        padding: 2 4;
    }

    .title {
        text-align: center;
        text-style: bold;
        color: #14b8a6;
        padding: 1 0;
        content-align: center middle;
        width: 100%;
    }

    .subtitle {
        text-align: center;
        color: #94a3b8;
        content-align: center middle;
        width: 100%;
    }

    .screen-title {
        text-style: bold;
        color: #14b8a6;
        padding: 1 0;
    }

    .screen-desc {
        color: #94a3b8;
        padding-bottom: 1;
    }

    .menu-item {
        padding: 1 2;
        margin: 1 0;
        border: solid #1e293b;
        background: #1e293b;
    }

    .menu-item:hover {
        border: solid #14b8a6;
    }

    .menu-label {
        text-style: bold;
        color: #e2e8f0;
        padding-bottom: 1;
    }

    .button-row {
        padding: 1 0;
    }

    .switch-label {
        color: #94a3b8;
    }

    .footer-hint {
        text-align: center;
        color: #475569;
        content-align: center middle;
        width: 100%;
    }

    .spacer-sm {
        height: 1;
    }

    /* Modal */
    .modal-content {
        padding: 2 4;
        background: #1e293b;
        border: solid #14b8a6;
        margin: 4 8;
    }

    .modal-title {
        text-style: bold;
        color: #14b8a6;
        text-align: center;
        content-align: center middle;
        width: 100%;
    }

    .modal-subtitle {
        text-align: center;
        color: #94a3b8;
        content-align: center middle;
        width: 100%;
    }

    .modal-hint {
        text-align: center;
        color: #475569;
        content-align: center middle;
        width: 100%;
        padding-top: 1;
    }

    Button {
        margin: 0 1;
    }

    RichLog {
        background: #0a0a14;
        color: #e2e8f0;
        border: solid #1e293b;
        min-height: 10;
    }

    ProgressBar {
        width: 100%;
    }

    ProgressBar > .bar {
        background: #14b8a6;
    }

    Input {
        background: #1e293b;
        color: #e2e8f0;
        border: solid #334155;
    }

    Input:focus {
        border: solid #14b8a6;
    }

    Switch > .switch--slider {
        background: #334155;
    }

    Switch.-on > .switch--slider {
        background: #14b8a6;
    }

    Header {
        background: #1e293b;
        color: #14b8a6;
    }

    Footer {
        background: #1e293b;
        color: #475569;
    }

    TabbedContent {
        background: #0f172a;
    }

    TabPane {
        background: #0f172a;
        padding: 1 2;
        border: solid #1e293b;
    }

    LoadingIndicator {
        color: #14b8a6;
    }
    """

    SCREENS = {
        "main": MainScreen,
        "research": ResearchScreen,
        "plan": PlanScreen,
        "codegen": CodeGenScreen,
        "devkit": DevKitScreen,
        "assets": AssetsScreen,
    }

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("f1", "show_help", "Help"),
        Binding("ctrl+a", "show_about", "About"),
    ]

    # Shared state between screens
    research_report = None
    research_idea = ""
    planning_output = None

    def on_mount(self):
        self.push_screen("main")

    def action_show_help(self):
        self.push_screen(HelpModal())

    def action_show_about(self):
        self.push_screen(AboutModal())


def main():
    """Run the PitchForge TUI."""
    app = StartupFactoryApp()
    app.run()


if __name__ == "__main__":
    main()
