import json
from pathlib import Path

from app.schemas.tools import (
    CaseEvaluateRequest,
    CaseEvaluateResponse,
    CitationValidateRequest,
    CitationValidateResponse,
    GenerateRequest,
    GenerateResponse,
    RetrieveRequest,
    RetrieveResponse,
)
from app.services.citation_validation import (
    SOURCE_BIBLIOGRAPHY_INSTRUCTION,
    SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION,
)


CONTRACT_PATH = Path("workflow/tool_contracts.json")


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_workflow_contract_has_exact_inputs_authentication_and_tools():
    contract = _contract()

    assert contract["name"] == "粮储智研助手技术实体_v1"
    assert contract["start_parameters"] == [
        "AGENT_USER_INPUT",
        "REQUEST_ID",
        "SESSION_ID",
        "USER_ROLE",
        "TASK_TYPE",
        "CASE_JSON",
        "PROJECT_ID",
    ]
    assert contract["authentication"] == {
        "header": "Authorization",
        "value": "Bearer ${TOOLS_SERVICE_TOKEN}",
    }
    assert [
        (tool["name"], tool["method"], tool["path"])
        for tool in contract["tools"]
    ] == [
        ("grain_retrieve", "POST", "/tools/v1/retrieve"),
        ("grain_generate", "POST", "/tools/v1/generate"),
        ("grain_case_evaluate", "POST", "/tools/v1/cases/evaluate"),
        (
            "grain_citation_validate",
            "POST",
            "/tools/v1/citations/validate",
        ),
    ]


def test_workflow_contract_fields_exactly_match_service_schemas():
    contract = _contract()
    expected_models = [
        (RetrieveRequest, RetrieveResponse),
        (GenerateRequest, GenerateResponse),
        (CaseEvaluateRequest, CaseEvaluateResponse),
        (CitationValidateRequest, CitationValidateResponse),
    ]

    for tool, (request_model, response_model) in zip(
        contract["tools"], expected_models, strict=True
    ):
        assert tool["request_fields"] == list(request_model.model_fields)
        assert tool["response_fields"] == list(response_model.model_fields)
        assert tool["request_schema"] == json.loads(
            json.dumps(request_model.model_json_schema())
        )
        assert tool["response_schema"] == json.loads(
            json.dumps(response_model.model_json_schema())
        )
        assert set(tool) == {
            "name",
            "method",
            "path",
            "request_fields",
            "response_fields",
            "request_schema",
            "response_schema",
        }


def test_workflow_guide_documents_retry_citations_auth_and_environment_config():
    guide = Path("workflow/README.md").read_text(encoding="utf-8")

    for parameter in _contract()["start_parameters"]:
        assert f"`{parameter}`" in guide
    for tool in _contract()["tools"]:
        assert f"`{tool['name']}`" in guide
    assert "只重试一次" in guide
    assert "第二次验证仍失败" in guide
    assert "Authorization: Bearer ${TOOLS_SERVICE_TOKEN}" in guide
    assert "不在工作流提示词或固定变量中保存任何讯飞 API 密钥" in guide
    assert "quality.sufficient == false" in guide
    assert SOURCE_BIBLIOGRAPHY_INSTRUCTION in guide
    assert SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION in guide


def test_workflow_assets_document_exact_schema_mapping_and_operator_quick_start():
    workflow_guide = Path("workflow/README.md").read_text(encoding="utf-8")
    operator_guide = Path("docs/星辰工作流联调指南.md").read_text(
        encoding="utf-8"
    )
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "`coverage`" in workflow_guide
    assert "嵌套对象" in workflow_guide
    assert "尚未发布" in workflow_guide
    assert "Flow export" in workflow_guide

    for text in (operator_guide,):
        for required in [
            "conda activate LLM",
            "python -m pip install -r requirements-dev.txt",
            ".env.example",
            "python -m pytest -m \"not online\" -q",
            "SKIP_VECTOR_SEARCH=1 python build_vector_store.py",
            "python -m uvicorn app.main:app",
            "--workers 1",
            "GET /health",
            "GET /ready",
            "503",
            "PowerShell",
            "Copy-Item .env.example .env",
            "$env:SKIP_VECTOR_SEARCH = \"1\"",
            "python -m pytest -m 'not online' -q",
            "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1",
        ]:
            assert required in text
    assert "conda activate LLM" in readme
    assert "python -m uvicorn" in readme
    assert "只适用于该 macOS" in readme
    assert "向量" in operator_guide
    assert "静态云配置" in operator_guide


def test_operator_online_verification_commands_are_scoped_to_each_shell():
    guide = Path("docs/星辰工作流联调指南.md").read_text(encoding="utf-8")
    posix = guide.split("## 1. macOS/Linux：安装与配置", 1)[1].split(
        "## 3. Windows PowerShell：配置、验证、重建与启动", 1
    )[0]
    powershell = guide.split("## 3. Windows PowerShell：配置、验证、重建与启动", 1)[
        1
    ].split("## 4. 暴露工具接口", 1)[0]

    assert "source .env" in posix
    assert 'python -m pytest -m "not online" -q' in posix
    assert "python -m pytest tests/online -v" in posix
    assert "全部收集并跳过" in posix
    assert (
        "RUN_ONLINE=1 python -m pytest "
        "tests/online/test_cloud_services.py -v"
    ) in posix
    assert "终端 A" in posix
    assert "终端 B" in posix
    assert posix.index("终端 A") < posix.index("终端 B")
    assert (
        "python -m uvicorn app.main:app --host 127.0.0.1 "
        "--port 8000 --workers 1"
    ) in posix
    assert (
        "RUN_ONLINE=1 LOCAL_PUBLIC_API_URL=http://127.0.0.1:8000 "
        "python -m pytest tests/online/test_end_to_end.py -v"
    ) in posix
    assert posix.index("终端 A") < posix.index("终端 B") < posix.index(
        "RUN_ONLINE=1 LOCAL_PUBLIC_API_URL=http://127.0.0.1:8000"
    )
    assert "$env:RUN_ONLINE" not in posix

    assert "Copy-Item .env.example .env" in powershell
    assert "Get-Content .env" in powershell
    assert ".Split('=', 2)" in powershell
    assert (
        "[Environment]::SetEnvironmentVariable($name, $value, 'Process')"
        in powershell
    )
    assert "python -m pytest -m 'not online' -q" in powershell
    assert "python -m pytest tests/online -v" in powershell
    assert "全部收集并跳过" in powershell
    assert '$env:RUN_ONLINE = "1"' in powershell
    assert (
        "python -m pytest tests/online/test_cloud_services.py -v"
        in powershell
    )
    assert '$env:LOCAL_PUBLIC_API_URL = "http://127.0.0.1:8000"' in powershell
    assert "python -m pytest tests/online/test_end_to_end.py -v" in powershell
    assert "终端 A" in powershell
    assert "终端 B" in powershell
    assert powershell.index("终端 A") < powershell.index("终端 B")
    assert (
        "python -m uvicorn app.main:app --host 127.0.0.1 "
        "--port 8000 --workers 1"
    ) in powershell
    assert "Remove-Item Env:RUN_ONLINE -ErrorAction SilentlyContinue" in powershell
    assert (
        "Remove-Item Env:LOCAL_PUBLIC_API_URL -ErrorAction SilentlyContinue"
        in powershell
    )
    e2e_url = powershell.index(
        '$env:LOCAL_PUBLIC_API_URL = "http://127.0.0.1:8000"'
    )
    e2e_test = powershell.index(
        "python -m pytest tests/online/test_end_to_end.py -v"
    )
    cleanup_url = powershell.index(
        "Remove-Item Env:LOCAL_PUBLIC_API_URL -ErrorAction SilentlyContinue"
    )
    cleanup_online = powershell.rindex(
        "Remove-Item Env:RUN_ONLINE -ErrorAction SilentlyContinue"
    )
    assert powershell.index("终端 A") < powershell.index("终端 B") < e2e_url
    assert e2e_url < e2e_test < cleanup_url < cleanup_online
    assert "RUN_ONLINE=1 python" not in powershell


def test_operator_docs_define_anti_recursion_and_public_exposure_boundaries():
    for path in [
        Path("workflow/README.md"),
        Path("docs/星辰工作流联调指南.md"),
    ]:
        guide = path.read_text(encoding="utf-8")

        assert "`/v1/*` 调用星辰工作流" in guide
        assert "星辰只允许调用经过认证的 `/tools/v1/*`" in guide
        assert "`/tools/v1/*` 绝不调用星辰工作流" in guide
        assert "仅允许 `/tools/v1/*`" in guide
        for private_path in [
            "`/v1/*`",
            "`/health`",
            "`/ready`",
            "`/openapi.json`",
        ]:
            assert private_path in guide
        assert "文档和管理路径" in guide
        assert "除非另行授权" in guide
        assert "不是删除或停用应用路由" in guide
