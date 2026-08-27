from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.dependencies import ServiceContainer
from app.main import create_app
from app.rag.evidence import Evidence


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        xf_app_id="app-id",
        xf_embedding_api_secret="embedding-secret",
        xf_maas_api_key="maas-key",
        xf_maas_api_secret="maas-secret",
        xf_maas_resource_id="resource-id",
        xf_maas_service_id="service-id",
        xf_workflow_api_key="workflow-key",
        xf_workflow_api_secret="workflow-secret",
        xf_workflow_flow_id="flow-id",
        tools_service_token="tool-token",
        xf_chatdoc_repo_id="repo-123",
    )


class Retriever:
    def __init__(self, evidence):
        self.evidence = evidence

    def ready_details(self):
        return {
            "status": "ready",
            "backend": "chatdoc",
            "sources": 30,
            "repo": "repo-123",
        }

    def get_evidence(self, evidence_id):
        if self.evidence and self.evidence.evidence_id == evidence_id:
            return self.evidence
        return None


def _container(retriever):
    return ServiceContainer(
        retriever=retriever,
        generation=SimpleNamespace(),
        cases=SimpleNamespace(),
        citations=SimpleNamespace(),
        contexts=SimpleNamespace(),
        workflow=SimpleNamespace(),
    )


def test_ready_reports_chatdoc_backend():
    app = create_app(settings=_settings(), container=_container(Retriever(None)))

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "backend": "chatdoc",
        "sources": 30,
        "repo": "repo-123",
    }


def test_source_endpoint_resolves_evidence_from_chatdoc_retriever_cache():
    evidence = Evidence(
        evidence_id="evidence-1",
        document_id="document-1",
        title="粮食安全法",
        source="政策文件类/粮食安全法.pdf",
        text="政府粮食储备实行专仓储存。",
        score=0.8,
    )
    app = create_app(
        settings=_settings(),
        container=_container(Retriever(evidence)),
    )

    with TestClient(app) as client:
        response = client.get("/v1/sources/evidence-1")

    assert response.status_code == 200
    assert response.json()["source"] == "政策文件类/粮食安全法.pdf"
