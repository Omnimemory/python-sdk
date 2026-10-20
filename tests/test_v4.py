from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from memaura import MemoryV4, V4Job, V4JobTimeoutError, V4RetrievalResult
from memaura.client import MemAuraClientError, MemAuraHttpError
from memaura.v4 import V4JobOperations, _card_from_payload, _job_from_payload


def test_v4_ingest_retrieval_and_job_routes() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v3/memory/ingest_4":
            return httpx.Response(200, json={"success": True, "data": {"job_id": "job-1", "status": "queued"}})
        if request.url.path == "/api/v3/memory/ingest_4/jobs/job-1":
            return httpx.Response(200, json={"success": True, "data": {"status": "succeeded"}})
        if request.url.path == "/api/v3/memory/retrieval_4":
            return httpx.Response(200, json={"results": [{
                "card_id": "card-1", "role": "user", "content": "Prefers tea",
                "episodes": [{"episode_id": "episode-1", "summary": "Said they prefer tea"}],
            }]})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "missing"}})

    memory = MemoryV4(api_key="qbk_test", device_no="device-1")
    memory._client.close()
    memory._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        ack = memory.ingest([{"role": "user", "content": "I prefer tea"}])
        job = memory.jobs.get(ack.job_id)
        result = memory.retrieve("What do I prefer?", top_k=5)
    finally:
        memory.close()

    assert ack.job_id == "job-1"
    assert job.status == "succeeded"
    assert result.cards[0].card_id == "card-1"
    assert result.cards[0].episodes[0].episode_id == "episode-1"
    assert all(request.headers["x-api-key"] == "qbk_test" for request in requests)
    assert all(request.headers.get("x-device-no") == "device-1" for request in (requests[0], requests[2]))
    ingest_body = json.loads(requests[0].content)
    assert ingest_body["wait_for"] == "staged"
    assert "session_id" not in ingest_body
    retrieval_body = json.loads(requests[2].content)
    assert retrieval_body["vector_weight"] == 0.8
    assert retrieval_body["top_k"] == 5


def test_v4_write_is_not_retried_after_transport_failure() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    memory = MemoryV4(api_key="qbk_test", device_no="device-1")
    memory._client.close()
    memory._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        try:
            memory.ingest([{"role": "user", "content": "hello"}])
        except Exception:
            pass
    finally:
        memory.close()

    assert calls == 1


def test_v4_result_helpers_and_context_manager() -> None:
    empty = V4RetrievalResult(cards=[])
    assert not empty
    assert len(empty) == 0
    memory = MemoryV4(api_key="qbk_test")
    with patch.object(memory, "close") as close:
        with memory as entered:
            assert entered is memory
        close.assert_called_once()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"api_key": ""}, "api_key"),
        ({"api_key": "key", "endpoint": "relative"}, "absolute HTTP URL"),
        ({"api_key": "key", "endpoint": "http://"}, "absolute HTTP URL"),
    ],
)
def test_v4_init_validation(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        MemoryV4(**kwargs)


@pytest.mark.parametrize(
    ("turns", "kwargs", "message"),
    [
        ([], {}, "at least one"),
        ([{"content": "x"}], {"language": "fr"}, "language"),
        ([{"content": "x"}], {"wait_for": "done"}, "wait_for"),
        ([{"content": "x"}], {"wait_timeout_seconds": 0}, "wait_timeout"),
        ([{"content": " "}], {}, "content"),
    ],
)
def test_v4_ingest_validation(turns, kwargs, message) -> None:
    memory = MemoryV4(api_key="key")
    try:
        with pytest.raises(ValueError, match=message):
            memory.ingest(turns, **kwargs)
    finally:
        memory.close()


def test_v4_ingest_optional_fields_and_missing_job() -> None:
    memory = MemoryV4(api_key="key")
    memory._request = MagicMock(return_value={"job_id": "j", "wait_timed_out": True, "error": {"code": "x"}})
    job = memory.ingest(
        [{"content": " x ", "timestamp": None}], timezone="Asia/Shanghai",
        device_no="operation-device", wait_for="searchable", wait_timeout_seconds=3,
    )
    body = memory._request.call_args.args[2]
    assert body["timezone"] == "Asia/Shanghai"
    assert body["turns"] == [{"content": "x"}]
    assert job.wait_timed_out and job.error == {"code": "x"}
    memory._request.return_value = {}
    with pytest.raises(MemAuraClientError, match="missing job_id"):
        memory.ingest([{"content": "x"}])
    memory.close()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": ""}, "query"),
        ({"query": "x", "top_k": True}, "top_k"),
        ({"query": "x", "top_k": 101}, "top_k"),
        ({"query": "x", "vector_weight": True}, "vector_weight"),
        ({"query": "x", "vector_weight": -0.1}, "vector_weight"),
        ({"query": "x", "scope_type": "workspace"}, "scope_type"),
        ({"query": "x", "entity_match_mode": "other"}, "entity_match_mode"),
    ],
)
def test_v4_retrieval_validation(kwargs, message) -> None:
    memory = MemoryV4(api_key="key")
    try:
        with pytest.raises(ValueError, match=message):
            memory.retrieve(**kwargs)
    finally:
        memory.close()


def test_v4_retrieval_details_filters_and_invalid_shapes() -> None:
    memory = MemoryV4(api_key="key")
    payload = {
        "results": [{"card_id": "c", "role": "user", "content": "body", "episodes": [{}, "ignored"]}],
        "query_analysis": {"route": "both"},
    }
    memory._request = MagicMock(return_value=payload)
    result = memory.retrieve(
        "q", role="user", scope_type="device", tag_keys=["preference"],
        start_time="2026-01-01T00:00:00Z", end_time="2026-02-01T00:00:00Z",
        entity_id="entity-1", entity_match_mode="involved", participant_roles=["owner"],
        include_query_analysis=True, include_details=True,
    )
    body = memory._request.call_args.args[2]
    assert body["role"] == "user" and body["scope_type"] == "device"
    assert body["entity_match_mode"] == "involved" and body["participant_roles"] == ["owner"]
    assert result and result.details is payload and result.query_analysis == {"route": "both"}
    assert result.cards[0].episodes[0].episode_id == ""

    memory._request.return_value = {"results": [], "query_analysis": "invalid"}
    assert memory.retrieve("q").query_analysis is None
    memory._request.return_value = {}
    with pytest.raises(MemAuraClientError, match="missing results"):
        memory.retrieve("q")
    with pytest.raises(MemAuraClientError, match="Card must be an object"):
        _card_from_payload("bad")
    with pytest.raises(MemAuraClientError, match="episodes must be an array"):
        _card_from_payload({"episodes": "bad"})
    memory.close()


def test_v4_job_operations_wait_paths() -> None:
    memory = MagicMock()
    memory._request.return_value = {"status": "queued"}
    jobs = V4JobOperations(memory)
    assert jobs.get("job/a").job_id == "job/a"
    assert "%2F" in memory._request.call_args.args[1]
    with pytest.raises(ValueError, match="job_id"):
        jobs.get(" ")
    with pytest.raises(ValueError, match="greater than zero"):
        jobs.wait("j", timeout_s=0)

    jobs.get = MagicMock(side_effect=[V4Job("j", "buffered"), V4Job("j", "failed")])
    with patch("memaura.v4.time.sleep"), patch("memaura.v4.time.monotonic", side_effect=[0, 0, 0.1, 0.2]):
        assert jobs.wait("j", timeout_s=1).status == "failed"

    jobs.get = MagicMock(return_value=V4Job("j", "mystery"))
    with patch("memaura.v4.time.monotonic", side_effect=[0, 0]):
        with pytest.raises(MemAuraClientError, match="unexpected"):
            jobs.wait("j", timeout_s=1)

    jobs.get = MagicMock(return_value=V4Job("j", "queued"))
    with patch("memaura.v4.time.sleep"), patch("memaura.v4.time.monotonic", side_effect=[0, 0, 2, 2]):
        with pytest.raises(V4JobTimeoutError) as error:
            jobs.wait("j", timeout_s=1)
    assert error.value.job_id == "j" and error.value.last_job.status == "queued"


def test_v4_request_error_and_response_paths() -> None:
    responses = iter([
        httpx.Response(500, json={"message": "boom"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"error": {"code": "bad", "message": "no"}}, headers={"x-request-id": "r"}),
        httpx.Response(200, json={"error": {}}),
        httpx.Response(200, json={"success": True, "data": {"ok": True}}),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        response = next(responses)
        response.request = request
        return response

    memory = MemoryV4(api_key="key")
    memory._client.close()
    memory._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(MemAuraHttpError):
        memory._request("GET", "/one")
    with pytest.raises(MemAuraClientError, match="invalid_json"):
        memory._request("GET", "/two")
    with pytest.raises(MemAuraHttpError) as compact:
        memory._request("GET", "/three")
    assert compact.value.error == "bad" and compact.value.request_id == "r"
    with pytest.raises(MemAuraHttpError) as fallback:
        memory._request("GET", "/four")
    assert fallback.value.error == "request_failed"
    assert memory._request("GET", "/five", device_no="override") == {"ok": True}
    memory.close()


def test_v4_payload_helpers_cover_optional_values() -> None:
    job = _job_from_payload({"job_id": "j", "status": 7, "error": "ignored"})
    assert job.status == "7" and job.error is None
    with pytest.raises(MemAuraClientError, match="missing job_id"):
        _job_from_payload({})
    card = _card_from_payload({})
    assert card.card_id == card.role == card.content == "" and card.episodes == []
