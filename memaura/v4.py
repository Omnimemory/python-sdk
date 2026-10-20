"""Typed client for the MemAura V4 Card/Episode data plane."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote, urlparse

import httpx

from .client import MemAuraClientError, MemAuraHttpError, _http_error_from_response, _unwrap_api_payload


DEFAULT_V4_ENDPOINT = "https://api.omnimemory.cn/api/v3"
_PENDING_STATUSES = {"queued", "staged", "processing", "buffered", "indexing"}
_TERMINAL_STATUSES = {"succeeded", "failed"}


@dataclass(frozen=True)
class V4Job:
    job_id: str
    status: Optional[str] = None
    wait_timed_out: bool = False
    error: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class V4Episode:
    episode_id: str
    summary: str


@dataclass(frozen=True)
class V4Card:
    card_id: str
    role: str
    content: str
    episodes: List[V4Episode] = field(default_factory=list)


@dataclass(frozen=True)
class V4RetrievalResult:
    cards: List[V4Card]
    query_analysis: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None

    def __bool__(self) -> bool:
        return bool(self.cards)

    def __len__(self) -> int:
        return len(self.cards)


class V4JobTimeoutError(TimeoutError):
    """The local wait deadline expired; the existing job may still complete."""

    def __init__(self, job_id: str, last_job: Optional[V4Job]) -> None:
        super().__init__(f"timed out waiting for V4 ingest job {job_id}; continue polling the same job")
        self.job_id = job_id
        self.last_job = last_job


class V4JobOperations:
    def __init__(self, memory: "MemoryV4") -> None:
        self._memory = memory

    def get(self, job_id: str) -> V4Job:
        jid = _non_empty(job_id, "job_id")
        data = self._memory._request("GET", "/memory/ingest_4/jobs/" + quote(jid, safe=""))
        return _job_from_payload(data, fallback_job_id=jid)

    def wait(
        self,
        job_id: str,
        *,
        timeout_s: float = 300.0,
        poll_interval_s: float = 1.0,
    ) -> V4Job:
        jid = _non_empty(job_id, "job_id")
        if timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("timeout_s and poll_interval_s must be greater than zero")
        deadline = time.monotonic() + timeout_s
        last_job: Optional[V4Job] = None
        while time.monotonic() < deadline:
            last_job = self.get(jid)
            status = (last_job.status or "").lower()
            if status in _TERMINAL_STATUSES:
                return last_job
            if status not in _PENDING_STATUSES:
                raise MemAuraClientError(f"unexpected V4 job status: {last_job.status!r}")
            time.sleep(min(poll_interval_s, max(0.0, deadline - time.monotonic())))
        raise V4JobTimeoutError(jid, last_job)


class MemoryV4:
    """V4 client using explicit ingest, job, and Card/Episode retrieval routes.

    Writes are submitted exactly once. Transport failures are returned to the
    caller and are never retried automatically.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: Optional[str] = None,
        device_no: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = _non_empty(api_key, "api_key")
        self._endpoint = str(endpoint or DEFAULT_V4_ENDPOINT).rstrip("/")
        parsed_endpoint = urlparse(self._endpoint)
        if parsed_endpoint.scheme not in {"https", "http"} or not parsed_endpoint.netloc:
            raise ValueError("endpoint must be an absolute HTTP URL")
        self._device_no = str(device_no).strip() if device_no else None
        self._client = httpx.Client(timeout=timeout_s)
        self.jobs = V4JobOperations(self)

    def ingest(
        self,
        turns: Sequence[Mapping[str, Any]],
        *,
        language: str = "auto",
        timezone: Optional[str] = None,
        device_no: Optional[str] = None,
        wait_for: str = "staged",
        wait_timeout_seconds: float = 120.0,
    ) -> V4Job:
        if not turns:
            raise ValueError("turns must contain at least one message")
        if language not in {"auto", "zh", "en"}:
            raise ValueError("language must be auto, zh, or en")
        if wait_for not in {"staged", "searchable"}:
            raise ValueError("wait_for must be staged or searchable")
        if not 0 < wait_timeout_seconds <= 300:
            raise ValueError("wait_timeout_seconds must be between 0 and 300")

        wire_turns: List[Dict[str, Any]] = []
        for index, turn in enumerate(turns):
            content = _non_empty(str(turn.get("content") or ""), f"turns[{index}].content")
            item = {key: value for key, value in dict(turn).items() if value is not None}
            item["content"] = content
            wire_turns.append(item)
        body: Dict[str, Any] = {
            "turns": wire_turns,
            "language": language,
            "wait_for": wait_for,
            "wait_timeout_seconds": wait_timeout_seconds,
        }
        if timezone:
            body["timezone"] = timezone
        data = self._request("POST", "/memory/ingest_4", body, device_no=device_no)
        return _job_from_payload(data)

    def retrieve(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        vector_weight: float = 0.8,
        tag_keys: Optional[Sequence[str]] = None,
        role: Optional[str] = None,
        scope_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_match_mode: Optional[str] = None,
        participant_roles: Optional[Sequence[str]] = None,
        device_no: Optional[str] = None,
        include_query_analysis: bool = False,
        include_details: bool = False,
    ) -> V4RetrievalResult:
        body: Dict[str, Any] = {
            "query": _non_empty(query, "query"),
            "vector_weight": vector_weight,
            "tag_keys": list(tag_keys or []),
            "include_query_analysis": include_query_analysis,
            "include_details": include_details,
        }
        if top_k is not None:
            if isinstance(top_k, bool) or not 1 <= top_k <= 100:
                raise ValueError("top_k must be between 1 and 100")
            body["top_k"] = top_k
        if isinstance(vector_weight, bool) or not 0 <= vector_weight <= 1:
            raise ValueError("vector_weight must be between 0 and 1")
        if role:
            body["role"] = role
        if scope_type:
            if scope_type not in {"account", "api_key", "device"}:
                raise ValueError("scope_type must be account, api_key, or device")
            body["scope_type"] = scope_type
        if start_time:
            body["start_time"] = start_time
        if end_time:
            body["end_time"] = end_time
        if entity_id:
            body["entity_id"] = entity_id
        if entity_match_mode:
            if entity_match_mode not in {"primary", "involved", "source"}:
                raise ValueError("entity_match_mode must be primary, involved, or source")
            body["entity_match_mode"] = entity_match_mode
        if participant_roles is not None:
            body["participant_roles"] = list(participant_roles)

        payload = self._request("POST", "/memory/retrieval_4", body, device_no=device_no)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise MemAuraClientError("invalid V4 retrieval response: missing results")
        cards = [_card_from_payload(item) for item in raw_results]
        analysis = payload.get("query_analysis")
        return V4RetrievalResult(
            cards=cards,
            query_analysis=analysis if isinstance(analysis, dict) else None,
            details=payload if include_details else None,
        )

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        device_no: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = {"X-API-Key": self._api_key, "Content-Type": "application/json"}
        resolved_device = str(device_no or self._device_no or "").strip()
        if resolved_device:
            headers["X-Device-No"] = resolved_device
        try:
            response = self._client.request(method, self._endpoint + path, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise MemAuraClientError(f"unable to reach MemAura Router: {exc}") from exc
        if response.status_code >= 400:
            raise _http_error_from_response(response, request_id=response.headers.get("x-request-id"))
        try:
            payload = response.json()
        except ValueError as exc:
            raise MemAuraClientError("invalid_json_response") from exc
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            raise MemAuraHttpError(
                str(error.get("message") or "request_failed"),
                status_code=response.status_code,
                error=str(error.get("code") or "request_failed"),
                request_id=response.headers.get("x-request-id"),
            )
        return _unwrap_api_payload(payload, request_id=response.headers.get("x-request-id"))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MemoryV4":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _non_empty(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _job_from_payload(payload: Dict[str, Any], fallback_job_id: str = "") -> V4Job:
    job_id = str(payload.get("job_id") or fallback_job_id)
    if not job_id:
        raise MemAuraClientError("invalid V4 job response: missing job_id")
    error = payload.get("error")
    return V4Job(
        job_id=job_id,
        status=str(payload["status"]) if payload.get("status") is not None else None,
        wait_timed_out=payload.get("wait_timed_out") is True,
        error=error if isinstance(error, dict) else None,
    )


def _card_from_payload(value: Any) -> V4Card:
    if not isinstance(value, dict):
        raise MemAuraClientError("invalid V4 retrieval response: Card must be an object")
    episodes = value.get("episodes") or []
    if not isinstance(episodes, list):
        raise MemAuraClientError("invalid V4 retrieval response: episodes must be an array")
    return V4Card(
        card_id=str(value.get("card_id") or ""),
        role=str(value.get("role") or ""),
        content=str(value.get("content") or ""),
        episodes=[
            V4Episode(episode_id=str(item.get("episode_id") or ""), summary=str(item.get("summary") or ""))
            for item in episodes
            if isinstance(item, dict)
        ],
    )


__all__ = [
    "MemoryV4", "V4Card", "V4Episode", "V4Job", "V4JobOperations",
    "V4JobTimeoutError", "V4RetrievalResult",
]
