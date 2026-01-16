from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import json
import warnings

import httpx

from .types import CanonicalAttachmentV1, CanonicalTurnV1, JobStatusV1, SessionStatusV1


class OmemClientError(RuntimeError):
    pass


class OmemHttpError(OmemClientError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error: Optional[str] = None,
        request_id: Optional[str] = None,
        retry_after_s: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.error = error
        self.request_id = request_id
        self.retry_after_s = retry_after_s


class OmemAuthError(OmemHttpError):
    pass


class OmemForbiddenError(OmemHttpError):
    pass


class OmemRateLimitError(OmemHttpError):
    pass


class OmemQuotaExceededError(OmemHttpError):
    pass


class OmemPayloadTooLargeError(OmemHttpError):
    pass


class OmemValidationError(OmemHttpError):
    pass


class OmemServerError(OmemHttpError):
    pass


def _normalize_base_url(base_url: str) -> str:
    u = str(base_url or "").strip()
    if not u:
        raise ValueError("base_url is required")
    return u.rstrip("/")


def _normalize_user_tokens(user_tokens: Sequence[str]) -> List[str]:
    """
    Normalize and validate user_tokens.

    SaaS mode:
        The public SDK no longer sends user_tokens in request payloads. Isolation
        is handled by the SaaS control plane (gateway/api-dev) based on the API
        key → account_id/tenant_id mapping. This helper is therefore only used
        in self-hosted or advanced scenarios.

    Self-hosted mode (future design sketch):
        Prefer an X-User-ID header over client-controlled user_tokens in the
        payload:

            - SDK sends X-User-ID header derived from Memory(user_id=...)
            - Server enforces isolation based on tenant_id + user_id
            - Client cannot escalate privileges by forging tokens

        The existing user_tokens field remains for backward compatibility but
        should be considered a legacy surface.
    """
    out = [str(x).strip() for x in (user_tokens or []) if str(x).strip()]
    if not out:
        raise ValueError("user_tokens must be non-empty")
    # Stable order for idempotency keys/markers.
    return list(sorted(dict.fromkeys(out)))


def _turn_id_from_index(i: int) -> str:
    if i <= 0:
        raise ValueError("turn index must be >= 1")
    return f"t{i:04d}"


def _as_jsonable_turn(t: CanonicalTurnV1) -> Dict[str, Any]:
    attachments: List[Dict[str, Any]] = []
    for a in (t.attachments or [])[:]:
        attachments.append(
            {
                "type": a.type,
                "name": a.name,
                "truncated": bool(a.truncated),
                "sha256": a.sha256,
                "ref": a.ref,
            }
        )
    return {
        "turn_id": t.turn_id,
        "role": t.role,
        "name": t.name,
        "speaker": t.name,  # Backend uses "speaker" for entity extraction
        "timestamp_iso": t.timestamp_iso,
        "text": t.text,
        "attachments": (attachments if attachments else None),
        "meta": (dict(t.meta) if isinstance(t.meta, dict) else None),
    }


def _coerce_job_status(payload: Dict[str, Any]) -> JobStatusV1:
    return JobStatusV1(
        job_id=str(payload.get("job_id") or ""),
        session_id=str(payload.get("session_id") or ""),
        status=str(payload.get("status") or ""),
        attempts=(dict(payload.get("attempts") or {}) if isinstance(payload.get("attempts"), dict) else None),
        next_retry_at=(str(payload.get("next_retry_at")) if payload.get("next_retry_at") else None),
        last_error=(dict(payload.get("last_error") or {}) if isinstance(payload.get("last_error"), dict) else None),
        metrics=(dict(payload.get("metrics") or {}) if isinstance(payload.get("metrics"), dict) else None),
    )


def _coerce_session_status(payload: Dict[str, Any]) -> SessionStatusV1:
    return SessionStatusV1(
        session_id=str(payload.get("session_id") or ""),
        latest_job_id=(str(payload.get("latest_job_id")) if payload.get("latest_job_id") else None),
        latest_status=(str(payload.get("latest_status")) if payload.get("latest_status") else None),
        cursor_committed=(str(payload.get("cursor_committed")) if payload.get("cursor_committed") else None),
    )


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    max_wait_seconds: float = 30.0
    base_backoff_seconds: float = 0.5
    jitter: bool = True


@dataclass(frozen=True)
class CommitHandle:
    client: "MemoryClient"
    job_id: str
    session_id: str
    commit_id: str

    def status(self) -> JobStatusV1:
        return self.client.get_job(self.job_id)

    def wait(self, *, timeout_s: float = 30.0, poll_interval_s: float = 0.5) -> JobStatusV1:
        deadline = time.time() + float(timeout_s)
        last: Optional[JobStatusV1] = None
        while True:
            last = self.status()
            if str(last.status).upper() == "COMPLETED":
                return last
            if time.time() >= deadline:
                return last
            time.sleep(float(poll_interval_s))


class SessionBuffer:
    def __init__(
        self,
        *,
        client: "MemoryClient",
        session_id: str,
        cursor_last_committed: Optional[str] = None,
    ) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        self._client = client
        self.session_id = sid
        self.cursor_last_committed = cursor_last_committed
        self._turns: List[CanonicalTurnV1] = []
        self._next_turn_index = 1

    def append_turn(
        self,
        *,
        role: str,
        text: str,
        timestamp_iso: Optional[str] = None,
        name: Optional[str] = None,
        attachments: Optional[Iterable[CanonicalAttachmentV1]] = None,
        meta: Optional[Dict[str, Any]] = None,
        turn_id: Optional[str] = None,
    ) -> CanonicalTurnV1:
        r = str(role or "").strip().lower()
        if r not in ("user", "assistant", "tool", "system"):
            raise ValueError("role must be one of: user|assistant|tool|system")
        t = str(text or "")
        if not t.strip():
            raise ValueError("text is empty")

        if turn_id is None:
            turn_id = _turn_id_from_index(self._next_turn_index)
            self._next_turn_index += 1
        else:
            turn_id = str(turn_id).strip()
            if not turn_id:
                raise ValueError("turn_id is empty")
            # Best-effort bump next index if it looks like our canonical format.
            if turn_id.startswith("t") and turn_id[1:].isdigit():
                try:
                    idx = int(turn_id[1:])
                    self._next_turn_index = max(self._next_turn_index, idx + 1)
                except Exception:
                    pass

        turn = CanonicalTurnV1(
            turn_id=turn_id,
            role=r,  # type: ignore[arg-type]
            name=(str(name).strip() if name else None),
            timestamp_iso=(str(timestamp_iso).strip() if timestamp_iso else None),
            text=t,
            attachments=(list(attachments) if attachments is not None else None),
            meta=(dict(meta) if isinstance(meta, dict) else None),
        )
        self._turns.append(turn)
        return turn

    def turns(self) -> List[CanonicalTurnV1]:
        return list(self._turns)

    def commit(self, *, commit_id: Optional[str] = None) -> CommitHandle:
        delta = self._delta_turns()
        if not delta:
            # Treat as a no-op commit but still return a handle-like object for uniform call sites.
            cid = str(commit_id or uuid.uuid4())
            return CommitHandle(client=self._client, job_id="", session_id=self.session_id, commit_id=cid)
        cid = str(commit_id or uuid.uuid4())
        handle = self._client.ingest_dialog_v1(
            session_id=self.session_id,
            turns=delta,
            commit_id=cid,
            base_turn_id=(self.cursor_last_committed or None),
        )
        # Client-side cursor advances optimistically to the last submitted turn.
        self.cursor_last_committed = delta[-1].turn_id
        return handle

    def sync_cursor_from_server(self) -> Optional[str]:
        ss = self._client.get_session(self.session_id)
        self.cursor_last_committed = ss.cursor_committed
        if ss.cursor_committed and ss.cursor_committed.startswith("t") and ss.cursor_committed[1:].isdigit():
            try:
                idx = int(ss.cursor_committed[1:])
                self._next_turn_index = max(self._next_turn_index, idx + 1)
            except Exception:
                pass
        return self.cursor_last_committed

    def _delta_turns(self) -> List[CanonicalTurnV1]:
        base = str(self.cursor_last_committed or "").strip()
        if not base:
            return list(self._turns)
        out: List[CanonicalTurnV1] = []
        for t in self._turns:
            if t.turn_id > base:
                out.append(t)
        return out


class MemoryClient:
    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        user_tokens: Optional[Sequence[str]] = None,
        memory_domain: str = "dialog",
        api_token: Optional[str] = None,
        timeout_s: float = 30.0,
        retry_config: Optional[RetryConfig] = None,
        http: Optional[httpx.Client] = None,
        mode: str = "saas",
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.tenant_id = str(tenant_id or "").strip()
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        # Mode is primarily used to distinguish SaaS from self-hosted behavior.
        # For now, only SaaS behavior is officially supported for external users.
        self._mode = (str(mode or "saas").strip() or "saas").lower()

        # In SaaS mode (tenant derived from API key), the backend BFF owns user_tokens.
        # We still allow user_tokens for self-hosted/direct-core scenarios.
        if user_tokens is not None:
            if self._mode == "saas" or self.tenant_id == "__from_api_key__":
                # Guard-rail: warn that SDK-side user_tokens are ignored in SaaS.
                warnings.warn(
                    "MemoryClient(user_tokens=...) is ignored in SaaS mode; "
                    "data is isolated at account level by the backend.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                self.user_tokens: List[str] = []
            else:
                self.user_tokens = _normalize_user_tokens(user_tokens)
        else:
            self.user_tokens = []

        self.memory_domain = str(memory_domain or "dialog").strip() or "dialog"
        self.api_token = (str(api_token).strip() if api_token else None)
        self._timeout_s = float(timeout_s)
        self._retry = retry_config or RetryConfig()
        self._http = http or httpx.Client(timeout=self._timeout_s)

    def close(self) -> None:
        self._http.close()

    def session(self, *, session_id: str, sync_cursor: bool = False) -> SessionBuffer:
        buf = SessionBuffer(client=self, session_id=session_id)
        if sync_cursor:
            try:
                buf.sync_cursor_from_server()
            except Exception:
                # Cursor sync is best-effort.
                pass
        return buf

    def ingest_dialog_v1(
        self,
        *,
        session_id: str,
        turns: Sequence[CanonicalTurnV1],
        commit_id: Optional[str] = None,
        base_turn_id: Optional[str] = None,
        client_meta: Optional[Dict[str, Any]] = None,
    ) -> CommitHandle:
        # SaaS mode: backend (Gateway + BFF) owns user_tokens and client_meta.
        saas_mode = self._mode == "saas" or self.tenant_id == "__from_api_key__"

        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        cid = str(commit_id or uuid.uuid4())
        body: Dict[str, Any] = {
            "session_id": sid,
            "memory_domain": str(self.memory_domain),
            "turns": [_as_jsonable_turn(t) for t in turns],
            "commit_id": cid,
            "cursor": {"base_turn_id": (str(base_turn_id).strip() if base_turn_id else None)},
        }
        # Only attach user_tokens/client_meta when not in SaaS mode.
        if not saas_mode and self.user_tokens:
            body["user_tokens"] = list(self.user_tokens)
        if not saas_mode and client_meta:
            body["client_meta"] = dict(client_meta)
        payload = self._request_json(
            "POST",
            "/ingest",
            json_body=body,
        )
        job_id = str(payload.get("job_id") or "").strip()
        return CommitHandle(client=self, job_id=job_id, session_id=sid, commit_id=cid)

    def get_job(self, job_id: str) -> JobStatusV1:
        jid = str(job_id or "").strip()
        if not jid:
            raise ValueError("job_id is required")
        payload = self._request_json("GET", f"/ingest/jobs/{jid}")
        return _coerce_job_status(payload)

    def get_session(self, session_id: str) -> SessionStatusV1:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        payload = self._request_json("GET", f"/ingest/sessions/{sid}")
        return _coerce_session_status(payload)

    def retrieve_dialog_v2(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        topk: int = 30,
        task: str = "GENERAL",
        debug: bool = False,
        with_answer: bool = False,
        backend: str = "tkg",
        tkg_explain: bool = True,
        entity_hints: Optional[Sequence[str]] = None,
        time_hints: Optional[Dict[str, Any]] = None,
        client_meta: Optional[Dict[str, Any]] = None,
        strategy: str = "dialog_v2",
    ) -> Dict[str, Any]:
        # SaaS mode: backend (Gateway + BFF) owns user_tokens and client_meta.
        saas_mode = self._mode == "saas" or self.tenant_id == "__from_api_key__"

        q = str(query or "").strip()
        if not q:
            raise ValueError("query is required")
        sid = str(session_id).strip() if session_id else None
        strategy_norm = str(strategy or "dialog_v2").strip().lower()
        if strategy_norm not in ("dialog_v1", "dialog_v2"):
            strategy_norm = "dialog_v2"
        body: Dict[str, Any] = {
            "memory_domain": str(self.memory_domain),
            "run_id": sid,
            "query": q,
            "strategy": strategy_norm,
            "topk": int(topk),
            "task": str(task or "GENERAL"),
            "debug": bool(debug),
            "with_answer": bool(with_answer),
            "backend": str(backend or "tkg"),
            "tkg_explain": bool(tkg_explain),
            "entity_hints": (list(entity_hints) if entity_hints else None),
            "time_hints": (dict(time_hints) if isinstance(time_hints, dict) else None),
        }
        # In SaaS mode, gateway injects x-tenant-id header; SDK should not send tenant_id in body.
        # Only attach tenant_id/user_tokens/client_meta when not in SaaS mode.
        if not saas_mode:
            body["tenant_id"] = str(self.tenant_id)
            if self.user_tokens:
                body["user_tokens"] = list(self.user_tokens)
        if not saas_mode and client_meta:
            body["client_meta"] = dict(client_meta)
        return self._request_json("POST", "/retrieval", json_body=body)

    def debug_config(self) -> Dict[str, Any]:
        """Fetch effective backend configuration for this client (if supported).

        This calls the SaaS/backend debug endpoint. Not all deployments expose it;
        in that case an OmemHttpError (e.g., 404) will be raised.
        """
        return self._request_json("GET", "/debug/config")

    # ========== TKG Graph API Methods ==========

    def graph_resolve_entities(
        self,
        name: str,
        *,
        entity_type: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Resolve entity by name.

        Args:
            name: Entity name to resolve.
            entity_type: Optional type filter (e.g., "person", "place").
            limit: Maximum number of results.

        Returns:
            Dict with "items" list of resolved entities.
        """
        params: Dict[str, Any] = {"name": name, "limit": limit}
        if entity_type:
            params["type"] = entity_type
        return self._request_json("GET", "/graph/v0/entities/resolve", params=params)

    def graph_explain_event(self, event_id: str) -> Dict[str, Any]:
        """Get structured evidence chain for a single event.

        Backend: GET /graph/v0/explain/event/{event_id}

        Args:
            event_id: Logical event ID from retrieval/search (MemoryItem.event_id).

        Returns:
            Dict with \"item\" containing event, entities, evidences, utterances, knowledge, etc.
        """
        eid = str(event_id or "").strip()
        if not eid:
            raise ValueError("event_id is required")
        return self._request_json("GET", f"/graph/v0/explain/event/{eid}")

    def graph_entity_timeline(
        self,
        entity_id: str,
        *,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Get timeline of events/evidences for an entity.

        Args:
            entity_id: Entity ID.
            limit: Maximum number of results.

        Returns:
            Dict with timeline data.
        """
        return self._request_json(
            "GET",
            f"/graph/v0/entities/{entity_id}/timeline",
            params={"limit": limit},
        )

    def graph_search_events(
        self,
        query: str,
        *,
        topk: int = 10,
        source_id: Optional[str] = None,
        include_evidence: bool = True,
    ) -> Dict[str, Any]:
        """Search events using fulltext/BM25.

        Args:
            query: Search query.
            topk: Maximum number of results.
            source_id: Optional source filter.
            include_evidence: Whether to include evidence details.

        Returns:
            Dict with search results.
        """
        body: Dict[str, Any] = {
            "query": query,
            "topk": topk,
            "include_evidence": include_evidence,
        }
        if source_id:
            body["source_id"] = source_id
        return self._request_json("POST", "/graph/v1/search", json_body=body)

    def graph_list_events(
        self,
        *,
        entity_id: Optional[str] = None,
        place_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List events with optional filters.

        Args:
            entity_id: Filter by entity involvement.
            place_id: Filter by place.
            limit: Maximum number of results.

        Returns:
            Dict with "items" list of events.
        """
        params: Dict[str, Any] = {"limit": limit}
        if entity_id:
            params["entity_id"] = entity_id
        if place_id:
            params["place_id"] = place_id
        return self._request_json("GET", "/graph/v0/events", params=params)

    def graph_timeslices_range(
        self,
        start: str,
        end: str,
        *,
        granularity: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Query timeslices within a time range.

        Args:
            start: ISO format start time.
            end: ISO format end time.
            granularity: Optional granularity filter (e.g., "day", "hour").
            limit: Maximum number of results.

        Returns:
            Dict with "items" list of timeslices.
        """
        params: Dict[str, Any] = {"start": start, "end": end, "limit": limit}
        if granularity:
            params["granularity"] = granularity
        return self._request_json("GET", "/graph/v0/timeslices/range", params=params)

    def graph_timeslice_events(
        self,
        timeslice_id: str,
        *,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get events within a specific timeslice.

        Args:
            timeslice_id: Timeslice ID.
            limit: Maximum number of results.

        Returns:
            Dict with "items" list of events.
        """
        return self._request_json(
            "GET",
            f"/graph/v0/timeslices/{timeslice_id}/events",
            params={"limit": limit},
        )

    def graph_entity_evidences(
        self,
        entity_id: str,
        *,
        subtype: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get evidences for an entity.

        Args:
            entity_id: Entity ID.
            subtype: Optional evidence subtype filter.
            source_id: Optional source ID filter.
            limit: Maximum number of results (default: 50, max: 200).

        Returns:
            Dict with "items" list of evidence objects.

        Backend: GET /graph/v0/entities/{entity_id}/evidences
        """
        params: Dict[str, Any] = {"limit": limit}
        if subtype:
            params["subtype"] = subtype
        if source_id:
            params["source_id"] = source_id
        return self._request_json(
            "GET",
            f"/graph/v0/entities/{entity_id}/evidences",
            params=params,
        )

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        
        # In SaaS mode, gateway injects x-tenant-id header from API key lookup.
        # SDK should NOT send X-Tenant-ID header in SaaS mode.
        saas_mode = self._mode == "saas" or self.tenant_id == "__from_api_key__"
        if not saas_mode and self.tenant_id and self.tenant_id != "__from_api_key__":
            h["X-Tenant-ID"] = str(self.tenant_id)
        
        if self.api_token:
            token = str(self.api_token)
            # SaaS mode: API keys starting with qbk_ use x-api-key header
            if token.startswith("qbk_"):
                h["x-api-key"] = token
            else:
                # Self-hosted mode: use X-API-Token and Bearer
                h["X-API-Token"] = token
                h["Authorization"] = f"Bearer {token}"
        
        return h

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        request_id = _ensure_request_id(headers)

        attempt = 0
        while True:
            try:
                resp = self._http.request(method.upper(), url, headers=headers, json=json_body, params=params)
            except Exception as exc:
                if _should_retry_exc(exc) and attempt < self._retry.max_retries:
                    _sleep_backoff(self._retry, attempt, None)
                    attempt += 1
                    continue
                raise OmemClientError(f"http_request_failed: {type(exc).__name__}: {exc}") from exc

            if resp.status_code >= 400:
                err = _http_error_from_response(resp, request_id=request_id)
                if _should_retry_status(resp.status_code) and attempt < self._retry.max_retries:
                    _sleep_backoff(self._retry, attempt, err.retry_after_s)
                    attempt += 1
                    continue
                raise err

            try:
                return resp.json()  # type: ignore[no-any-return]
            except Exception:
                # Keep raw for diagnostics.
                try:
                    txt = resp.text
                except Exception:
                    txt = "<unreadable>"
                raise OmemClientError(f"invalid_json_response: {txt[:500]}")


def _ensure_request_id(headers: Dict[str, str]) -> str:
    for key in ("X-Request-ID", "x-request-id"):
        if key in headers and str(headers[key]).strip():
            return str(headers[key]).strip()
    rid = f"req_{uuid.uuid4().hex}"
    headers["X-Request-ID"] = rid
    return rid


def _should_retry_status(status_code: int) -> bool:
    return int(status_code) in (429, 502, 503, 504)


def _should_retry_exc(exc: Exception) -> bool:
    return isinstance(exc, httpx.RequestError)


def _sleep_backoff(cfg: RetryConfig, attempt: int, retry_after_s: Optional[int]) -> None:
    if retry_after_s is not None and retry_after_s >= 0:
        wait = float(retry_after_s)
    else:
        wait = float(cfg.base_backoff_seconds) * (2 ** attempt)
        if cfg.jitter:
            wait = random.uniform(0.0, max(wait, 0.0))
    wait = min(wait, float(cfg.max_wait_seconds))
    if wait <= 0:
        return
    time.sleep(wait)


def _parse_retry_after(resp: httpx.Response) -> Optional[int]:
    raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0, int(float(raw)))
    except Exception:
        return None


def _parse_error_payload(resp: httpx.Response) -> Dict[str, Any]:
    try:
        payload = resp.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _http_error_from_response(resp: httpx.Response, *, request_id: Optional[str]) -> OmemHttpError:
    payload = _parse_error_payload(resp)
    err_code = None
    message = None
    if payload:
        err_code = payload.get("error") or payload.get("detail") or payload.get("code")
        message = payload.get("message")
        
        # Provide helpful hints for common configuration errors
        if err_code == "missing_core_requirements":
            missing = payload.get("missing", [])
            if any(k in missing for k in ["llm_api_key", "llm_provider", "llm_model"]):
                message = (
                    f"{message}. "
                    "You need to configure an LLM provider in your dashboard: "
                    "Go to Dashboard → Memory Policy → Add LLM Key. "
                    "See https://omnimemory.ai/docs/quickstart for setup instructions."
                )
    snippet = ""
    if not err_code and not message:
        try:
            snippet = resp.text[:500]
        except Exception:
            snippet = ""
    detail = message or err_code or snippet or "request_failed"
    retry_after = _parse_retry_after(resp)
    status = int(resp.status_code)

    cls: type[OmemHttpError]
    if status == 401:
        cls = OmemAuthError
    elif status == 403:
        cls = OmemForbiddenError
    elif status == 402:
        cls = OmemQuotaExceededError
    elif status == 429:
        cls = OmemRateLimitError
    elif status == 413:
        cls = OmemPayloadTooLargeError
    elif status == 400:
        cls = OmemValidationError
    elif status >= 500:
        cls = OmemServerError
    else:
        cls = OmemHttpError

    return cls(
        f"http_{status}: {detail}",
        status_code=status,
        error=(str(err_code) if err_code else None),
        request_id=(resp.headers.get("X-Request-ID") or resp.headers.get("x-request-id") or request_id),
        retry_after_s=retry_after,
    )
