"""Strongly-typed return models for the MemAura SDK.

These dataclasses provide type-safe, IDE-friendly return values
for Memory class methods, replacing raw Dict responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, List, Optional


@dataclass
class MemoryItem:
    """A single memory item from search results."""

    text: str
    score: float = 0.0
    timestamp: Optional[datetime] = None
    source: str = "unknown"
    entities: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"[{self.score:.2f}] {self.text}"


@dataclass
class SearchResult:
    """Search result containing memory items."""

    query: str
    items: List[MemoryItem]
    latency_ms: float = 0.0
    error: Optional[str] = None  # For fail_silent mode
    strategy: Optional[str] = None  # Strategy used (dialog_v1, dialog_v2)

    def __iter__(self) -> Iterator[MemoryItem]:
        return iter(self.items)

    def __bool__(self) -> bool:
        return len(self.items) > 0

    def __len__(self) -> int:
        return len(self.items)

    def to_prompt(self, max_items: int = 5) -> str:
        """Format search results for LLM prompt injection.

        Args:
            max_items: Maximum number of items to include.

        Returns:
            Formatted string suitable for LLM context.
        """
        if not self.items:
            return ""
        lines = []
        for i, item in enumerate(self.items[:max_items], 1):
            lines.append(f"{i}. {item.text}")
        return "\n".join(lines)


@dataclass
class AddResult:
    """Result of adding messages to memory."""

    conversation_id: str
    message_count: int
    job_id: Optional[str] = None
    completed: bool = False


__all__ = [
    "MemoryItem",
    "SearchResult",
    "AddResult",
]
