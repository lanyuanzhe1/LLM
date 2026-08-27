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
