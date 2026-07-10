"""High-level Memory API for omem SDK.

This module provides a simplified, user-friendly interface for interacting
with the omem memory service. It wraps the low-level MemoryClient with
convenient methods and strongly-typed return values.

Design principles:
- Simple case: `add()` for one-line writes (auto-commit)
- Advanced case: `conversation()` with explicit `commit()` for batch control
- Graph/TKG helper methods are disabled until the public API exposes device-scoped routes
- Strongly-typed return models
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .client import MemoryClient
from .models import (
    AddResult,
    MemoryItem,
    SearchResult,
)
from .types import CanonicalTurnV1

# Default cloud service endpoint
DEFAULT_ENDPOINT = "https://api.omnimemory.cn/api/v2/memory"


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
        device_no: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        """Initialize Memory client.

        Args:
            api_key: API key for authentication (required). Get yours at omnimemory.ai
            endpoint: OmniMemory-compatible gateway URL. Defaults to the cloud service.
            device_no: Optional customer-defined device number. When provided,
                search() uses the hybrid device-scoped retrieval endpoint.
            timeout_s: Request timeout in seconds.
        """
        if not api_key:
            raise ValueError("api_key is required")

        self._api_key = str(api_key).strip()
        self._endpoint = str(endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self._device_no = str(device_no).strip() if device_no else None
        self._timeout_s = float(timeout_s)

        self._client = MemoryClient(
            base_url=self._endpoint,
            tenant_id="__from_api_key__",  # Gateway derives from api_key
            # SaaS mode: delegate user_tokens/client_meta to backend BFF
            memory_domain="dialog",
            api_token=self._api_key,
            device_no=self._device_no,
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
    ) -> "Conversation":
        """Create a conversation buffer for batch writes.

        Use this when you need fine-grained control over when to commit,
        or when adding messages incrementally.

        Args:
            conversation_id: Unique identifier for the conversation.
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
            auto_timestamp=True,
        )

    # ========== Search API ==========

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        session_id: Optional[str] = None,
        fail_silent: bool = False,
    ) -> SearchResult:
        """Search memories.

        Args:
            query: Search question (e.g., "我什么时候去西湖？")
            limit: Maximum number of results (default: 10)
            session_id: Optional conversation/session ID to filter results.
                When provided, only memories from that specific session are returned.
                Use this for multi-tenant apps or to scope retrieval to a conversation.
            fail_silent: If True, return empty result on error instead of raising.
                Use this to ensure memory failures don't break your agent.

        Returns:
            SearchResult with items and helper methods:
            - Truthy when results exist: `if result: ...`
            - Iterable: `for item in result: ...`
            - Formattable: `result.to_prompt()` for LLM injection

        Example:
            >>> result = mem.search("meeting with Caroline")
            >>> if result:
            ...     print(result.to_prompt())  # Inject into LLM context

            >>> # Filter by session/conversation
            >>> result = mem.search("project details", session_id="project-alpha")
            >>> # Only returns memories from "project-alpha" session

            >>> # With fail_silent for robustness
            >>> result = mem.search("query", fail_silent=True)
            >>> # Returns empty SearchResult on error, never raises

        """
        t0 = time.perf_counter()
        try:
            if self._device_no:
                resp = self._client.retrieve_dialog_hybrid(
                    query=query,
                    session_id=session_id,
                    top_k=limit,
                    device_no=None,
                )
            else:
                resp = self._client.retrieve_dialog_v2(
                    query=query,
                    session_id=session_id,
                    topk=limit,
                    with_answer=False,
                )
            return self._search_result_from_response(
                query=query,
                resp=resp,
                latency_ms=(time.perf_counter() - t0) * 1000,
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
            # status_code and error codes.
            raise

    def search_hybrid(
        self,
        query: str,
        *,
        device_no: Optional[str] = None,
        limit: int = 10,
        session_id: Optional[str] = None,
        fail_silent: bool = False,
    ) -> SearchResult:
        """Search device-scoped memories through the hybrid retrieval endpoint."""
        effective_device_no = str(device_no or self._device_no or "").strip()
        if not effective_device_no:
            raise ValueError("device_no is required for hybrid retrieval")

        t0 = time.perf_counter()
        try:
            resp = self._client.retrieve_dialog_hybrid(
                query=query,
                session_id=session_id,
                top_k=limit,
                device_no=effective_device_no,
            )
            return self._search_result_from_response(
                query=query,
                resp=resp,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            if fail_silent:
                return SearchResult(
                    query=query,
                    items=[],
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    error=f"{type(exc).__name__}: {str(exc)[:200]}",
                )
            raise

    def _search_result_from_response(
        self,
        *,
        query: str,
        resp: Dict[str, Any],
        latency_ms: float,
    ) -> SearchResult:
        items: List[MemoryItem] = []
        for e in resp.get("evidence_details") or []:
            text = str(e.get("text") or "").strip()
            if not text:
                continue
            items.append(
                MemoryItem(
                    text=text,
                    score=float(e.get("score") or 0.0),
                    timestamp=_parse_datetime(e.get("timestamp")),
                    source=str(e.get("source") or "unknown"),
                    entities=list(e.get("entities") or []),
                )
            )

        return SearchResult(
            query=query,
            items=items,
            latency_ms=latency_ms,
            strategy=resp.get("strategy"),
        )

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
    - Batch writes reduce request overhead
    - Control over when data is persisted
    """

    def __init__(
        self,
        client: MemoryClient,
        conversation_id: str,
        auto_timestamp: bool = True,
    ) -> None:
        """Initialize conversation buffer.

        Args:
            client: MemoryClient instance.
            conversation_id: Unique identifier for the conversation.
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
