"""High-level Memory API for the MemAura SDK.

This module provides a simplified, user-friendly interface for interacting
with the MemAura memory service. It wraps the low-level MemoryClient with
convenient methods and strongly-typed return values.

Design principles:
- Simple case: `add()` for one-line writes (auto-commit)
- Advanced case: `conversation()` with explicit `commit()` for batch control
- Strongly-typed return models
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .client import CommitHandle, MemoryClient, is_successful_job_status
from .models import (
    AddResult,
    EvidenceDetail,
    MemoryItem,
    SearchResult,
)
from .types import CanonicalTurnV1, JobStatusV1

# Default hosted API endpoint.
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


def _resolve_group_id(group_id: Optional[str], session_id: Optional[str]) -> Optional[str]:
    """Prefer the Router-native group ID while retaining the session alias."""
    group = str(group_id).strip() if group_id else None
    session = str(session_id).strip() if session_id else None
    if group and session and group != session:
        raise ValueError("group_id and session_id must match when both are provided")
    return group or session


class Memory:
    """High-level Memory API for MemAura.

    Provides a simple interface for storing and retrieving conversational
    memories through the MemAura API.

    Quick Start:
        >>> from memaura import Memory
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
        - Simple case: `add()` for one-line writes with an asynchronous receipt
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
            api_key: API key for authentication (required).
            endpoint: MemAura-compatible gateway URL. Defaults to the cloud service.
            device_no: Optional customer-defined device number. It is used as the
                default for explicit `search_hybrid()` calls; `search()` always
                uses regular retrieval.
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
        self.jobs = JobOperations(self._client)

    # ========== Write API ==========

    def add(
        self,
        conversation_id: str,
        messages: Sequence[Dict[str, Any]],
        *,
        commit_id: Optional[str] = None,
        group_id: Optional[str] = None,
        group_name: Optional[str] = None,
        device_no: Optional[str] = None,
        wait: bool = False,
        timeout_s: float = 60.0,
    ) -> "AddResult":
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
        conv = self.conversation(
            conversation_id,
            group_id=group_id,
            group_name=group_name,
            device_no=device_no,
        )
        for msg in messages:
            conv.add(msg)
        return conv.commit(wait=wait, timeout_s=timeout_s, commit_id=commit_id)

    def conversation(
        self,
        conversation_id: str,
        *,
        group_id: Optional[str] = None,
        group_name: Optional[str] = None,
        device_no: Optional[str] = None,
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
            group_id=group_id,
            group_name=group_name,
            device_no=device_no,
            auto_timestamp=True,
        )

    # ========== Search API ==========

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        group_id: Optional[str] = None,
        session_id: Optional[str] = None,
        fail_silent: bool = False,
    ) -> SearchResult:
        """Search memories.

        Args:
            query: Search question (e.g., "我什么时候去西湖？")
            limit: Maximum number of results (default: 10)
            group_id: Optional Router-native memory group ID to filter results.
            session_id: Compatibility alias for group_id. When either is provided,
                only memories from that group are returned.
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
        resolved_group_id = _resolve_group_id(group_id, session_id)
        t0 = time.perf_counter()
        try:
            resp = self._client.retrieve_dialog_v2(
                query=query,
                session_id=resolved_group_id,
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
        group_id: Optional[str] = None,
        session_id: Optional[str] = None,
        fail_silent: bool = False,
    ) -> SearchResult:
        """Search device-scoped memories through the hybrid retrieval endpoint."""
        effective_device_no = str(device_no or self._device_no or "").strip()
        if not effective_device_no:
            raise ValueError("device_no is required for hybrid retrieval")

        resolved_group_id = _resolve_group_id(group_id, session_id)
        t0 = time.perf_counter()
        try:
            resp = self._client.retrieve_dialog_hybrid(
                query=query,
                session_id=resolved_group_id,
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
        evidence_details: List[EvidenceDetail] = []
        for e in resp.get("evidence_details") or []:
            text = str(e.get("text") or "").strip()
            if not text:
                continue
            evidence_details.append(
                EvidenceDetail(
                    event_id=str(e.get("event_id") or ""),
                    text=text,
                    source=(str(e.get("source")) if e.get("source") is not None else None),
                    role=(str(e.get("role")) if e.get("role") is not None else None),
                    sender_name=(str(e.get("sender_name")) if e.get("sender_name") is not None else None),
                    atomic_facts=(list(e.get("atomic_facts")) if isinstance(e.get("atomic_facts"), list) else []),
                    group_id=(str(e.get("group_id")) if e.get("group_id") is not None else None),
                    timestamp=_parse_datetime(e.get("timestamp")),
                )
            )
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
            evidence_details=evidence_details,
            requested_group_id=(str(resp.get("requested_group_id")) if resp.get("requested_group_id") is not None else None),
        )

    # ========== Lifecycle ==========

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class JobOperations:
    """Read and wait for ingest jobs through the owning Memory instance."""

    def __init__(self, client: MemoryClient) -> None:
        self._client = client

    def get(self, job_id: str) -> JobStatusV1:
        return self._client.get_job(job_id)

    def wait(
        self,
        job_id: str,
        *,
        timeout_s: float = 60.0,
        poll_interval_s: float = 0.5,
    ) -> JobStatusV1:
        jid = str(job_id or "").strip()
        if not jid:
            raise ValueError("job_id is required")
        return CommitHandle(
            client=self._client,
            job_id=jid,
            session_id="",
            commit_id="",
        ).wait(timeout_s=timeout_s, poll_interval_s=poll_interval_s)


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
        group_id: Optional[str] = None,
        group_name: Optional[str] = None,
        device_no: Optional[str] = None,
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
        self._group_id = str(group_id).strip() if group_id else None
        self._group_name = str(group_name).strip() if group_name else None
        self._device_no = str(device_no).strip() if device_no else None
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
                - role: "user", "assistant", or "system"
                - content or text: Message content
                - turn_id (or id / uuid): Optional caller-defined message ID
                - name: Optional speaker name
                - timestamp: Optional ISO timestamp (auto-generated if auto_timestamp=True)
                - refer_list (or referList): Optional referenced message IDs

        Example:
            >>> conv.add({"role": "user", "content": "Hello"})
            >>> conv.add({"role": "assistant", "content": "Hi there!"})
        """
        role = str(message.get("role") or "user").strip().lower()
        if role not in ("user", "assistant", "system"):
            raise ValueError("role must be one of: user, assistant, system")

        # Support both "content" (OpenAI) and "text" (MemAura).
        text = str(
            message.get("content") or message.get("text") or message.get("message") or ""
        )
        if not text.strip():
            raise ValueError("message content/text is empty")

        provided_turn_id = message.get("turn_id") or message.get("id") or message.get("uuid")
        turn_id = str(provided_turn_id).strip() if provided_turn_id else self._turn_id_from_index(self._next_turn_index)
        if not turn_id:
            raise ValueError("turn_id must not be empty")
        self._next_turn_index += 1

        raw_refer_list = message.get("refer_list", message.get("referList"))
        if raw_refer_list is not None and not isinstance(raw_refer_list, (list, tuple)):
            raise ValueError("refer_list must be a list of non-empty strings")
        refer_list = None
        if raw_refer_list is not None:
            refer_list = [str(value).strip() for value in raw_refer_list]
            if any(not value for value in refer_list):
                raise ValueError("refer_list must be a list of non-empty strings")

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
            refer_list=refer_list,
        )
        self._buffer.append(turn)

    def commit(
        self,
        *,
        commit_id: Optional[str] = None,
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
                session_id=self._conversation_id,
                status="completed",
                completed=True,
            )

        # Only submit delta (messages after cursor)
        delta = self._get_delta_turns()
        if not delta:
            return AddResult(
                conversation_id=self._conversation_id,
                message_count=0,
                session_id=self._conversation_id,
                status="completed",
                completed=True,
            )

        handle = self._client.ingest_dialog_v1(
            session_id=self._conversation_id,
            turns=delta,
            commit_id=commit_id,
            group_id=self._group_id,
            group_name=self._group_name,
            device_no=self._device_no,
        )

        # Update cursor
        self._cursor_last_committed = delta[-1].turn_id

        status = handle.ack_status
        completed = False
        if wait and handle.job_id:
            job_status = handle.wait(timeout_s=timeout_s)
            status = job_status.status
            completed = is_successful_job_status(status)

        # Clear buffer after successful commit
        self._buffer.clear()

        return AddResult(
            conversation_id=self._conversation_id,
            message_count=len(delta),
            job_id=handle.job_id if handle.job_id else None,
            session_id=handle.session_id or self._conversation_id,
            status=status,
            status_url=handle.status_url,
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
    "JobOperations",
]
