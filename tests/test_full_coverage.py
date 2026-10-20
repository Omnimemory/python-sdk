from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from memaura import Memory
from memaura.client import (
    CommitHandle,
    MemAuraAuthError,
    MemAuraClientError,
    MemAuraForbiddenError,
    MemAuraHttpError,
    MemAuraPayloadTooLargeError,
    MemAuraQuotaExceededError,
    MemAuraRateLimitError,
    MemAuraServerError,
    MemAuraValidationError,
    MemoryClient,
    RetryConfig,
    _as_jsonable_turn,
    _coerce_job_status,
    _device_no_from_meta,
    _ensure_request_id,
    _error_class_for_status,
    _http_error_from_response,
    _normalize_base_url,
    _normalize_user_tokens,
    _parse_error_payload,
    _parse_retry_after,
    _should_retry_exc,
    _should_retry_status,
    _sleep_backoff,
    _turn_id_from_index,
    _unwrap_api_payload,
)
from memaura.memory import Conversation, JobOperations, _parse_datetime
from memaura.models import MemoryItem, SearchResult
from memaura.types import CanonicalTurnV1, JobStatusV1


def _response(status: int = 200, *, json_data=None, text: str = "", headers=None):
    request = httpx.Request("GET", "https://example.test/path")
    if json_data is not None:
        return httpx.Response(status, json=json_data, headers=headers, request=request)
    return httpx.Response(status, text=text, headers=headers, request=request)


def _client(**kwargs):
    defaults = dict(
        base_url="https://example.test/root/",
        tenant_id="tenant-1",
        mode="self-hosted",
        http=MagicMock(),
    )
    defaults.update(kwargs)
    return MemoryClient(**defaults)


def test_client_scalar_helpers_and_models():
    with pytest.raises(ValueError, match="base_url"):
        _normalize_base_url(" ")
    assert _normalize_base_url(" https://example.test/ ") == "https://example.test"
    assert _normalize_user_tokens([" b ", "a", "b", " "]) == ["a", "b"]
    with pytest.raises(ValueError, match="user_tokens"):
        _normalize_user_tokens([])
    assert _turn_id_from_index(2) == "t0002"
    with pytest.raises(ValueError, match="turn index"):
        _turn_id_from_index(0)

    turn = CanonicalTurnV1(turn_id="t1", role="user", text="hello")
    assert "refer_list" not in _as_jsonable_turn(turn)
    turn_with_ref = CanonicalTurnV1(
        turn_id="t2", role="assistant", text="hi", refer_list=["t1"]
    )
    assert _as_jsonable_turn(turn_with_ref)["refer_list"] == ["t1"]

    status = _coerce_job_status(
        {
            "job_id": 1,
            "session_id": 2,
            "status": "queued",
            "attempts": {"count": 1},
            "next_retry_at": 123,
            "last_error": {"code": "x"},
            "metrics": {"ms": 2},
        }
    )
    assert status.job_id == "1" and status.attempts == {"count": 1}
    empty = _coerce_job_status(
        {"attempts": [], "next_retry_at": "", "last_error": [], "metrics": []}
    )
    assert empty.attempts is None and empty.next_retry_at is None

    item = MemoryItem("fact", score=0.5)
    result = SearchResult("q", [item])
    assert str(item) == "[0.50] fact"
    assert bool(result) and list(result) == [item] and len(result) == 1
    assert result.to_prompt() == "1. fact"
    assert SearchResult("q", []).to_prompt() == ""


def test_client_constructor_modes_headers_and_close():
    with pytest.raises(ValueError, match="tenant_id"):
        MemoryClient(base_url="https://x", tenant_id="")

    direct = _client(user_tokens=["b", "a", "a"], api_token="token", device_no="d1")
    assert direct.user_tokens == ["a", "b"]
    assert direct._headers() == {
        "X-Tenant-ID": "tenant-1",
        "X-API-Token": "token",
        "Authorization": "Bearer token",
        "X-Device-No": "d1",
    }
    direct.close()
    direct._http.close.assert_called_once()

    with pytest.warns(RuntimeWarning, match="ignored"):
        saas = _client(mode="saas", user_tokens=["ignored"], api_token="qbk_key")
    assert saas.user_tokens == []
    assert saas._headers() == {"x-api-key": "qbk_key"}
    assert _client(api_token=None)._headers(device_no="override")["X-Device-No"] == "override"


def test_ingest_and_retrieve_all_contract_branches():
    client = _client(user_tokens=["u"], device_no="default")
    client._request_json = MagicMock(
        return_value={"job_id": "j", "session_id": "s2", "status": "accepted"}
    )
    handle = client.ingest_dialog_v1(
        session_id="s",
        turns=[CanonicalTurnV1(turn_id="t", role="user", text="x")],
        client_meta={"device_no": "meta", "other": True},
    )
    body = client._request_json.call_args.kwargs["json_body"]
    assert body["user_tokens"] == ["u"] and body["client_meta"]["other"] is True
    assert handle.session_id == "s2" and handle.status_url is None
    with pytest.raises(ValueError, match="session_id"):
        client.ingest_dialog_v1(session_id="", turns=[])

    client._request_json.reset_mock(return_value=True)
    client._request_json.return_value = {"status": "ok"}
    payload = client.retrieve_dialog_v2(
        query=" q ", session_id=" s ", topk=2, strategy="unsupported", client_meta={"x": 1}
    )
    assert payload == {"status": "ok"}
    body = client._request_json.call_args.kwargs["json_body"]
    assert body == {
        "group_id": "s",
        "query": "q",
        "top_k": 2,
        "tenant_id": "tenant-1",
        "user_tokens": ["u"],
        "client_meta": {"x": 1},
    }
    with pytest.raises(ValueError, match="query"):
        client.retrieve_dialog_v2(query="")

    hybrid = _client(device_no="d")
    hybrid._request_json = MagicMock(return_value={"ok": True})
    assert hybrid.retrieve_dialog_hybrid(query="q", debug=True) == {"ok": True}
    assert hybrid._request_json.call_args.kwargs["json_body"]["debug"] is True
    with pytest.raises(ValueError, match="query"):
        hybrid.retrieve_dialog_hybrid(query=" ")
    with pytest.raises(ValueError, match="device_no"):
        _client().retrieve_dialog_hybrid(query="q")

    client._request_json = MagicMock(return_value={"job_id": "j", "status": "done"})
    assert client.get_job(" j ").job_id == "j"
    with pytest.raises(ValueError, match="job_id"):
        client.get_job("")


def test_saas_device_metadata_branches():
    client = _client(mode="saas", tenant_id="__from_api_key__")
    client._request_json = MagicMock(return_value={})
    client.ingest_dialog_v1(
        session_id="s",
        turns=[],
        group_id="g",
        group_name="name",
        client_meta={"device_no": "d"},
    )
    assert client._request_json.call_args.kwargs["json_body"]["client_meta"] == {"device_no": "d"}
    client.retrieve_dialog_v2(query="q", device_no="d", strategy="dialog_v1")
    body = client._request_json.call_args.kwargs["json_body"]
    assert body["client_meta"] == {"device_no": "d"}
    assert "tenant_id" not in body and "user_tokens" not in body


def test_commit_handle_timeout_and_status():
    backend = MagicMock()
    backend.get_job.return_value = JobStatusV1(job_id="j", session_id="s", status="queued")
    handle = CommitHandle(backend, "j", "s", "c")
    assert handle.status().status == "queued"
    with patch("memaura.client.time.monotonic", side_effect=[0.0, 0.5, 2.0]), patch(
        "memaura.client.time.sleep"
    ) as sleep:
        assert handle.wait(timeout_s=1, poll_interval_s=0.25).status == "queued"
        sleep.assert_called_once_with(0.25)


def test_request_retries_network_status_and_invalid_json():
    request = httpx.Request("GET", "https://example.test")
    retrying_http = MagicMock()
    retrying_http.request.side_effect = [
        httpx.ConnectError("no", request=request),
        _response(json_data={"ok": True}),
    ]
    client = _client(
        http=retrying_http,
        retry_config=RetryConfig(max_retries=1, base_backoff_seconds=0, jitter=False),
    )
    assert client._request_json("get", "/x") == {"ok": True}

    status_http = MagicMock()
    status_http.request.side_effect = [
        _response(503, json_data={"message": "later"}, headers={"Retry-After": "0"}),
        _response(json_data={"ok": True}),
    ]
    client = _client(
        http=status_http,
        retry_config=RetryConfig(max_retries=1, base_backoff_seconds=0, jitter=False),
    )
    assert client._request_json("GET", "/x") == {"ok": True}

    failed = MagicMock()
    failed.request.side_effect = RuntimeError("boom")
    with pytest.raises(MemAuraClientError, match="http_request_failed"):
        _client(http=failed)._request_json("GET", "/x")

    invalid = MagicMock()
    invalid.request.return_value = _response(text="not-json")
    with pytest.raises(MemAuraClientError, match="invalid_json_response: not-json"):
        _client(http=invalid)._request_json("GET", "/x")

    class UnreadableResponse:
        status_code = 200

        def json(self):
            raise ValueError("bad")

        @property
        def text(self):
            raise RuntimeError("unreadable")

    unreadable = MagicMock()
    unreadable.request.return_value = UnreadableResponse()
    with pytest.raises(MemAuraClientError, match="<unreadable>"):
        _client(http=unreadable)._request_json("GET", "/x")


def test_low_level_retry_and_response_helpers():
    assert _device_no_from_meta(None) is None
    assert _device_no_from_meta({"device_no": None}) is None
    assert _device_no_from_meta({"device_no": " d "}) == "d"
    headers = {"x-request-id": " old "}
    assert _ensure_request_id(headers) == "old"
    generated = {}
    assert _ensure_request_id(generated).startswith("req_")
    assert "X-Request-ID" in generated
    assert _should_retry_status(429) and not _should_retry_status(500)
    request = httpx.Request("GET", "https://x")
    assert _should_retry_exc(httpx.ConnectError("x", request=request))
    assert not _should_retry_exc(ValueError("x"))

    with patch("memaura.client.time.sleep") as sleep:
        _sleep_backoff(RetryConfig(max_wait_seconds=2), 0, 3)
        sleep.assert_called_once_with(2.0)
    with patch("memaura.client.random.uniform", return_value=0.25), patch(
        "memaura.client.time.sleep"
    ) as sleep:
        _sleep_backoff(RetryConfig(base_backoff_seconds=1, jitter=True), 1, None)
        sleep.assert_called_once_with(0.25)
    with patch("memaura.client.time.sleep") as sleep:
        _sleep_backoff(RetryConfig(base_backoff_seconds=0, jitter=False), 0, None)
        sleep.assert_not_called()

    assert _parse_retry_after(_response(headers={})) is None
    assert _parse_retry_after(_response(headers={"Retry-After": "2.9"})) == 2
    assert _parse_retry_after(_response(headers={"Retry-After": "bad"})) is None
    assert _parse_error_payload(_response(json_data=[1])) == {}
    assert _parse_error_payload(_response(text="bad")) == {}


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, MemAuraAuthError),
        (403, MemAuraForbiddenError),
        (402, MemAuraQuotaExceededError),
        (429, MemAuraRateLimitError),
        (413, MemAuraPayloadTooLargeError),
        (400, MemAuraValidationError),
        (500, MemAuraServerError),
        (418, MemAuraHttpError),
    ],
)
def test_http_error_mapping(status, error_type):
    error = _http_error_from_response(
        _response(status, json_data={"detail": "failure"}, headers={"X-Request-ID": "server"}),
        request_id="client",
    )
    assert type(error) is error_type
    assert error.request_id == "server"
    assert _error_class_for_status(status) is error_type


def test_http_error_diagnostics_and_configuration_hint():
    hinted = _http_error_from_response(
        _response(
            400,
            json_data={
                "message": "missing config",
                "data": {"error": "missing_core_requirements", "missing": ["llm_api_key"]},
            },
        ),
        request_id="r",
    )
    assert "Memory Policy" in str(hinted)

    raw = _http_error_from_response(_response(404, text="raw failure"), request_id="fallback")
    assert "raw failure" in str(raw) and raw.request_id == "fallback"

    class BrokenTextResponse:
        status_code = 404
        headers = {}

        def json(self):
            raise ValueError("bad")

        @property
        def text(self):
            raise RuntimeError("bad")

    assert "request_failed" in str(
        _http_error_from_response(BrokenTextResponse(), request_id=None)
    )


def test_unwrap_api_payload_variants():
    with pytest.raises(MemAuraClientError, match="expected object"):
        _unwrap_api_payload([], request_id="r")
    assert _unwrap_api_payload({"plain": True}, request_id=None) == {"plain": True}
    assert _unwrap_api_payload(
        {"success": True, "code": "invalid", "data": "value"}, request_id=None
    ) == {"data": "value"}
    assert _unwrap_api_payload(
        {"success": True, "code": 200, "data": {"ok": True}}, request_id=None
    ) == {"ok": True}
    with pytest.raises(MemAuraServerError):
        _unwrap_api_payload(
            {"success": False, "code": "invalid", "data": None}, request_id="r"
        )
    with pytest.raises(MemAuraValidationError):
        _unwrap_api_payload(
            {"success": False, "code": 400, "error": "bad", "data": None}, request_id="r"
        )


def test_memory_datetime_models_and_lifecycle():
    now = datetime.now(timezone.utc)
    assert _parse_datetime(now) is now
    assert _parse_datetime(" ") is None
    assert _parse_datetime("2024-01-01T00:00:00Z").tzinfo is not None
    assert _parse_datetime("not-a-date") is None

    backend = MagicMock()
    memory = Memory.__new__(Memory)
    memory._client = backend
    memory._device_no = "d"
    assert memory.__enter__() is memory
    memory.__exit__(None, None, None)
    backend.close.assert_called_once()
    with pytest.raises(ValueError, match="job_id"):
        JobOperations(backend).wait(" ")


def test_memory_search_error_and_response_branches():
    memory = Memory.__new__(Memory)
    memory._device_no = "d"
    memory._client = MagicMock()
    memory._client.retrieve_dialog_v2.side_effect = RuntimeError("regular")
    with pytest.raises(RuntimeError, match="regular"):
        memory.search("q")
    memory._client.retrieve_dialog_hybrid.side_effect = RuntimeError("hybrid")
    silent = memory.search_hybrid("q", fail_silent=True)
    assert not silent and "hybrid" in silent.error
    with pytest.raises(RuntimeError, match="hybrid"):
        memory.search_hybrid("q")
    memory._client.retrieve_dialog_hybrid.side_effect = None
    memory._client.retrieve_dialog_hybrid.return_value = {"evidence_details": []}
    assert not memory.search_hybrid("q")

    response = {
        "evidence_details": [
            {"text": ""},
            {
                "event_id": "e",
                "text": "fact",
                "score": 0.7,
                "timestamp": "2024-01-01T00:00:00Z",
                "source": None,
                "role": None,
                "sender_name": None,
                "atomic_facts": "invalid",
                "group_id": None,
                "entities": ["x"],
            },
        ],
        "requested_group_id": "g",
    }
    result = memory._search_result_from_response(query="q", resp=response, latency_ms=1)
    assert len(result) == 1 and result.items[0].source == "unknown"
    assert result.evidence_details[0].atomic_facts == []


def test_conversation_remaining_validation_and_delta_paths():
    with pytest.raises(ValueError, match="conversation_id"):
        Conversation(MagicMock(), " ")
    conv = Conversation(MagicMock(), "c", auto_timestamp=False)
    with pytest.raises(ValueError, match="turn_id"):
        conv.add({"role": "user", "content": "x", "turn_id": " "})
    with pytest.raises(ValueError, match="refer_list"):
        conv.add({"role": "user", "content": "x", "refer_list": "bad"})
    with pytest.raises(ValueError, match="refer_list"):
        conv.add({"role": "user", "content": "x", "refer_list": [""]})
    conv.add({"role": "user", "content": "x", "timestamp": " now ", "name": " Alice "})
    assert conv._buffer[0].timestamp_iso == "now" and conv._buffer[0].name == "Alice"
    no_timestamp = Conversation(MagicMock(), "c", auto_timestamp=False)
    no_timestamp.add({"role": "user", "content": "x"})
    assert no_timestamp._buffer[0].timestamp_iso is None

    empty = Conversation(MagicMock(), "c").commit()
    assert empty.completed and empty.message_count == 0

    delta = Conversation(MagicMock(), "c")
    delta.add({"role": "user", "content": "old", "turn_id": "t1"})
    delta._cursor_last_committed = "t9"
    assert delta.commit().message_count == 0
    assert delta._get_delta_turns() == []


def test_direct_retrieval_without_optional_metadata_or_user_tokens():
    client = _client()
    client._request_json = MagicMock(return_value={})
    client.retrieve_dialog_v2(query="q")
    body = client._request_json.call_args.kwargs["json_body"]
    assert body == {"group_id": None, "query": "q", "top_k": 30, "tenant_id": "tenant-1"}

    error = _http_error_from_response(
        _response(
            400,
            json_data={
                "message": "missing config",
                "data": {"error": "missing_core_requirements", "missing": ["unrelated"]},
            },
        ),
        request_id="r",
    )
    assert "Memory Policy" not in str(error)
