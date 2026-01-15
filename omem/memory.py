"""High-level Memory API for omem SDK.

This module provides a simplified, user-friendly interface for interacting
with the omem memory service. It wraps the low-level MemoryClient with
convenient methods and strongly-typed return values.

Design principles:
- Simple case: `add()` for one-line writes (auto-commit)
- Advanced case: `conversation()` with explicit `commit()` for batch control
- TKG capabilities exposed at tenant-level
- Strongly-typed return models
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .client import MemoryClient, OmemClientError
from .models import (
    AddResult,
    Entity,
    Event,
    EventContext,
    Evidence,
    ExtractedKnowledge,
    MemoryItem,
    SearchResult,
)
from .types import CanonicalTurnV1

# Default cloud service endpoint
DEFAULT_ENDPOINT = "https://zdfdulpnyaci.sealoshzh.site/api/v1/memory"


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse datetime from various formats."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        s = str(val).strip()
        if not s:
            return None
        # Handle ISO format with Z suffix
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _now_iso() -> str:
    """Return current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class Memory:
    """High-level Memory API for omem.

    Provides a simple interface for storing and retrieving conversational
    memories. Works with both cloud service (SaaS) and self-hosted deployments.

    Quick Start:
        >>> from omem import Memory
        >>> 
        >>> # Initialize (only api_key required!)
        >>> mem = Memory(api_key="qbk_xxx")
        >>> 
        >>> # Save conversation
        >>> mem.add("conv-001", [
        ...     {"role": "user", "content": "明天和 Caroline 去西湖"},
        ...     {"role": "assistant", "content": "好的，我记住了"},
        ... ])
        >>> 
        >>> # Search memories
        >>> result = mem.search("我什么时候去西湖？")
        >>> if result:
        ...     print(result.to_prompt())  # Formatted for LLM

    Design Principles:
        - Simple case: `add()` for one-line writes (fire-and-forget)
        - Search: `search()` returns strongly-typed results
        - Fail gracefully: Memory failures should not block agent conversations
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        """Initialize Memory client.

        Args:
            api_key: API key for authentication (required). Get yours at omnimemory.ai
            endpoint: Memory service URL. Defaults to cloud service.
                Override for self-hosted deployments.
            user_id: User identifier for multi-user isolation within your app.
                Use this to separate memories for different end users.
                If not provided, all memories are shared under your API key.
            timeout_s: Request timeout in seconds.
        """
        if not api_key:
            raise ValueError("api_key is required")

        self._api_key = str(api_key).strip()
        self._endpoint = str(endpoint or DEFAULT_ENDPOINT).rstrip("/")
        # NOTE: In SaaS mode, data isolation is at account level. The optional
        # user_id is accepted for future/backend-controlled isolation features
        # but does not currently affect SaaS data partitioning.
        self._user_id = str(user_id).strip() if user_id else None
        self._timeout_s = float(timeout_s)

        self._client = MemoryClient(
            base_url=self._endpoint,
            tenant_id="__from_api_key__",  # Gateway derives from api_key
            # SaaS mode: delegate user_tokens/client_meta to backend BFF
            memory_domain="dialog",
            api_token=self._api_key,
            timeout_s=self._timeout_s,
            mode="saas",
        )

    # ========== Write API ==========

    def add(
        self,
        conversation_id: str,
        messages: Sequence[Dict[str, Any]],
        *,
        wait: bool = False,
        timeout_s: float = 60.0,
    ) -> Optional["AddResult"]:
        """Save conversation messages to memory.

        This is the primary way to store conversations. Messages are sent to
        the server and processed asynchronously (typically ready for search
        within 5-30 seconds).

        Args:
            conversation_id: Unique identifier for the conversation.
            messages: List of messages in OpenAI format:
                [{"role": "user", "content": "Hello"}, ...]
                Supported fields: role, content (or text), name, timestamp
            wait: If True, wait for backend processing to complete.
            timeout_s: Timeout (seconds) when wait=True.

        Example:
            >>> mem.add("conv-001", [
            ...     {"role": "user", "content": "帮我订明天下午3点的会议室"},
            ...     {"role": "assistant", "content": "好的，已预订明天下午3点的会议室A"},
            ... ])

        Note:
            - Call once per conversation (not per message) to avoid fragmentation
            - Memories are searchable after backend processing completes
            - Fire-and-forget by default; pass wait=True to block until done
        """
        conv = self.conversation(conversation_id)
        for msg in messages:
            conv.add(msg)
        if wait:
            return conv.commit(wait=True, timeout_s=timeout_s)
        conv.commit()  # Fire and forget
        return None

    def conversation(
        self,
        conversation_id: str,
        *,
        sync_cursor: bool = True,
    ) -> "Conversation":
        """Create a conversation buffer for batch writes.

        Use this when you need fine-grained control over when to commit,
        or when adding messages incrementally.

        Args:
            conversation_id: Unique identifier for the conversation.
            sync_cursor: Whether to sync cursor from server (prevents duplicates).

        Returns:
            Conversation object for adding messages and committing.

        Example:
            >>> conv = mem.conversation("conv-001")
            >>> conv.add({"role": "user", "content": "First message"})
            >>> conv.add({"role": "assistant", "content": "Reply"})
            >>> conv.add({"role": "user", "content": "Second message"})
            >>> result = conv.commit()  # Commit all at once

            # Or use as context manager (auto-commit on exit)
            >>> with mem.conversation("conv-001") as conv:
            ...     conv.add({"role": "user", "content": "Hello"})
            ...     conv.add({"role": "assistant", "content": "Hi!"})
            # Auto-commits here
        """
        return Conversation(
            client=self._client,
            conversation_id=conversation_id,
            sync_cursor=sync_cursor,
            auto_timestamp=True,
        )

    # ========== Search API ==========

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        fail_silent: bool = False,
        debug: bool = False,
    ) -> SearchResult:
        """Search memories.

        Args:
            query: Search question (e.g., "我什么时候去西湖？")
            limit: Maximum number of results (default: 10)
            fail_silent: If True, return empty result on error instead of raising.
                Use this to ensure memory failures don't break your agent.
            debug: If True, include detailed debug info in the result.

        Returns:
            SearchResult with items and helper methods:
            - Truthy when results exist: `if result: ...`
            - Iterable: `for item in result: ...`
            - Formattable: `result.to_prompt()` for LLM injection

        Example:
            >>> result = mem.search("meeting with Caroline")
            >>> if result:
            ...     print(result.to_prompt())  # Inject into LLM context

            >>> # With fail_silent for robustness
            >>> result = mem.search("query", fail_silent=True)
            >>> # Returns empty SearchResult on error, never raises

            >>> # With debug info
            >>> result = mem.search("query", debug=True)
            >>> print(result.debug)  # See executed_calls, plan, etc.
        """
        t0 = time.perf_counter()
        try:
            resp = self._client.retrieve_dialog_v2(
                query=query,
                topk=limit,
                with_answer=False,
                debug=debug,
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            items: List[MemoryItem] = []
            for e in resp.get("evidence_details") or []:
                text = str(e.get("text") or "").strip()
                if not text:
                    continue
                # Prefer tkg_event_id (actual TKG event ID) over event_id (logical ID)
                # tkg_event_id is needed for get_evidence_for() to work with explain endpoint
                event_id = str(e.get("tkg_event_id") or e.get("event_id") or "").strip() or None
                items.append(
                    MemoryItem(
                        text=text,
                        score=float(e.get("score") or 0.0),
                        timestamp=_parse_datetime(e.get("timestamp")),
                        source=str(e.get("source") or "unknown"),
                        entities=list(e.get("entities") or []),
                        event_id=event_id,
                    )
                )

            return SearchResult(
                query=query,
                items=items,
                latency_ms=latency_ms,
                debug=resp.get("debug") if debug else None,
                strategy=resp.get("strategy"),
            )

        except Exception as exc:
            if fail_silent:
                return SearchResult(
                    query=query,
                    items=[],
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    error=f"{type(exc).__name__}: {str(exc)[:200]}",
                )
            # Let structured HTTP errors bubble up so callers can inspect
            # status_code / error codes. For SaaS, remember that data is
            # isolated at account level (not per user_id) by the backend.
            raise

    def debug_config(self) -> Dict[str, Any]:
        """Fetch effective backend configuration for this Memory client.

        This delegates to the underlying client's debug_config() helper, which
        calls the SaaS/backend debug endpoint. Not all deployments expose it;
        in that case an OmemHttpError (e.g., 404) will be raised.
        """
        return self._client.debug_config()

    # ========== TKG API (tenant-level) ==========

    def resolve_entity(
        self,
        name: str,
        *,
        entity_type: Optional[str] = None,
    ) -> Optional[Entity]:
        """Resolve entity by name.

        Note: TKG queries operate at tenant-level (no user isolation).

        Args:
            name: Entity name to resolve (e.g., "Caroline", "西湖").
            entity_type: Optional type filter ("person", "place", etc.).

        Returns:
            Entity if found, None otherwise.

        Example:
            >>> entity = mem.resolve_entity("Caroline")
            >>> if entity:
            ...     print(f"Found: {entity.name} ({entity.type})")
        """
        try:
            resp = self._client.graph_resolve_entities(
                name=name,
                entity_type=entity_type,
                limit=1,
            )
            items = resp.get("items") or []
            if not items:
                return None
            e = items[0]
            return Entity(
                id=str(e.get("entity_id") or e.get("id") or ""),
                name=str(e.get("name") or e.get("cluster_label") or name),
                type=str(e.get("type") or "unknown"),
                aliases=list(e.get("aliases") or []),
            )
        except Exception:
            return None

    # NOTE: get_entity_timeline() commented out to simplify SDK API.
    # Use get_evidence() instead. Uncomment when video support is added
    # and we need distinct timeline vs evidence views.
    #
    # def get_entity_timeline(
    #     self,
    #     entity: str,
    #     *,
    #     limit: int = 20,
    # ) -> List[Event]:
    #     """Get chronological timeline of events/activities for an entity."""
    #     resolved = self.resolve_entity(entity)
    #     if not resolved:
    #         return []
    #     try:
    #         resp = self._client.graph_entity_timeline(
    #             entity_id=resolved.id,
    #             limit=limit,
    #         )
    #         events: List[Event] = []
    #         for item in resp.get("items") or []:
    #             events.append(
    #                 Event(
    #                     id=str(item.get("evidence_id") or item.get("utterance_id") or item.get("id") or ""),
    #                     summary=str(item.get("text") or item.get("raw_text") or ""),
    #                     timestamp=_parse_datetime(
    #                         item.get("t_media_start") or item.get("timestamp")
    #                     ),
    #                     entities=[resolved.name],
    #                 )
    #             )
    #         return events
    #     except Exception:
    #         return []

    def get_entity_history(
        self,
        entity: str,
        *,
        limit: int = 10,
    ) -> List[Evidence]:
        """Get ALL utterances/evidences associated with an entity.

        This returns the raw source data that established facts about an entity:
        - For dialog: the original utterances where information was stated
        - For video: face detections, voice samples, visual observations

        Use this to:
        - Cite sources for agent claims ("You mentioned X on date Y")
        - Debug why the agent "knows" something
        - Build grounded, non-hallucinating responses

        Note: TKG queries operate at tenant-level (no user isolation).

        Args:
            entity: Entity name or ID.
            limit: Maximum evidences to return (default: 10, max: 200).

        Returns:
            List of Evidence objects with source text, ordered by time.

        Example:
            >>> history = mem.get_entity_history('Caroline', limit=5)
            >>> for e in history:
            ...     print(f"[{e.confidence:.2f}] {e.text}")
            ...     print(f"  Timestamp: {e.timestamp}")
        """
        resolved = self.resolve_entity(entity)
        if not resolved:
            return []

        try:
            # The timeline endpoint returns BOTH Evidence and UtteranceEvidence
            # unified into a single response with 'kind' field
            resp = self._client.graph_entity_timeline(
                entity_id=resolved.id,
                limit=limit,
            )
            evidences: List[Evidence] = []
            for item in resp.get("items") or []:
                evidence_id = str(
                    item.get("evidence_id")
                    or item.get("utterance_id")
                    or item.get("id")
                    or ""
                )
                text = str(item.get("text") or item.get("raw_text") or "")
                # Use confidence from response, default to 0.9 for utterances
                confidence = float(item.get("confidence") or 0.9)
                timestamp = _parse_datetime(
                    item.get("t_media_start") or item.get("timestamp")
                )
                segment_id = (
                    str(item.get("segment_id")) if item.get("segment_id") else None
                )

                evidences.append(
                    Evidence(
                        id=evidence_id,
                        text=text,
                        entity_id=resolved.id,
                        confidence=confidence,
                        timestamp=timestamp,
                        segment_id=segment_id,
                    )
                )

            return evidences
        except Exception:
            return []

    def get_evidence_for(self, item: MemoryItem) -> List[Evidence]:
        """Get source evidence for a specific search result.

        This answers: \"Where did THIS fact come from?\" for a given MemoryItem.

        The MemoryItem must have an event_id populated by the retrieval backend.
        When unavailable, this method returns an empty list.

        Args:
            item: MemoryItem from mem.search() results.

        Returns:
            List of Evidence objects derived from the event's evidence chain.
        """
        from .models import Evidence as _EvidenceModel  # avoid circulars in type checkers

        eid = str(getattr(item, "event_id", None) or "").strip()
        if not eid:
            return []

        try:
            resp = self._client.graph_explain_event(eid)
        except Exception:
            return []

        data = resp.get("item") or resp
        if not isinstance(data, dict):
            return []

        evidences: List[Evidence] = []

        # Prefer utterance-level evidence when available (dialog data)
        utterances = data.get("utterances") or []
        for u in utterances:
            text = str(u.get("raw_text") or u.get("text") or "")
            if not text:
                continue
            evidence_id = str(u.get("id") or "")
            timestamp = _parse_datetime(u.get("t_media_start") or u.get("timestamp"))
            segment_id = str(u.get("segment_id")) if u.get("segment_id") else None

            evidences.append(
                _EvidenceModel(  # type: ignore[call-arg]
                    id=evidence_id,
                    text=text,
                    entity_id="",  # entity is implicit in the event; leave empty for now
                    confidence=float(u.get("confidence") or 0.0),
                    timestamp=timestamp,
                    segment_id=segment_id,
                )
            )

        # Fallback: use generic evidences array if utterances are missing
        if not evidences:
            for ev in data.get("evidences") or []:
                text = str(ev.get("text") or "")
                if not text:
                    continue
                evidence_id = str(ev.get("id") or "")
                timestamp = _parse_datetime(ev.get("t_media_start") or ev.get("timestamp"))
                segment_id = str(ev.get("segment_id")) if ev.get("segment_id") else None

                evidences.append(
                    _EvidenceModel(  # type: ignore[call-arg]
                        id=evidence_id,
                        text=text,
                        entity_id="",
                        confidence=float(ev.get("confidence") or 0.0),
                        timestamp=timestamp,
                        segment_id=segment_id,
                    )
                )

        return evidences

    def explain_event(self, item: MemoryItem) -> Optional["EventContext"]:
        """Get full TKG context for a search result - the real value of extraction.

        This returns everything the TKG learned from the source utterance:
        - entities: Who/what was mentioned (e.g., "Caroline (PERSON)")
        - knowledge: Structured facts extracted (e.g., "Caroline went to support group on 2026-01-14")
        - places: Locations mentioned
        - utterances: Original source text
        - temporal context: When this occurred

        The MemoryItem must have an event_id (source: E_graph). Vector-only results
        (source: E_vec) don't have TKG nodes and will return None.

        Args:
            item: MemoryItem from mem.search() results.

        Returns:
            EventContext with full TKG data, or None if not available.

        Example:
            >>> result = mem.search("Caroline support group", limit=1)
            >>> ctx = mem.explain_event(result.items[0])
            >>> if ctx:
            ...     print(f"Entities: {ctx.entities}")
            ...     for k in ctx.knowledge:
            ...         print(f"Fact: {k.summary}")
        """
        from .models import EventContext, ExtractedKnowledge

        eid = str(getattr(item, "event_id", None) or "").strip()
        if not eid:
            return None

        try:
            resp = self._client.graph_explain_event(eid)
        except Exception:
            return None

        data = resp.get("item") or resp
        if not isinstance(data, dict):
            return None

        # Extract entities
        entities: List[str] = []
        for ent in data.get("entities") or []:
            name = ent.get("name", "")
            etype = ent.get("type", "")
            if name:
                entities.append(f"{name} ({etype})" if etype else name)

        # Extract knowledge (structured facts)
        knowledge: List[ExtractedKnowledge] = []
        for k in data.get("knowledge") or []:
            summary = k.get("summary") or k.get("text") or ""
            if summary:
                knowledge.append(
                    ExtractedKnowledge(
                        id=str(k.get("id") or ""),
                        summary=summary,
                        importance=float(k.get("importance") or 0.5),
                        timestamp=_parse_datetime(k.get("t_abs_start")),
                    )
                )

        # Extract places
        places: List[str] = []
        for p in data.get("places") or []:
            name = p.get("name", "")
            if name:
                places.append(name)

        # Extract source utterances
        utterances: List[str] = []
        for u in data.get("utterances") or []:
            text = u.get("raw_text") or u.get("text") or ""
            if text:
                utterances.append(text)

        # Get event summary and timestamp
        event = data.get("event") or {}
        summary = event.get("summary") or item.text
        timestamp = _parse_datetime(event.get("t_abs_start"))

        # Get session kind from timeslices
        session_kind = None
        timeslices = data.get("timeslices") or []
        if timeslices:
            session_kind = timeslices[0].get("kind")

        return EventContext(
            event_id=eid,
            summary=summary,
            entities=entities,
            knowledge=knowledge,
            places=places,
            utterances=utterances,
            timestamp=timestamp,
            session_kind=session_kind,
        )

    def search_events(
        self,
        query: str,
        *,
        time_range: Optional[Tuple[datetime, datetime]] = None,
        entities: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Event]:
        """Search events using fulltext/BM25.

        Note: TKG queries operate at tenant-level (no user isolation).

        Args:
            query: Search query.
            time_range: Optional (start, end) datetime filter.
            entities: Optional entity name filter.
            limit: Maximum number of results.

        Returns:
            List of Event objects.

        Example:
            >>> events = mem.search_events("meeting", limit=10)
            >>> events = mem.search_events("trip", entities=["Caroline"])
        """
        try:
            # If entities specified, filter by them
            if entities:
                # Resolve first entity and use graph_list_events
                resolved = self.resolve_entity(entities[0])
                if resolved:
                    resp = self._client.graph_list_events(
                        entity_id=resolved.id,
                        limit=limit,
                    )
                    items = resp.get("items") or []
                else:
                    items = []
            else:
                resp = self._client.graph_search_events(
                    query=query,
                    topk=limit,
                )
                items = resp.get("events") or resp.get("items") or []

            events: List[Event] = []
            for item in items:
                events.append(
                    Event(
                        id=str(item.get("id") or ""),
                        summary=str(item.get("summary") or ""),
                        timestamp=_parse_datetime(
                            item.get("t_abs_start") or item.get("timestamp")
                        ),
                        entities=list(item.get("involves") or []),
                        evidence=str(item.get("evidence") or item.get("text") or ""),
                    )
                )
            return events
        except Exception:
            return []

    def get_events_by_time(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int = 50,
    ) -> List[Event]:
        """Get events within a time range.

        Note: TKG queries operate at tenant-level (no user isolation).

        Args:
            start: Start datetime.
            end: End datetime.
            limit: Maximum number of results.

        Returns:
            List of Event objects.

        Example:
            >>> from datetime import datetime, timedelta
            >>> now = datetime.now()
            >>> events = mem.get_events_by_time(now - timedelta(days=7), now)
        """
        try:
            # Get timeslices in range
            resp = self._client.graph_timeslices_range(
                start=start.isoformat(),
                end=end.isoformat(),
                limit=limit,
            )
            timeslices = resp.get("items") or []

            events: List[Event] = []
            for ts in timeslices[:10]:  # Limit timeslice queries
                ts_id = ts.get("id")
                if not ts_id:
                    continue
                try:
                    ts_resp = self._client.graph_timeslice_events(
                        timeslice_id=ts_id,
                        limit=limit // 10 + 1,
                    )
                    for item in ts_resp.get("items") or []:
                        events.append(
                            Event(
                                id=str(item.get("id") or ""),
                                summary=str(item.get("summary") or ""),
                                timestamp=_parse_datetime(
                                    item.get("t_abs_start") or ts.get("t_abs_start")
                                ),
                                entities=list(item.get("involves") or []),
                            )
                        )
                except Exception:
                    continue

            return events[:limit]
        except Exception:
            return []

    # ========== Lifecycle ==========

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class Conversation:
    """Buffer for batch message writes with explicit commit control.

    This class accumulates messages in a local buffer and sends them
    to the server only when `commit()` is called.

    Benefits:
    - Batch writes reduce graph mutations
    - Control over when data is persisted
    - Cursor sync prevents duplicate writes after process restart
    """

    def __init__(
        self,
        client: MemoryClient,
        conversation_id: str,
        sync_cursor: bool = True,
        auto_timestamp: bool = True,
    ) -> None:
        """Initialize conversation buffer.

        Args:
            client: MemoryClient instance.
            conversation_id: Unique identifier for the conversation.
            sync_cursor: Whether to sync cursor from server.
            auto_timestamp: If True, auto-generate timestamp for messages
                without explicit timestamp. Defaults to True.
        """
        cid = str(conversation_id or "").strip()
        if not cid:
            raise ValueError("conversation_id is required")

        self._client = client
        self._conversation_id = cid
        self._buffer: List[CanonicalTurnV1] = []
        self._next_turn_index = 1
        self._cursor_last_committed: Optional[str] = None
        self._auto_timestamp = bool(auto_timestamp)

        if sync_cursor:
            self._sync_cursor_from_server()

    def _sync_cursor_from_server(self) -> None:
        """Sync cursor from server to prevent duplicate writes."""
        try:
            ss = self._client.get_session(self._conversation_id)
            self._cursor_last_committed = ss.cursor_committed
            if (
                ss.cursor_committed
                and ss.cursor_committed.startswith("t")
                and ss.cursor_committed[1:].isdigit()
            ):
                idx = int(ss.cursor_committed[1:])
                self._next_turn_index = max(self._next_turn_index, idx + 1)
        except Exception:
            # Session may not exist yet; cursor sync is best-effort
            pass

    def _turn_id_from_index(self, i: int) -> str:
        """Generate turn ID from index."""
        return f"t{i:04d}"

    def add(self, message: Dict[str, Any]) -> None:
        """Add a message to the buffer.

        Does NOT send to server until `commit()` is called.

        Args:
            message: Message dict with at least "role" and "content" (or "text").
                Supported fields:
                - role: "user", "assistant", "tool", or "system"
                - content or text: Message content
                - name: Optional speaker name
                - timestamp: Optional ISO timestamp (auto-generated if auto_timestamp=True)

        Example:
            >>> conv.add({"role": "user", "content": "Hello"})
            >>> conv.add({"role": "assistant", "content": "Hi there!"})
        """
        role = str(message.get("role") or "user").strip().lower()
        if role not in ("user", "assistant", "tool", "system"):
            raise ValueError("role must be one of: user, assistant, tool, system")

        # Support both "content" (OpenAI) and "text" (omem)
        text = str(
            message.get("content") or message.get("text") or message.get("message") or ""
        )
        if not text.strip():
            raise ValueError("message content/text is empty")

        turn_id = self._turn_id_from_index(self._next_turn_index)
        self._next_turn_index += 1

        # Handle timestamp: use provided, or auto-generate if auto_timestamp is enabled
        timestamp_iso = message.get("timestamp") or message.get("timestamp_iso")
        if timestamp_iso:
            timestamp_iso = str(timestamp_iso).strip()
        elif self._auto_timestamp:
            timestamp_iso = _now_iso()

        turn = CanonicalTurnV1(
            turn_id=turn_id,
            role=role,  # type: ignore[arg-type]
            text=text,
            name=str(message.get("name")).strip() if message.get("name") else None,
            timestamp_iso=timestamp_iso if timestamp_iso else None,
        )
        self._buffer.append(turn)

    def commit(
        self,
        *,
        wait: bool = False,
        timeout_s: float = 60.0,
    ) -> AddResult:
        """Commit buffered messages to the server.

        Args:
            wait: Whether to wait for server processing to complete.
            timeout_s: Timeout for waiting.

        Returns:
            AddResult with conversation_id, message_count, job_id, completed.
        """
        if not self._buffer:
            return AddResult(
                conversation_id=self._conversation_id,
                message_count=0,
                completed=True,
            )

        # Only submit delta (messages after cursor)
        delta = self._get_delta_turns()
        if not delta:
            return AddResult(
                conversation_id=self._conversation_id,
                message_count=0,
                completed=True,
            )

        handle = self._client.ingest_dialog_v1(
            session_id=self._conversation_id,
            turns=delta,
            base_turn_id=self._cursor_last_committed,
        )

        # Update cursor
        self._cursor_last_committed = delta[-1].turn_id

        completed = False
        if wait and handle.job_id:
            status = handle.wait(timeout_s=timeout_s)
            completed = str(status.status).upper() == "COMPLETED"

        # Clear buffer after successful commit
        self._buffer.clear()

        return AddResult(
            conversation_id=self._conversation_id,
            message_count=len(delta),
            job_id=handle.job_id if handle.job_id else None,
            completed=completed,
        )

    def _get_delta_turns(self) -> List[CanonicalTurnV1]:
        """Get turns that haven't been committed yet."""
        base = str(self._cursor_last_committed or "").strip()
        if not base:
            return list(self._buffer)
        return [t for t in self._buffer if t.turn_id > base]

    def __enter__(self) -> "Conversation":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Auto-commit on exit if no exception occurred."""
        if exc_type is None and self._buffer:
            self.commit()


__all__ = [
    "Memory",
    "Conversation",
]

