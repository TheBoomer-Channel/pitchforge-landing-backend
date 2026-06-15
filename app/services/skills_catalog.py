"""Skills Catalog — builderstudio-skills compatible catalog for development enhancement.

Based on the Builder Studio Skills ecosystem (github.com/wundercorp/builderstudio-skills).
Each skill enhances a specific aspect of code development: structure, testing,
accessibility, documentation, security, i18n, and more.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Skill:
    """A developer skill from the builderstudio-skills ecosystem."""
    id: str
    name: str
    description: str
    repo_url: str
    install_cmd: str
    category: str
    tags: list[str] = field(default_factory=list)
    best_for: list[str] = field(default_factory=list)
    icon: str = "🧠"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "repo_url": self.repo_url,
            "install_cmd": self.install_cmd,
            "category": self.category,
            "tags": self.tags,
            "best_for": self.best_for,
            "icon": self.icon,
        }


# ── Skill categories ───────────────────────────────────

CATEGORIES = {
    "development": "Development & Structure",
    "testing": "Testing & Quality",
    "design": "Design & UX",
    "documentation": "Documentation & Memory",
    "security": "Security & Compliance",
    "i18n": "Internationalization",
    "infra": "Infrastructure & DevOps",
    "video": "Video & Motion",
}


# ── Full catalog (curated from builderstudio-skills) ────

SKILLS: list[Skill] = [
    # ── Development ──────────────────────────────────
    Skill(
        id="professional-developer",
        name="Professional Developer",
        description="Production-grade development guidance for clean structure, formatting, "
                    "design patterns, testing, maintainability, and professional code review behavior.",
        repo_url="https://github.com/wundercorp/professional-developer-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/professional-developer-skill --skill professional-developer",
        category="development",
        tags=["structure", "patterns", "maintainability", "code-review"],
        best_for=["Refactoring codebases", "Improving folder structure", "Design patterns"],
        icon="⚡",
    ),
    Skill(
        id="wiring",
        name="Wiring",
        description="Connect APIs, services, and external tools with production-grade integration "
                    "patterns: auth, webhooks, retries, rate limits, and error handling.",
        repo_url="https://github.com/wundercorp/wiring-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/wiring-skill --skill wiring",
        category="development",
        tags=["api", "integration", "webhooks", "auth"],
        best_for=["API integrations", "Webhook setup", "Service connections"],
        icon="🔌",
    ),
    Skill(
        id="coherence",
        name="Coherence",
        description="Ensure architectural and stylistic consistency across the codebase. "
                    "Detects drift, enforces conventions, and harmonizes patterns.",
        repo_url="https://github.com/wundercorp/coherence-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/coherence-skill --skill coherence",
        category="development",
        tags=["consistency", "architecture", "conventions"],
        best_for=["Multi-file refactors", "Consistency audits"],
        icon="🎯",
    ),
    Skill(
        id="cleaner",
        name="Cleaner",
        description="Code cleanup and de-duplication. Removes dead code, merges duplicates, "
                    "and simplifies over-engineered solutions.",
        repo_url="https://github.com/wundercorp/cleaner-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/cleaner-skill --skill cleaner",
        category="development",
        tags=["cleanup", "refactor", "de-duplication"],
        best_for=["Removing dead code", "Simplifying logic"],
        icon="🧹",
    ),
    Skill(
        id="patcher",
        name="Patcher",
        description="Quick, surgical fixes for bugs and issues. Patches specific problems without "
                    "refactoring entire modules.",
        repo_url="https://github.com/wundercorp/patcher-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/patcher-skill --skill patcher",
        category="development",
        tags=["bugfix", "patch", "hotfix"],
        best_for=["Bug fixes", "Quick patches"],
        icon="🩹",
    ),

    # ── Testing ─────────────────────────────────────
    Skill(
        id="doctor",
        name="Doctor",
        description="Diagnostic and debugging specialist. Analyzes errors, suggests fixes, "
                    "and helps resolve complex runtime issues.",
        repo_url="https://github.com/wundercorp/doctor-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/doctor-skill --skill doctor",
        category="testing",
        tags=["debugging", "diagnostics", "errors"],
        best_for=["Debugging runtime errors", "Analyzing stack traces"],
        icon="🏥",
    ),
    Skill(
        id="svalbard",
        name="Svalbard",
        description="Frozen-in-time snapshot testing. Creates reproducible test snapshots "
                    "that can be compared across runs for regression detection.",
        repo_url="https://github.com/wundercorp/svalbard-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/svalbard-skill --skill svalbard",
        category="testing",
        tags=["snapshot-testing", "regression", "reproducibility"],
        best_for=["Snapshot tests", "Regression detection"],
        icon="❄️",
    ),

    # ── Design & UX ─────────────────────────────────
    Skill(
        id="contrast-guard",
        name="Contrast Guard",
        description="WCAG contrast ratio auditing and fixing. Ensures all text meets AA/AAA "
                    "contrast requirements across themes.",
        repo_url="https://github.com/wundercorp/contrast-guard-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/contrast-guard-skill --skill contrast-guard",
        category="design",
        tags=["accessibility", "contrast", "wcag"],
        best_for=["Color contrast audits", "Theme accessibility"],
        icon="👁️",
    ),
    Skill(
        id="accessibility",
        name="Accessibility",
        description="Full WCAG compliance auditing and remediation. Covers ARIA, keyboard nav, "
                    "screen readers, focus management, and semantic HTML.",
        repo_url="https://github.com/wundercorp/accessibility-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/accessibility-skill --skill accessibility",
        category="design",
        tags=["a11y", "wcag", "aria", "keyboard"],
        best_for=["WCAG compliance", "Screen reader support"],
        icon="♿",
    ),
    Skill(
        id="themable",
        name="Themable",
        description="Multi-theme design system generation. Creates cohesive dark/light/custom "
                    "theme support with CSS variables and Tailwind integration.",
        repo_url="https://github.com/wundercorp/themable-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/themable-skill --skill themable",
        category="design",
        tags=["themes", "dark-mode", "design-system"],
        best_for=["Theme systems", "Dark/light mode"],
        icon="🎨",
    ),
    Skill(
        id="bauhaus",
        name="Bauhaus",
        description="Minimalist, grid-based layout design. Applies Bauhaus design principles "
                    "for clean, functional, and beautiful interfaces.",
        repo_url="https://github.com/wundercorp/bauhaus-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/bauhaus-skill --skill bauhaus",
        category="design",
        tags=["design", "layout", "minimalist"],
        best_for=["Clean UI layouts", "Grid systems"],
        icon="📐",
    ),
    Skill(
        id="gradient-mesh",
        name="Gradient Mesh",
        description="Premium gradient generation for backgrounds, cards, buttons, and data "
                    "visualizations. Creates production-ready gradient palettes.",
        repo_url="https://github.com/wundercorp/gradient-mesh-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/gradient-mesh-skill --skill gradient-mesh",
        category="design",
        tags=["gradients", "visual", "palettes"],
        best_for=["Gradient backgrounds", "Visual polish"],
        icon="🌈",
    ),

    # ── Documentation ────────────────────────────────
    Skill(
        id="archivist",
        name="Archivist",
        description="Documentation generation and maintenance. Creates README, API docs, "
                    "changelogs, and keeps them in sync with code changes.",
        repo_url="https://github.com/wundercorp/archivist-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/archivist-skill --skill archivist",
        category="documentation",
        tags=["docs", "readme", "changelog"],
        best_for=["README generation", "API documentation"],
        icon="📚",
    ),

    # ── i18n ─────────────────────────────────────────
    Skill(
        id="linguist",
        name="Linguist",
        description="Multi-language internationalization. Manages translation files, locale "
                    "detection, RTL support, and i18n framework integration.",
        repo_url="https://github.com/wundercorp/linguist-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/linguist-skill --skill linguist",
        category="i18n",
        tags=["i18n", "translation", "locale", "rtl"],
        best_for=["Adding i18n support", "Managing translations"],
        icon="🌍",
    ),

    # ── Infra ────────────────────────────────────────
    Skill(
        id="mimar",
        name="Mimar",
        description="Cloud architecture and deployment planning. Designs scalable infrastructure "
                    "with Docker, Kubernetes, and cloud provider best practices.",
        repo_url="https://github.com/wundercorp/mimar-skill",
        install_cmd="npx --yes skills add https://github.com/wundercorp/mimar-skill --skill mimar",
        category="infra",
        tags=["docker", "kubernetes", "cloud", "deployment"],
        best_for=["Docker Compose setup", "Cloud deployment config"],
        icon="🏗️",
    ),
]

# Index by id for fast lookup
SKILL_MAP: dict[str, Skill] = {s.id: s for s in SKILLS}

# Map skills to development categories they enhance
SKILL_RECOMMENDATIONS: dict[str, list[str]] = {
    "code_structure": ["professional-developer", "coherence", "cleaner"],
    "testing": ["doctor", "svalbard"],
    "accessibility": ["contrast-guard", "accessibility"],
    "design": ["themable", "bauhaus", "gradient-mesh"],
    "documentation": ["archivist"],
    "i18n": ["linguist"],
    "infrastructure": ["mimar"],
    "api_integration": ["wiring"],
    "bugfixing": ["doctor", "patcher"],
}


class SkillsCatalog:
    """Provides access to the builderstudio-skills catalog."""

    @staticmethod
    def get_all() -> list[dict]:
        return [s.to_dict() for s in SKILLS]

    @staticmethod
    def get_by_id(skill_id: str) -> Optional[dict]:
        skill = SKILL_MAP.get(skill_id)
        return skill.to_dict() if skill else None

    @staticmethod
    def get_by_category(category: str) -> list[dict]:
        return [s.to_dict() for s in SKILLS if s.category == category]

    @staticmethod
    def get_categories() -> dict[str, str]:
        return dict(CATEGORIES)

    @staticmethod
    def recommend_for(area: str) -> list[dict]:
        """Get skill recommendations for a specific development area."""
        skill_ids = SKILL_RECOMMENDATIONS.get(area, [])
        return [SKILL_MAP[sid].to_dict() for sid in skill_ids if sid in SKILL_MAP]

    @staticmethod
    def search(query: str) -> list[dict]:
        """Search skills by name, description, or tags."""
        q = query.lower()
        results = []
        for s in SKILLS:
            if (q in s.name.lower() or q in s.description.lower() or
                any(q in t.lower() for t in s.tags) or
                any(q in b.lower() for b in s.best_for)):
                results.append(s.to_dict())
            # Also check category name
            cat_name = CATEGORIES.get(s.category, "").lower()
            if q in cat_name:
                if s.to_dict() not in results:
                    results.append(s.to_dict())
        return results
