"""Research sources — import triggers auto-registration via __init_subclass__."""
from . import tavily_source
from . import reddit_source
from . import hn_source
from . import github_source
from . import wikipedia_source
from . import brave_source
from . import duckduckgo_source
from . import perplexity_source

__all__ = [
    "tavily_source",
    "reddit_source",
    "hn_source",
    "github_source",
    "wikipedia_source",
    "brave_source",
    "duckduckgo_source",
    "perplexity_source",
]
