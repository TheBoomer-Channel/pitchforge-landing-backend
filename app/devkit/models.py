"""DevKit models — data structures for Active Learning system.

TASK-069 — Models for error tracking, lessons, patterns, and briefings.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ParsedError(BaseModel):
    """Parsed error from stack trace or build output."""
    error_type: str  # "TS2307", "AssertionError", "ECONNREFUSED", ...
    category: str  # build_error | test_failure | runtime_error | config | security | dependency
    file_path: str = ""
    line_number: int = 0
    message: str = ""
    framework: str = ""  # fastapi | react | pytest | docker | tsc
    stack_summary: list[dict] = Field(default_factory=list)


class Lesson(BaseModel):
    """A lesson learned from an error or correction."""
    id: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    category: str  # Same categories as ParsedError
    error_type: str
    message: str
    file_path: str = ""
    project: str = "startup-factory"
    root_cause: str = ""
    fix_applied: str = ""
    rule_suggestion: str = ""
    tags: list[str] = Field(default_factory=list)


class Pattern(BaseModel):
    """A recurring error pattern detected across sessions."""
    category: str
    error_type: str
    occurrences: int
    projects: list[str] = Field(default_factory=list)
    last_error: Optional[ParsedError] = None
    suggestion: str = ""  # "¿Añadir regla al AGENTS.md?"


class Briefing(BaseModel):
    """Session briefing with lessons, patterns, and tips."""
    total_lessons: int = 0
    new_since_yesterday: int = 0
    trend: str = "stable"  # improving | stable | degrading
    patterns: list[Pattern] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
