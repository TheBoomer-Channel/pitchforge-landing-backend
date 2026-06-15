"""Token Budget — adaptive context management with section-aware truncation.

TASK-070 — Prevents large research/planning reports from saturating agent context.
Preserves markdown section headers and provides offsets for deferred reading.
"""

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Truncation thresholds by model size
PRUNE_THRESHOLDS = {
    "small":   {"max_tokens": 25000,  "trigger": 0.70, "floor": 10000},
    "medium":  {"max_tokens": 200000, "trigger": 0.65, "floor": 15000},
    "large":   {"max_tokens": 500000, "trigger": 0.60, "floor": 20000},
    "xlarge":  {"max_tokens": 1000000,"trigger": 0.55, "floor": 20000},
}

# Default model size for DeepSeek V4
DEFAULT_MODEL_SIZE = "large"


@dataclass
class TokenBudget:
    """Tracks token usage and determines pressure level for truncation."""
    max_tokens: int
    used_tokens: int = 0
    level: int = 0  # 0=normal, 1=attention, 2=warning, 3=critical
    floor: int = 20000  # Minimum tokens to preserve before critical rebuild

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def usable(self) -> int:
        """Usable tokens: max_tokens minus floor reserve."""
        return max(0, self.max_tokens - self.floor)

    @property
    def pressure(self) -> float:
        return self.used_tokens / max(self.max_tokens, 1)

    def consume(self, tokens: int) -> None:
        """Register token consumption."""
        self.used_tokens += tokens
        self._update_level()

    def _update_level(self) -> int:
        """Update pressure level based on usage ratio."""
        if self.pressure < 0.30:
            self.level = 0
        elif self.pressure < 0.50:
            self.level = 1
        elif self.pressure < 0.70:
            self.level = 2
        else:
            self.level = 3
        return self.level

    @classmethod
    def for_model(cls, model_size: str = DEFAULT_MODEL_SIZE) -> "TokenBudget":
        """Create a budget for a specific model size."""
        thresholds = PRUNE_THRESHOLDS.get(model_size, PRUNE_THRESHOLDS["large"])
        return cls(
            max_tokens=thresholds["max_tokens"],
            floor=thresholds["floor"],
        )


def estimate_tokens(text: str) -> int:
    """Fast token estimation: ~4 chars/token for text, ~2 for code.
    
    For English text, this is within ~15% of actual tokenizer count.
    For code-heavy content, it's within ~20%.
    """
    if not text:
        return 0
    
    # Detect code-heavy content (>10% of chars are code symbols)
    code_chars = sum(1 for c in text if c in '{}[]()<>;=+-*/%&|^!')
    if code_chars / max(len(text), 1) > 0.1:
        return len(text) // 2  # Code: ~2 chars/token
    return len(text) // 4  # Text: ~4 chars/token


def truncate_markdown(content: str, max_tokens: int) -> tuple[str, dict]:
    """Truncate markdown preserving section headers.
    
    Args:
        content: Markdown content to truncate
        max_tokens: Maximum tokens allowed
    
    Returns:
        (truncated_content, offsets_dict)
        offsets: { "## Section Name": {"start": 2400, "length": 800}, ... }
    """
    if not content:
        return content, {}

    current_tokens = estimate_tokens(content)
    if current_tokens <= max_tokens:
        return content, {}

    # Split by H2 headers (## Section)
    sections = re.split(r'(?=^## )', content, flags=re.MULTILINE)
    
    result_parts = []
    offsets = {}
    running_tokens = 0
    
    for section in sections:
        section_tokens = estimate_tokens(section)
        
        if section_tokens == 0:
            continue
            
        # Extract header
        header_line = section.split('\n')[0].strip()
        if not header_line.startswith('##'):
            # Non-header content (intro text) — always include
            result_parts.append(section)
            running_tokens += section_tokens
            continue
        
        if running_tokens + section_tokens <= max_tokens:
            # Full section fits
            result_parts.append(section)
            running_tokens += section_tokens
        elif running_tokens + 200 <= max_tokens:
            # Partial — keep header + 1 paragraph + offset hint
            lines = section.split('\n')
            header = lines[0]
            # Take first paragraph after header
            body_lines = []
            for line in lines[1:]:
                if line.strip() and not line.startswith('#'):
                    body_lines.append(line)
                if len(body_lines) >= 3 or estimate_tokens('\n'.join(body_lines)) > 150:
                    break
            
            truncated_section = '\n'.join([header] + body_lines[:3])
            truncated_section += f"\n\n> 📌 Esta sección tiene {section_tokens} tokens. Usa `?section={header_line.replace('## ', '').strip()}` para leerla completa.\n"
            
            offsets[header_line] = {
                "start": running_tokens,
                "length": section_tokens,
                "preview_tokens": estimate_tokens(truncated_section),
            }
            result_parts.append(truncated_section)
            running_tokens += estimate_tokens(truncated_section)
        else:
            # Budget exhausted — include header + offset hint so section is visible
            exhausted_section = header_line + f"\n\n> 📌 Budget agotado. Esta sección tiene {section_tokens} tokens. Usa `?section={header_line.replace('## ', '').strip()}` para leerla.\n"
            offsets[header_line] = {
                "start": running_tokens,
                "length": section_tokens,
                "preview_tokens": 0,
            }
            result_parts.append(exhausted_section)
    
    return ''.join(result_parts), offsets


def section_reader(content: str, section_name: str) -> str | None:
    """Read a specific section from truncated markdown content.
    
    Args:
        content: Full markdown content
        section_name: Section header name (without ## prefix)
    
    Returns:
        Section content or None if not found
    """
    if not content:
        return None
    
    # Escape special regex chars in section name
    escaped = re.escape(section_name)
    pattern = rf'^## {escaped}.*?(?=^## |\Z)'
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    
    return match.group(0) if match else None
