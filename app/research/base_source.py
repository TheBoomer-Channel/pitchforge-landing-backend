"""Abstract base class for all research sources.

To add a new data source:
1. Create a new file in sources/ (e.g., `twitter_source.py`)
2. Subclass `BaseSource` and implement `async def search(self, query, context)`
3. Register it by adding to the `__init_subclass__` hook or the registry dict.

Each source is auto-discovered at import time via `__init_subclass__`.
"""

from abc import ABC, abstractmethod
from typing import ClassVar, Optional

from .models import BaseSourceResult


# ── Auto-Registry ───────────────────────────────────────
_source_registry: dict[str, type["BaseSource"]] = {}


def get_source(name: str) -> Optional[type["BaseSource"]]:
    """Look up a source class by its name."""
    return _source_registry.get(name)


def list_sources() -> list[str]:
    """Return all registered source names."""
    return list(_source_registry.keys())


def get_enabled_sources() -> list[str]:
    """Return names of sources that are enabled."""
    return [name for name, cls in _source_registry.items() if cls.enabled]


# ── Base Class ──────────────────────────────────────────

class BaseSource(ABC):
    """Extend this class and it auto-registers."""

    # Override in subclass
    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    enabled: ClassVar[bool] = True
    
    # How many parallel requests this source can handle
    max_concurrency: ClassVar[int] = 5
    
    # Priority: lower = runs first (0 = blocking for report)
    priority: ClassVar[int] = 10

    def __init_subclass__(cls, **kwargs):
        """Auto-register any concrete subclass."""
        super().__init_subclass__(**kwargs)
        if cls.name != "base" and not cls.__name__.startswith("_"):
            existing = _source_registry.get(cls.name)
            if existing:
                raise ValueError(
                    f"Source name conflict: '{cls.name}' already registered "
                    f"by {existing.__module__}.{existing.__qualname__}"
                )
            _source_registry[cls.name] = cls

    def __init__(self, http_client=None):
        self._http = http_client

    @abstractmethod
    async def search(self, query: str, context: Optional[dict] = None) -> BaseSourceResult:
        """Execute a search against this source.

        Args:
            query: The idea/concept to research.
            context: Optional dict with extra params (target_market, etc.)

        Returns:
            BaseSourceResult with structured data.
        """
        ...

    def format_for_report(self, result: BaseSourceResult) -> dict:
        """Convert raw result to report-friendly dict.
        
        Override if source returns special data shapes.
        """
        return {
            "source": self.name,
            "success": result.success,
            "count": len(result.data),
            "data": result.data,
            "metadata": result.raw_metadata,
        }

    @classmethod
    def validate_config(cls) -> tuple[bool, str]:
        """Check if source has everything it needs to run.
        
        Returns: (is_ready, message)
        """
        return True, "ok"
