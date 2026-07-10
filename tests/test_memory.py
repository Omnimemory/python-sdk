from __future__ import annotations

import importlib
import inspect
import pkgutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

import memaura
from memaura.client import MemoryClient, MemAuraClientError, MemAuraHttpError
from memaura.memory import DEFAULT_ENDPOINT, Conversation, Memory
from memaura.models import AddResult, MemoryItem, SearchResult


PUBLIC_EXPORTS = {
    "__version__",
    "Memory",
    "Conversation",
    "MemoryItem",
    "SearchResult",
    "AddResult",
    "MemAuraClientError",
    "MemAuraHttpError",
    "MemAuraAuthError",
    "MemAuraForbiddenError",
    "MemAuraRateLimitError",
    "MemAuraQuotaExceededError",
    "MemAuraPayloadTooLargeError",
    "MemAuraValidationError",
    "MemAuraServerError",
}


def _mock_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", "https://example.test"))


class TestPackageMetadata:
    def test_memaura_is_the_only_public_package_namespace(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        legacy_namespace = "o" + "mem"

        assert importlib.util.find_spec("memaura") is not None
        assert not (root / legacy_namespace).exists()
        assert 'name = "memaura"' in pyproject

    def test_release_workflows_use_ci_and_trusted_publishing(self):
        root = Path(__file__).resolve().parents[1]
        ci_workflow = root / ".github" / "workflows" / "python-sdk-ci.yml"
        release_workflow = (
            root / ".github" / "workflows" / "python-sdk-pypi-release.yml"
        )

        assert ci_workflow.is_file()
        ci_text = ci_workflow.read_text(encoding="utf-8")
        release_text = release_workflow.read_text(encoding="utf-8")
        assert '"3.8"' in ci_text
        assert '"3.11"' in ci_text
        assert '"3.13"' in ci_text
        assert "resume_publish" in release_text
        assert "id-token: write" in release_text
        assert "PYPI_API_TOKEN" not in release_text

    def test_build_metadata_supports_python_38_setuptools(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

        assert 'license = {text = "MIT"}' in pyproject

    def test_workflows_allow_a_metadata_24_compatible_twine(self):
        root = Path(__file__).resolve().parents[1]
        for workflow_name in (
            "python-sdk-ci.yml",
            "python-sdk-pypi-release.yml",
        ):
            workflow = (
                root / ".github" / "workflows" / workflow_name
            ).read_text(encoding="utf-8")
            assert "twine>=5,<6" not in workflow
            assert '"twine>=5"' in workflow
            assert "actions/checkout@v6" in workflow
            assert "actions/setup-python@v6" in workflow

    def test_public_metadata_uses_memaura_branding(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        init_py = (root / "memaura" / "__init__.py").read_text(encoding="utf-8")

        assert 'name = "memaura"' in pyproject
        assert "MemAura" in pyproject
        assert "MemAura" in init_py
        assert "github.com/VisMemo" not in pyproject
        assert "github.com/VisMemo" not in init_py

    def test_public_docs_are_available_in_english_and_chinese(self):
        root = Path(__file__).resolve().parents[1]
        readme_en = (root / "README.md").read_text(encoding="utf-8")
        readme_zh = (root / "README.zh.md").read_text(encoding="utf-8")
        manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")

        assert "Languages: [English](README.md) | [中文](README.zh.md)" in readme_en
        assert "语言: [English](README.md) | [中文](README.zh.md)" in readme_zh
        assert "快速开始" in readme_zh
        assert "MemAura" in readme_en
        assert "MemAura" in readme_zh
        assert "pip install memaura" in readme_en
        assert "pip install memaura" in readme_zh
        assert "from memaura import Memory" in readme_en
        assert "from memaura import Memory" in readme_zh
        assert "TKG Features" not in readme_en
        assert "TKG 能力" not in readme_zh
        assert "include README.zh.md" in manifest

        for removed_feature in ("user_id", "event_id", "Graph/TKG", "debug", "Self-hosted"):
            assert removed_feature not in readme_en
            assert removed_feature not in readme_zh

        signature = "search(query, *, limit=10, session_id=None, fail_silent=False)"
        assert signature in readme_en
        assert signature in readme_zh
        assert "[Contributing](CONTRIBUTING.md)" in readme_en
        assert "[贡献指南](CONTRIBUTING.zh.md)" in readme_zh
        assert "[Release Guide](RELEASE.md)" in readme_en
        assert "[发布指南](RELEASE.zh.md)" in readme_zh
        assert (root / "CONTRIBUTING.md").is_file()
        assert (root / "CONTRIBUTING.zh.md").is_file()
        assert (root / "SECURITY.md").is_file()
        assert (root / "SECURITY.zh.md").is_file()
        assert (root / "CHANGELOG.md").is_file()
        assert (root / "CHANGELOG.zh.md").is_file()
        assert (root / "RELEASE.md").is_file()
        assert (root / "RELEASE.zh.md").is_file()
        assert not (root / "SAAS_ARCHITECTURE_ALIGNMENT.md").exists()
        assert not (root / "docs" / "superpowers").exists()

        for filename in (
            "CONTRIBUTING.md",
            "CONTRIBUTING.zh.md",
            "SECURITY.md",
            "SECURITY.zh.md",
            "CHANGELOG.md",
            "CHANGELOG.zh.md",
            "RELEASE.md",
            "RELEASE.zh.md",
        ):
            assert f"include {filename}" in manifest

    def test_no_local_env_or_bytecode_files_are_tracked(self):
        root = Path(__file__).resolve().parents[1]
        tracked = set(
            subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
        )

        assert ".env" not in tracked
        assert not any(path.startswith("__pycache__/") for path in tracked)

    def test_packaged_modules_import_without_internal_core_dependencies(self):
        for module in pkgutil.walk_packages(memaura.__path__, prefix="memaura."):
            importlib.import_module(module.name)

    def test_major_version_and_python_support_match_public_boundary(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

        assert memaura.__version__ == "1.0.0"
        assert 'version = "1.0.0"' in pyproject
        assert '"Programming Language :: Python :: 3.13"' in pyproject


class TestPublicApiBoundary:
    def test_package_exports_only_supported_public_api(self):
        assert set(memaura.__all__) == PUBLIC_EXPORTS

    def test_removed_memory_arguments_and_methods_are_absent(self):
        assert "user_id" not in inspect.signature(Memory).parameters
        assert "sync_cursor" not in inspect.signature(Memory.conversation).parameters
        assert "debug" not in inspect.signature(Memory.search).parameters
        assert "debug" not in inspect.signature(Memory.search_hybrid).parameters

        for name in (
            "debug_config",
            "resolve_entity",
            "get_entity_history",
            "get_evidence_for",
            "explain_event",
            "search_events",
            "get_events_by_time",
        ):
            assert not hasattr(Memory, name)

    def test_removed_graph_and_session_symbols_are_not_public(self):
        for name in (
            "MemoryClient",
            "SessionBuffer",
            "CommitHandle",
            "RetryConfig",
            "CanonicalAttachmentV1",
            "CanonicalTurnV1",
            "JobStatusV1",
            "SessionStatusV1",
            "Entity",
            "Event",
            "Evidence",
            "EventContext",
            "ExtractedKnowledge",
            "MemAuraUnsupportedFeatureError",
        ):
            assert not hasattr(memaura, name)

    def test_result_models_omit_graph_and_debug_fields(self):
        assert "event_id" not in MemoryItem.__dataclass_fields__
        assert "debug" not in SearchResult.__dataclass_fields__


class TestMemoryInit:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="api_key is required"):
            Memory(api_key="")

    @patch("memaura.memory.MemoryClient")
    def test_defaults_to_public_v2_endpoint_and_saas_auth(self, mock_client_cls):
        Memory(api_key="qbk_test")

        call_kwargs = mock_client_cls.call_args.kwargs
        assert DEFAULT_ENDPOINT.startswith("https://")
        assert DEFAULT_ENDPOINT.endswith("/api/v2/memory")
        assert call_kwargs["base_url"] == DEFAULT_ENDPOINT
        assert call_kwargs["tenant_id"] == "__from_api_key__"
        assert call_kwargs["api_token"] == "qbk_test"
        assert call_kwargs["memory_domain"] == "dialog"
        assert call_kwargs["mode"] == "saas"
        assert "user_tokens" not in call_kwargs

    @patch("memaura.memory.MemoryClient")
    def test_accepts_default_device_number_for_device_scoped_memory(self, mock_client_cls):
        Memory(api_key="qbk_test", device_no="device-001")

        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["device_no"] == "device-001"


class TestMemoryAdd:
    @patch("memaura.memory.MemoryClient")
    def test_add_converts_openai_messages_and_fire_forget_returns_none(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_session.return_value = MagicMock(cursor_committed=None)
        mock_handle = MagicMock()
        mock_handle.job_id = "job-123"
        mock_client.ingest_dialog_v1.return_value = mock_handle

        mem = Memory(api_key="qbk_test", endpoint="https://api-test.example/api/v2/memory")
        result = mem.add(
            "conv-001",
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ],
        )

        assert result is None
        mock_client.ingest_dialog_v1.assert_called_once()
        call_kwargs = mock_client.ingest_dialog_v1.call_args.kwargs
        assert call_kwargs["session_id"] == "conv-001"
        assert len(call_kwargs["turns"]) == 2
        assert call_kwargs["turns"][0].text == "Hello"
        assert call_kwargs["turns"][1].text == "Hi!"

    @patch("memaura.memory.MemoryClient")
    def test_add_with_wait_returns_add_result(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_session.return_value = MagicMock(cursor_committed=None)
        mock_handle = MagicMock()
        mock_handle.job_id = "job-789"
        mock_handle.wait.return_value = MagicMock(status="COMPLETED")
        mock_client.ingest_dialog_v1.return_value = mock_handle

        mem = Memory(api_key="qbk_test")
        result = mem.add("conv-001", [{"role": "user", "content": "Test"}], wait=True)

        assert isinstance(result, AddResult)
        assert result.completed is True
        assert result.job_id == "job-789"
        mock_handle.wait.assert_called_once()


class TestConversation:
    @patch("memaura.memory.MemoryClient")
    def test_conversation_buffer(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_session.return_value = MagicMock(cursor_committed=None)
        mock_handle = MagicMock()
        mock_handle.job_id = "job-111"
        mock_client.ingest_dialog_v1.return_value = mock_handle

        conv = Memory(api_key="qbk_test").conversation("conv-001")
        conv.add({"role": "user", "content": "First"})
        conv.add({"role": "assistant", "content": "Reply"})

        assert not mock_client.ingest_dialog_v1.called
        result = conv.commit()

        assert mock_client.ingest_dialog_v1.called
        assert result.message_count == 2

    @patch("memaura.memory.MemoryClient")
    def test_conversation_context_manager_auto_commit(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_session.return_value = MagicMock(cursor_committed=None)
        mock_handle = MagicMock()
        mock_handle.job_id = "job-222"
        mock_client.ingest_dialog_v1.return_value = mock_handle

        with Memory(api_key="qbk_test").conversation("conv-001") as conv:
            conv.add({"role": "user", "content": "Hello"})
            assert not mock_client.ingest_dialog_v1.called

        assert mock_client.ingest_dialog_v1.called

    @patch("memaura.memory.MemoryClient")
    def test_conversation_no_commit_on_exception(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_session.return_value = MagicMock(cursor_committed=None)

        with pytest.raises(RuntimeError):
            with Memory(api_key="qbk_test").conversation("conv-001") as conv:
                conv.add({"role": "user", "content": "Hello"})
                raise RuntimeError("Something went wrong")

        assert not mock_client.ingest_dialog_v1.called

    def test_conversation_validates_role(self):
        conv = Conversation(MagicMock(), "conv-001")

        with pytest.raises(ValueError, match="role must be one of"):
            conv.add({"role": "invalid", "content": "Test"})

    def test_conversation_validates_content(self):
        conv = Conversation(MagicMock(), "conv-001")

        with pytest.raises(ValueError, match="content/text is empty"):
            conv.add({"role": "user", "content": ""})

    def test_conversation_accepts_text_field(self):
        conv = Conversation(MagicMock(), "conv-001")
        conv.add({"role": "user", "text": "Hello via text field"})

        assert len(conv._buffer) == 1
        assert conv._buffer[0].text == "Hello via text field"


class TestMemorySearch:
    @patch("memaura.memory.MemoryClient")
    def test_search_without_device_uses_legacy_v2_retrieval(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve_dialog_v2.return_value = {
            "evidence_details": [
                {"text": "Meeting at 10am", "score": 0.9, "source": "dialog"},
                {"text": "Call with Bob", "score": 0.8, "source": "dialog"},
            ]
        }

        result = Memory(api_key="qbk_test").search("meeting")

        assert isinstance(result, SearchResult)
        assert len(result) == 2
        assert result.items[0].text == "Meeting at 10am"
        mock_client.retrieve_dialog_v2.assert_called_once()
        mock_client.retrieve_dialog_hybrid.assert_not_called()

    @patch("memaura.memory.MemoryClient")
    def test_search_with_device_uses_hybrid_retrieval(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve_dialog_hybrid.return_value = {
            "evidence_details": [{"text": "Hybrid hit", "score": 0.93, "source": "hybrid"}],
            "strategy": "hybrid",
        }

        result = Memory(api_key="qbk_test", device_no="device-001").search("meeting", limit=3)

        assert len(result) == 1
        assert result.items[0].text == "Hybrid hit"
        assert result.strategy == "hybrid"
        mock_client.retrieve_dialog_hybrid.assert_called_once_with(
            query="meeting",
            session_id=None,
            top_k=3,
            device_no=None,
        )
        mock_client.retrieve_dialog_v2.assert_not_called()

    @patch("memaura.memory.MemoryClient")
    def test_search_hybrid_requires_configured_or_explicit_device_number(self, mock_client_cls):
        with pytest.raises(ValueError, match="device_no is required"):
            Memory(api_key="qbk_test").search_hybrid("query")

    @patch("memaura.memory.MemoryClient")
    def test_search_fail_silent_returns_empty(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.retrieve_dialog_v2.side_effect = Exception("Network error")

        result = Memory(api_key="qbk_test").search("test", fail_silent=True)

        assert isinstance(result, SearchResult)
        assert len(result) == 0
        assert result.error is not None
        assert "Network error" in result.error


class TestMemoryClientHttp:
    def test_unwraps_v2_envelope_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v2/memory/ingest"
            return httpx.Response(
                200,
                json={"success": True, "message": "ok", "code": 200, "data": {"job_id": "job-1"}},
                request=request,
            )

        client = MemoryClient(
            base_url="https://api.example/api/v2/memory",
            tenant_id="__from_api_key__",
            api_token="qbk_test",
            mode="saas",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        assert client._request_json("POST", "/ingest") == {"job_id": "job-1"}

    def test_raises_for_unsuccessful_v2_envelope_even_when_http_200(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "message": "Invalid email verification code",
                    "code": 400,
                    "data": {"error": "invalid_email_otp"},
                },
                request=request,
            )

        client = MemoryClient(
            base_url="https://api.example/api/v2/memory",
            tenant_id="__from_api_key__",
            api_token="qbk_test",
            mode="saas",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(MemAuraHttpError) as exc:
            client._request_json("POST", "/retrieval")
        assert exc.value.status_code == 400
        assert exc.value.error == "invalid_email_otp"

    def test_http_error_uses_v2_envelope_error_code(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "success": False,
                    "message": "Invalid email verification code",
                    "code": 400,
                    "data": {"error": "invalid_email_otp"},
                },
                request=request,
            )

        client = MemoryClient(
            base_url="https://api.example/api/v2/memory",
            tenant_id="__from_api_key__",
            api_token="qbk_test",
            mode="saas",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(MemAuraHttpError) as exc:
            client._request_json("POST", "/retrieval")
        assert exc.value.status_code == 400
        assert exc.value.error == "invalid_email_otp"

    def test_hybrid_retrieval_sends_device_number_header_and_body(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["headers"] = dict(request.headers)
            captured["json"] = __import__("json").loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "message": "ok",
                    "code": 200,
                    "data": {"evidence_details": [{"text": "hit", "score": 0.8}]},
                },
                request=request,
            )

        client = MemoryClient(
            base_url="https://api.example/api/v2/memory",
            tenant_id="__from_api_key__",
            api_token="qbk_test",
            device_no="device-001",
            mode="saas",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        payload = client.retrieve_dialog_hybrid(query="hi", top_k=5)

        assert payload["evidence_details"][0]["text"] == "hit"
        assert captured["path"] == "/api/v2/memory/retrieval/hybrid"
        assert captured["headers"]["x-api-key"] == "qbk_test"
        assert captured["headers"]["x-device-no"] == "device-001"
        assert captured["json"]["query"] == "hi"
        assert captured["json"]["top_k"] == 5
        assert captured["json"]["client_meta"] == {"device_no": "device-001"}
        assert "tenant_id" not in captured["json"]
        assert "user_tokens" not in captured["json"]


class TestModels:
    def test_memory_item_str(self):
        item = MemoryItem(text="Test memory", score=0.85)
        assert "[0.85] Test memory" in str(item)

    def test_search_result_empty_to_prompt(self):
        result = SearchResult(query="test", items=[])
        assert result.to_prompt() == ""

    def test_add_result_defaults(self):
        result = AddResult(conversation_id="conv-001", message_count=3)
        assert result.job_id is None
        assert result.completed is False
