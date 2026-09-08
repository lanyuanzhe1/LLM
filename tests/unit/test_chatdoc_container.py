import asyncio
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.main import build_container
from app.rag.chatdoc_retriever import ChatDocRetriever


def _settings(manifest_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        xf_app_id="app-id",
        xf_embedding_api_secret="shared-secret",
        xf_maas_api_key="maas-key",
        xf_maas_api_secret="maas-secret",
        xf_maas_resource_id="resource-id",
        xf_maas_service_id="service-id",
        xf_workflow_api_key="workflow-key",
        xf_workflow_api_secret="workflow-secret",
        xf_workflow_flow_id="flow-id",
        tools_service_token="tool-token",
        xf_chatdoc_repo_id="repo-123",
        chatdoc_manifest_path=manifest_path,
        openai_compat_api_key="test-compat-key",
    )


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "backend": "iflytek_chatdoc",
                "repo_id": "repo-123",
                "sources": {
                    "doc.pdf": {
                        "sha256": "a" * 64,
                        "source_type": None,
                        "uploads": [
                            {"file_id": "file-1", "status": "vectored"}
                        ],
                    }
                },
            }
        )
    )


def test_build_container_uses_chatdoc(monkeypatch, tmp_path):
    manifest = tmp_path / "chatdoc.json"
    _write_manifest(manifest)
    captured = {}

    class Closeable:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def close(self):
            pass

    class ChatDoc(Closeable):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured["chatdoc"] = kwargs

        async def search(self, **kwargs):
            return []

    class MaaS(Closeable):
        pass

    class Workflow(Closeable):
        pass

    monkeypatch.setattr("app.main.IflytekChatDocClient", ChatDoc)
    monkeypatch.setattr("app.main.IflytekMaaSClient", MaaS)
    monkeypatch.setattr("app.main.XingchenWorkflowClient", Workflow)

    built, closeables = build_container(_settings(manifest))

    assert isinstance(built.retriever, ChatDocRetriever)
    assert captured["chatdoc"]["api_secret"] == "shared-secret"
    # 默认 local 编排器不是 closeable，仅 chatdoc 与 maas 需要关闭
    assert len(closeables) == 2
    for item in closeables:
        asyncio.run(item.close())


def test_build_container_defaults_to_local_workflow(monkeypatch, tmp_path):
    from app.services.local_workflow import LocalWorkflow

    manifest = tmp_path / "chatdoc.json"
    _write_manifest(manifest)

    class Closeable:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def close(self):
            pass

    class ChatDoc(Closeable):
        async def search(self, **kwargs):
            return []

    class MaaS(Closeable):
        pass

    class Workflow(Closeable):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            raise AssertionError("local provider must not build Xingchen")

    monkeypatch.setattr("app.main.IflytekChatDocClient", ChatDoc)
    monkeypatch.setattr("app.main.IflytekMaaSClient", MaaS)
    monkeypatch.setattr("app.main.XingchenWorkflowClient", Workflow)

    built, closeables = build_container(_settings(manifest))

    assert isinstance(built.workflow, LocalWorkflow)
    # 对账上下文必须与容器共享同一存储，否则网关无法完成校验
    assert built.workflow._contexts is built.contexts
    assert built.workflow._retriever is built.retriever
    assert len(closeables) == 2
    for item in closeables:
        asyncio.run(item.close())


def test_build_container_selects_xingchen_for_xingchen_provider(
    monkeypatch, tmp_path
):
    manifest = tmp_path / "chatdoc.json"
    _write_manifest(manifest)

    class Closeable:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def close(self):
            pass

    class ChatDoc(Closeable):
        async def search(self, **kwargs):
            return []

    class MaaS(Closeable):
        pass

    class Workflow(Closeable):
        pass

    monkeypatch.setattr("app.main.IflytekChatDocClient", ChatDoc)
    monkeypatch.setattr("app.main.IflytekMaaSClient", MaaS)
    monkeypatch.setattr("app.main.XingchenWorkflowClient", Workflow)

    built, closeables = build_container(
        _settings(manifest).model_copy(
            update={"workflow_provider": "xingchen"}
        )
    )

    assert isinstance(built.workflow, Workflow)
    assert len(closeables) == 3
    for item in closeables:
        asyncio.run(item.close())


def test_build_container_rejects_repo_id_mismatch(tmp_path):
    manifest = tmp_path / "chatdoc.json"
    _write_manifest(manifest)
    settings = _settings(manifest).model_copy(
        update={"xf_chatdoc_repo_id": "different-repo"}
    )

    try:
        build_container(settings)
    except Exception as exc:
        assert getattr(exc, "code", None) == "CONFIGURATION_ERROR"
    else:
        raise AssertionError("repo mismatch was accepted")


def test_build_container_requires_chatdoc_repo_configuration(tmp_path):
    settings = _settings(tmp_path / "missing.json").model_copy(
        update={"xf_chatdoc_repo_id": None}
    )

    with pytest.raises(ConfigurationError, match="ChatDoc"):
        build_container(settings)
