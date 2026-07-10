from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import json
import warnings

import httpx

from .types import CanonicalAttachmentV1, CanonicalTurnV1, JobStatusV1


class MemAuraClientError(RuntimeError):
    pass


class MemAuraHttpError(MemAuraClientError):
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


class MemAuraAuthError(MemAuraHttpError):
    pass


class MemAuraForbiddenError(MemAuraHttpError):
    pass


class MemAuraRateLimitError(MemAuraHttpError):
    pass


class MemAuraQuotaExceededError(MemAuraHttpError):
    pass


class MemAuraPayloadTooLargeError(MemAuraHttpError):
    pass


class MemAuraValidationError(MemAuraHttpError):
    pass


class MemAuraServerError(MemAuraHttpError):
    pass


def _normalize_base_url(base_url: str) -> str:
    u = str(base_url or "").strip()
    if not u:
        raise ValueError("base_url is required")
    return u.rstrip("/")


def _normalize_user_tokens(user_tokens: Sequence[str]) -> List[str]:
    """Normalize user tokens for direct compatible-gateway integrations."""
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


class MemoryClient:
    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        user_tokens: Optional[Sequence[str]] = None,
        memory_domain: str = "dialog",
        api_token: Optional[str] = None,
        device_no: Optional[str] = None,
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
        self.device_no = (str(device_no).strip() if device_no else None)
        self._timeout_s = float(timeout_s)
        self._retry = retry_config or RetryConfig()
        self._http = http or httpx.Client(timeout=self._timeout_s)

    def close(self) -> None:
        self._http.close()

    def ingest_dialog_v1(
        self,
        *,
        session_id: str,
        turns: Sequence[CanonicalTurnV1],
        commit_id: Optional[str] = None,
        base_turn_id: Optional[str] = None,
        client_meta: Optional[Dict[str, Any]] = None,
        device_no: Optional[str] = None,
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
        effective_device_no = self._effective_device_no(device_no or _device_no_from_meta(client_meta))

        # Only attach user_tokens/client_meta when not in SaaS mode, except
        # device_no which is a public data-plane routing field in SaaS.
        if not saas_mode and self.user_tokens:
            body["user_tokens"] = list(self.user_tokens)
        if not saas_mode and client_meta:
            body["client_meta"] = dict(client_meta)
        elif effective_device_no:
            body["client_meta"] = {"device_no": effective_device_no}
        payload = self._request_json(
            "POST",
            "/ingest",
            json_body=body,
            device_no=effective_device_no,
        )
        job_id = str(payload.get("job_id") or "").strip()
        return CommitHandle(client=self, job_id=job_id, session_id=sid, commit_id=cid)

    def get_job(self, job_id: str) -> JobStatusV1:
        jid = str(job_id or "").strip()
        if not jid:
            raise ValueError("job_id is required")
        payload = self._request_json("GET", f"/ingest/jobs/{jid}")
        return _coerce_job_status(payload)

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
        device_no: Optional[str] = None,
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
        effective_device_no = self._effective_device_no(device_no or _device_no_from_meta(client_meta))
        body: Dict[str, Any] = {
            "memory_domain": str(self.memory_domain),
            "group_id": sid,
            "query": q,
            "strategy": strategy_norm,
            "top_k": int(topk),
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
        elif effective_device_no:
            body["client_meta"] = {"device_no": effective_device_no}
        return self._request_json("POST", "/retrieval", json_body=body, device_no=effective_device_no)

    def retrieve_dialog_hybrid(
        self,
        *,
        query: str,
        session_id: Optional[str] = None,
        top_k: int = 10,
        device_no: Optional[str] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        q = str(query or "").strip()
        if not q:
            raise ValueError("query is required")
        effective_device_no = self._effective_device_no(device_no)
        if not effective_device_no:
            raise ValueError("device_no is required for hybrid retrieval")
        sid = str(session_id).strip() if session_id else None
        body: Dict[str, Any] = {
            "query": q,
            "top_k": int(top_k),
            "group_id": sid,
            "client_meta": {"device_no": effective_device_no},
        }
        if debug:
            body["debug"] = True
        return self._request_json(
            "POST",
            "/retrieval/hybrid",
            json_body=body,
            device_no=effective_device_no,
        )

    def _effective_device_no(self, device_no: Optional[str] = None) -> Optional[str]:
        value = str(device_no or self.device_no or "").strip()
        return value or None

    def _headers(self, *, device_no: Optional[str] = None) -> Dict[str, str]:
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

        effective_device_no = self._effective_device_no(device_no)
        if effective_device_no:
            h["X-Device-No"] = effective_device_no
        
        return h

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        device_no: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers(device_no=device_no)
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
                raise MemAuraClientError(f"http_request_failed: {type(exc).__name__}: {exc}") from exc

            if resp.status_code >= 400:
                err = _http_error_from_response(resp, request_id=request_id)
                if _should_retry_status(resp.status_code) and attempt < self._retry.max_retries:
                    _sleep_backoff(self._retry, attempt, err.retry_after_s)
                    attempt += 1
                    continue
                raise err

            try:
                payload = resp.json()
            except Exception:
                # Keep raw for diagnostics.
                try:
                    txt = resp.text
                except Exception:
                    txt = "<unreadable>"
                raise MemAuraClientError(f"invalid_json_response: {txt[:500]}")
            return _unwrap_api_payload(payload, request_id=request_id)


def _device_no_from_meta(client_meta: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(client_meta, dict):
        return None
    raw = client_meta.get("device_no")
    value = str(raw).strip() if raw is not None else ""
    return value or None


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


def _http_error_from_response(resp: httpx.Response, *, request_id: Optional[str]) -> MemAuraHttpError:
    payload = _parse_error_payload(resp)
    err_code = None
    message = None
    if payload:
        data = payload.get("data")
        data_obj = data if isinstance(data, dict) else {}
        err_code = data_obj.get("error") or payload.get("error") or payload.get("detail") or payload.get("code")
        message = payload.get("message")
        
        # Provide helpful hints for common configuration errors
        if err_code == "missing_core_requirements":
            missing = payload.get("missing") or data_obj.get("missing") or []
            if any(k in missing for k in ["llm_api_key", "llm_provider", "llm_model"]):
                message = (
                    f"{message}. "
                    "You need to configure an LLM provider in your dashboard: "
                    "Go to Dashboard → Memory Policy → Add LLM Key. "
                    "See the MemAura quickstart documentation for setup instructions."
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

    cls: type[MemAuraHttpError]
    if status == 401:
        cls = MemAuraAuthError
    elif status == 403:
        cls = MemAuraForbiddenError
    elif status == 402:
        cls = MemAuraQuotaExceededError
    elif status == 429:
        cls = MemAuraRateLimitError
    elif status == 413:
        cls = MemAuraPayloadTooLargeError
    elif status == 400:
        cls = MemAuraValidationError
    elif status >= 500:
        cls = MemAuraServerError
    else:
        cls = MemAuraHttpError

    return cls(
        f"http_{status}: {detail}",
        status_code=status,
        error=(str(err_code) if err_code else None),
        request_id=(resp.headers.get("X-Request-ID") or resp.headers.get("x-request-id") or request_id),
        retry_after_s=retry_after,
    )


def _error_class_for_status(status: int) -> type[MemAuraHttpError]:
    if status == 401:
        return MemAuraAuthError
    if status == 403:
        return MemAuraForbiddenError
    if status == 402:
        return MemAuraQuotaExceededError
    if status == 429:
        return MemAuraRateLimitError
    if status == 413:
        return MemAuraPayloadTooLargeError
    if status == 400:
        return MemAuraValidationError
    if status >= 500:
        return MemAuraServerError
    return MemAuraHttpError


def _unwrap_api_payload(payload: Any, *, request_id: Optional[str]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MemAuraClientError("invalid_json_response: expected object")

    if "success" not in payload or "data" not in payload:
        return payload

    success = bool(payload.get("success"))
    try:
        status = int(payload.get("code") or (200 if success else 500))
    except Exception:
        status = 200 if success else 500

    data = payload.get("data")
    data_obj = data if isinstance(data, dict) else {}
    err_code = data_obj.get("error") or payload.get("error") or (payload.get("code") if not success else None)
    message = payload.get("message") or err_code or "request_failed"

    if not success or status >= 400:
        cls = _error_class_for_status(status)
        raise cls(
            f"http_{status}: {message}",
            status_code=status,
            error=(str(err_code) if err_code else None),
            request_id=request_id,
        )

    if isinstance(data, dict):
        return data
    return {"data": data}
