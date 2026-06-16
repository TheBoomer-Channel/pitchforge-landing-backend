"""Briefing Engine — generates session briefings from lessons and patterns.

TASK-069 — Proactive briefing at session start with patterns, tips, and trends.
"""

import logging
from datetime import datetime, timedelta
from collections import Counter


from .models import Lesson, Pattern, Briefing

logger = logging.getLogger(__name__)


class BriefingEngine:
    """Generates session briefings from stored lessons and patterns."""

    def __init__(self):
        self._lessons: list[Lesson] = []

    def load_lessons(self, lessons: list[Lesson]) -> None:
        """Load lessons from storage for briefing generation."""
        self._lessons = lessons

    def generate(self) -> Briefing:
        """Generate a session briefing from loaded lessons."""
        now = datetime.utcnow()
        recent = [ls for ls in self._lessons if ls.timestamp > now - timedelta(days=7)]
        yesterday = [ls for ls in self._lessons if ls.timestamp > now - timedelta(days=1)]

        # Detect patterns (same category + error_type appearing >= 3 times)
        patterns = self._detect_patterns(recent, min_occurrences=3)

        # Generate tips from recent lessons
        tips = self._generate_tips(recent[:10])

        # Compute trend
        trend = self._compute_trend(recent)

        return Briefing(
            total_lessons=len(self._lessons),
            new_since_yesterday=len(yesterday),
            trend=trend,
            patterns=patterns,
            tips=tips,
        )

    def _detect_patterns(
        self, lessons: list[Lesson], min_occurrences: int = 3
    ) -> list[Pattern]:
        """Detect recurring error patterns."""
        key_counter = Counter()
        for lesson in lessons:
            key = (lesson.category, lesson.error_type)
            key_counter[key] += 1

        patterns = []
        for (category, error_type), count in key_counter.items():
            if count >= min_occurrences:
                matching = [
                    ls for ls in lessons
                    if ls.category == category and ls.error_type == error_type
                ]
                projects = list(set(ls.project for ls in matching))
                patterns.append(Pattern(
                    category=category,
                    error_type=error_type,
                    occurrences=count,
                    projects=projects,
                    last_error=None,  # Would need ParsedError from stored error
                    suggestion=f"Patrón '{error_type}' ×{count} en {', '.join(projects[:3])}. ¿Agregar regla?",
                ))

        return sorted(patterns, key=lambda p: p.occurrences, reverse=True)

    def _generate_tips(self, recent: list[Lesson]) -> list[str]:
        """Generate actionable tips from recent lessons."""
        tips = []
        seen = set()
        for lesson in recent[:5]:
            if lesson.rule_suggestion and lesson.rule_suggestion not in seen:
                tips.append(f"💡 {lesson.rule_suggestion}")
                seen.add(lesson.rule_suggestion)

        if not tips and recent:
            # Fallback: generate tips from categories
            cat_counter = Counter(ls.category for ls in recent)
            top_cat = cat_counter.most_common(1)[0][0]
            tips.append(f"📊 Categoría más frecuente esta semana: {top_cat} ({cat_counter[top_cat]} errores)")

        return tips

    def _compute_trend(self, recent: list[Lesson]) -> str:
        """Compute error trend: improving | stable | degrading."""
        if len(recent) < 4:
            return "stable"

        now = datetime.utcnow()
        timestamps = [ls.timestamp for ls in recent]
        # Split into first half and second half
        mid = min(timestamps) + (now - min(timestamps)) / 2
        first_half = [ls for ls in recent if ls.timestamp <= mid]
        second_half = [ls for ls in recent if ls.timestamp > mid]

        if len(first_half) == 0 or len(second_half) == 0:
            return "stable"

        ratio = len(second_half) / max(len(first_half), 1)
        if ratio < 0.7:
            return "improving"
        elif ratio > 1.3:
            return "degrading"
        return "stable"
