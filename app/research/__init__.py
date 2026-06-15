"""Research module — import sources to trigger auto-registration."""

# Import all source modules to trigger __init_subclass__ registration
from .sources import tavily_source
from .sources import reddit_source
from .sources import hn_source
from .sources import github_source
from .sources import wikipedia_source
from .sources import brave_source
from .sources import duckduckgo_source

# Re-export main classes
from .engine import ResearchEngine
from .http_client import ResearchHTTPClient
from .models import (
    ResearchReport, Competitor, MarketValidation, MarketSizing,
    OpportunityGap, ResearchProgress, BaseSourceResult,
)
from .report import ReportSynthesizer
from .base_source import BaseSource, list_sources, get_source, get_enabled_sources

# BoomerDev methodology integration
from .methodology import (
    evaluate_idea, filter_from_research, format_filter_report, IdeaFilterResult,
)
from .competitor_framework import (
    CompetitorProfile, build_profile_from_research,
    format_profile_report, get_research_sources_guide,
)

__all__ = [
    "ResearchEngine",
    "ResearchHTTPClient",
    "ReportSynthesizer",
    "ResearchReport",
    "Competitor",
    "MarketValidation",
    "MarketSizing",
    "OpportunityGap",
    "ResearchProgress",
    "BaseSourceResult",
    "BaseSource",
    "list_sources",
    "get_source",
    "get_enabled_sources",
    # Methodology
    "evaluate_idea",
    "filter_from_research",
    "format_filter_report",
    "IdeaFilterResult",
    # Competitor framework
    "CompetitorProfile",
    "build_profile_from_research",
    "format_profile_report",
    "get_research_sources_guide",
]
