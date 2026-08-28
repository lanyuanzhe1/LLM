import json

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.rag.evidence import Evidence
from app.schemas.events import WorkflowFrame


EVIDENCE = Evidence(
    evidence_id="sha256:evidence",
    document_id="sha256:document",
    title="低温储粮技术应用进展研究",
    source="knowledge/其他论文/低温储粮.pdf",
    page=3,
    section="低温对害虫的影响",
    text="低温条件可抑制储粮害虫的生长发育。",
    score=0.88,
    authority_level="research",
)


class RecordingWorkflow:
    answer = "低温能够抑制储粮害虫活动。[E1]"

    def __init__(self, contexts):
        self.contexts = contexts
        self.calls = []

    async def stream(self, parameters, uid):
        self.calls.append((parameters, uid))
        request_id = parameters["REQUEST_ID"]
        await self.contexts.set_retrieval_result(
            request_id,
            [EVIDENCE],
            sufficient=True,
        )
        await self.contexts.set_validation_result(
            request_id,
            valid=True,
            answer=self.answer,
            citation_ids=[EVIDENCE.evidence_id],
        )
        for content in ("低温能够抑制", "储粮害虫活动。[E1]"):
            yield WorkflowFrame.model_validate(
                {
                    "code": 0,
                    "message": "Success",
                    "id": "provider-session",
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "content": content,
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )


class FailingWorkflow:
    async def stream(self, parameters, uid):
        raise RuntimeError("provider-secret-must-not-leak")
        yield


def _settings(**overrides):
    values = {
        "xf_app_id": "app-id",
        "xf_embedding_api_secret": "embedding-secret",
        "xf_maas_api_key": "maas-key",
        "xf_maas_api_secret": "maas-secret",
        "xf_maas_resource_id": "resource-id",
        "xf_maas_service_id": "service-id",
        "xf_workflow_api_key": "workflow-key",
        "xf_workflow_api_secret": "workflow-secret",
        "xf_workflow_flow_id": "flow-id",
        "tools_service_token": "tool-token",
        "openai_compat_api_key": "test-compat-key",
        "openai_compat_model_id": "grain-storage-agent",
        "openai_compat_model_name": "粮储知识助手",
        "openai_compat_project_id": "grain-project-2026",
        "openai_compat_history_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _client(workflow=None, **settings_overrides):
    from app.main import create_app

    contexts = RequestContextStore(ttl_seconds=300)
    resolved_workflow = workflow or RecordingWorkflow(contexts)
    container = ServiceContainer(
        retriever=None,
        generation=None,
        cases=None,
        citations=None,
        contexts=contexts,
        workflow=resolved_workflow,
    )
    return (
        TestClient(
            create_app(
                settings=_settings(**settings_overrides),
                container=container,
            )
        ),
        resolved_workflow,
    )


def _auth():
    return {"Authorization": "Bearer test-compat-key"}


def _request(**overrides):
    payload = {
        "model": "grain-storage-agent",
        "messages": [{"role": "user", "content": "低温为何抑制害虫？"}],
        "stream": False,
    }
    payload.update(overrides)
    return payload


def _stream_payloads(response):
    payloads = []
    for block in response.text.split("\n\n"):
        if not block:
            continue
        assert block.startswith("data: ")
        raw = block[6:]
        payloads.append(
            "[DONE]" if raw == "[DONE]" else json.loads(raw)
        )
    return payloads


def test_models_requires_key_and_exposes_only_grain_agent():
    client, _ = _client()

    unauthorized = client.get("/v1/models")
    response = client.get("/v1/models", headers=_auth())

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "invalid_api_key"
    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "grain-storage-agent",
                "name": "粮储知识助手",
                "object": "model",
                "created": 0,
                "owned_by": "grain-learning",
            }
        ],
    }


def test_non_stream_chat_maps_session_user_and_returns_sources():
    client, workflow = _client()
    headers = {
        **_auth(),
        "X-OpenWebUI-Chat-Id": "chat-01J5",
        "X-OpenWebUI-User-Id": "user-42",
    }

    first = client.post(
        "/v1/chat/completions",
        headers=headers,
        json=_request(),
    )
    second = client.post(
        "/v1/chat/completions",
        headers=headers,
        json=_request(
            messages=[
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "第一答"},
                {"role": "user", "content": "继续解释"},
            ]
        ),
    )

    assert first.status_code == 200
    assert first.json()["choices"][0]["message"]["content"] == workflow.answer
    assert first.json()["sources"][0]["metadata"][0]["page"] == 3
    assert second.status_code == 200
    assert [call[0]["SESSION_ID"] for call in workflow.calls] == [
        "chat-01J5",
        "chat-01J5",
    ]
    assert workflow.calls[0][0]["AGENT_USER_INPUT"] == "低温为何抑制害虫？"
    second_input = workflow.calls[1][0]["AGENT_USER_INPUT"]
    assert "第一问" in second_input
    assert "第一答" in second_input
    assert second_input.endswith("继续解释")
    assert [call[1] for call in workflow.calls] == ["user-42", "user-42"]
    assert all(call[0]["USER_ROLE"] == "student" for call in workflow.calls)
    assert all(
        call[0]["PROJECT_ID"] == "grain-project-2026"
        for call in workflow.calls
    )


def test_history_packed_into_workflow_input():
    client, workflow = _client()

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(
            messages=[
                {"role": "user", "content": "什么是低温储粮"},
                {"role": "assistant", "content": "指利用低温抑制害虫霉菌"},
                {"role": "user", "content": "那仓房气密性呢"},
            ],
        ),
    )

    assert response.status_code == 200
    sent = workflow.calls[-1][0]["AGENT_USER_INPUT"]
    assert sent.startswith("[对话历史]")
    assert "低温储粮" in sent and "仓房气密性" in sent
    assert "[当前问题]" in sent
    assert workflow.calls[-1][0]["TASK_TYPE"] == "knowledge_qa"


def test_chat_sends_only_last_question_when_history_disabled():
    client, workflow = _client(openai_compat_history_enabled=False)
    question = "低温为什么能抑制害虫？"

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(
            messages=[
                {"role": "user", "content": "什么是低温储粮"},
                {"role": "assistant", "content": "指利用低温抑制害虫霉菌"},
                {"role": "user", "content": question},
            ],
        ),
    )

    assert response.status_code == 200
    call = workflow.calls[-1][0]
    assert call["AGENT_USER_INPUT"] == question
    assert call["TASK_TYPE"] == "knowledge_qa"


def test_chat_uses_server_project_and_ignores_client_override():
    client, workflow = _client()

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(project_id="attacker-project"),
    )

    assert response.status_code == 200
    assert workflow.calls[-1][0]["PROJECT_ID"] == "grain-project-2026"


def test_chat_keeps_base_only_context_when_project_is_unset():
    client, workflow = _client(openai_compat_project_id=None)

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(),
    )

    assert response.status_code == 200
    assert workflow.calls[-1][0]["PROJECT_ID"] == ""


def test_stream_chat_emits_role_content_sources_finish_and_done():
    client, workflow = _client()

    response = client.post(
        "/v1/chat/completions",
        headers={**_auth(), "X-OpenWebUI-Chat-Id": "chat-stream"},
        json=_request(stream=True),
    )
    payloads = _stream_payloads(response)
    statuses = [
        item["event"]["data"]
        for item in payloads
        if isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
    ]
    source = next(
        item
        for item in payloads
        if isinstance(item, dict)
        and item.get("event", {}).get("type") == "source"
    )

    assert response.status_code == 200
    assert payloads[0]["choices"][0]["delta"]["role"] == "assistant"
    assert statuses == [
        {
            "description": "正在检索粮储知识库并核对依据",
            "done": False,
        },
        {
            "description": "已核对知识库依据",
            "done": True,
        },
    ]
    assert "".join(
        payload["choices"][0]["delta"].get("content", "")
        for payload in payloads
        if isinstance(payload, dict) and payload.get("choices")
    ) == workflow.answer
    assert source["event"]["data"]["source"]["name"] == EVIDENCE.title
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[-1] == "[DONE]"


def test_generic_stream_omits_openwebui_status_and_keeps_answer_sources():
    client, workflow = _client()

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(stream=True),
    )
    payloads = _stream_payloads(response)

    assert response.status_code == 200
    assert not any(
        isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
        for item in payloads
    )
    assert "".join(
        item["choices"][0]["delta"].get("content", "")
        for item in payloads
        if isinstance(item, dict) and item.get("choices")
    ) == workflow.answer
    assert any(
        isinstance(item, dict)
        and item.get("event", {}).get("type") == "source"
        for item in payloads
    )
    assert payloads[-1] == "[DONE]"


def test_chat_rejects_bad_key_unknown_model_and_invalid_headers():
    client, _ = _client()

    bad_key = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer wrong-key"},
        json=_request(),
    )
    unknown_model = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(model="general-chat"),
    )
    invalid_header = client.post(
        "/v1/chat/completions",
        headers={**_auth(), "X-OpenWebUI-Chat-Id": "chat id"},
        json=_request(),
    )

    assert bad_key.status_code == 401
    assert bad_key.json()["error"]["code"] == "invalid_api_key"
    assert unknown_model.status_code == 404
    assert unknown_model.json()["error"]["code"] == "model_not_found"
    assert invalid_header.status_code == 400
    assert invalid_header.json()["error"]["code"] == "invalid_request_error"


def test_chat_validation_errors_use_openai_error_shape():
    client, _ = _client()

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(messages=[{"role": "system", "content": "无用户消息"}]),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "message": "聊天请求无效",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_request_error",
        }
    }


def test_unauthorized_malformed_chat_is_rejected_before_body_parsing():
    client, _ = _client()

    response = client.post(
        "/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        content=b"{",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_non_stream_workflow_failure_is_stable_and_redacted():
    client, _ = _client(workflow=FailingWorkflow())

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(),
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "message": "智能体工作流暂时不可用",
        "type": "server_error",
        "param": None,
        "code": "WORKFLOW_UNAVAILABLE",
    }
    assert "provider-secret-must-not-leak" not in response.text


def test_stream_workflow_failure_returns_http_error_before_sse_starts():
    client, _ = _client(workflow=FailingWorkflow())

    response = client.post(
        "/v1/chat/completions",
        headers=_auth(),
        json=_request(stream=True),
    )

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"] == {
        "message": "智能体工作流暂时不可用",
        "type": "server_error",
        "param": None,
        "code": "WORKFLOW_UNAVAILABLE",
    }
    assert "provider-secret-must-not-leak" not in response.text


def test_openwebui_stream_failure_finishes_status_and_returns_sse_error():
    client, _ = _client(workflow=FailingWorkflow())

    response = client.post(
        "/v1/chat/completions",
        headers={
            **_auth(),
            "X-OpenWebUI-Chat-Id": "chat-failing-stream",
        },
        json=_request(stream=True),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "text/event-stream"
    )
    payloads = _stream_payloads(response)
    statuses = [
        item["event"]["data"]
        for item in payloads
        if isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
    ]
    assert statuses == [
        {
            "description": "正在检索粮储知识库并核对依据",
            "done": False,
        },
        {
            "description": "本轮处理未完成，请稍后重试",
            "done": True,
        },
    ]
    assert payloads[-2]["error"]["code"] == "WORKFLOW_UNAVAILABLE"
    assert payloads[-1] == "[DONE]"
    assert "provider-secret-must-not-leak" not in response.text
