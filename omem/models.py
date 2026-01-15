"""Strongly-typed return models for omem SDK.

These dataclasses provide type-safe, IDE-friendly return values
for Memory class methods, replacing raw Dict responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class MemoryItem:
    """A single memory item from search results."""

    text: str
    score: float = 0.0
    timestamp: Optional[datetime] = None
    source: str = "unknown"
    entities: List[str] = field(default_factory=list)
    # Optional logical event identifier from TKG-backed retrieval.
    # When present, this can be used with get_evidence_for() to fetch
    # a structured evidence chain for this specific memory item.
    event_id: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.score:.2f}] {self.text}"


@dataclass
class SearchResult:
    """Search result containing memory items."""

    query: str
    items: List[MemoryItem]
    latency_ms: float = 0.0
    error: Optional[str] = None  # For fail_silent mode
    debug: Optional[Dict[str, Any]] = None  # Debug info when debug=True
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
class Entity:
    """An entity from the TKG (Temporal Knowledge Graph)."""

    id: str
    name: str
    type: str
    aliases: List[str] = field(default_factory=list)


@dataclass
class Event:
    """An event from the TKG (Temporal Knowledge Graph)."""

    id: str
    summary: str
    timestamp: Optional[datetime] = None
    entities: List[str] = field(default_factory=list)
    evidence: Optional[str] = None


@dataclass
class Evidence:
    """Evidence linking knowledge to source utterance."""

    id: str
    text: str  # The original utterance text
    entity_id: str  # Entity this evidence belongs to
    confidence: float = 0.0  # Extraction confidence
    timestamp: Optional[datetime] = None
    segment_id: Optional[str] = None  # Media segment if from video


@dataclass
class ExtractedKnowledge:
    """A structured fact extracted by TKG from raw utterances."""

    id: str
    summary: str  # The extracted fact (e.g., "Caroline went to support group on 2026-01-14")
    importance: float = 0.5
    timestamp: Optional[datetime] = None


@dataclass
class EventContext:
    """Full TKG context for an event - the value extracted from raw data.
    
    This represents everything the TKG learned from an utterance:
    - entities: Who/what was mentioned
    - knowledge: Structured facts extracted
    - places: Locations mentioned
    - utterances: Original source text
    - timestamp: When this occurred
    """

    event_id: str
    summary: str  # Event summary (often the original utterance)
    entities: List[str] = field(default_factory=list)  # Entity names
    knowledge: List[ExtractedKnowledge] = field(default_factory=list)  # Extracted facts
    places: List[str] = field(default_factory=list)  # Location names
    utterances: List[str] = field(default_factory=list)  # Source utterance texts
    timestamp: Optional[datetime] = None
    session_kind: Optional[str] = None  # e.g., "dialog_session"


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
    "ExtractedKnowledge",
    "EventContext",
    "Entity",
    "Event",
    "Evidence",
    "AddResult",
]

