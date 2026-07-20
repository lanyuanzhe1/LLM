from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


REQUIRED_ENV = {
    "XF_APP_ID": "app-id",
    "XF_EMBEDDING_API_KEY": "embedding-key",
    "XF_EMBEDDING_API_SECRET": "embedding-secret",
    "XF_MAAS_API_KEY": "maas-key",
    "XF_MAAS_API_SECRET": "maas-secret",
    "XF_MAAS_RESOURCE_ID": "resource-id",
    "XF_MAAS_SERVICE_ID": "service-id",
    "XF_WORKFLOW_API_KEY": "workflow-key",
    "XF_WORKFLOW_API_SECRET": "workflow-secret",
    "XF_WORKFLOW_FLOW_ID": "flow-id",
    "TOOLS_SERVICE_TOKEN": "tool-token",
}


def configured_settings(**overrides) -> Settings:
    values = {
        "xf_app_id": "app-id",
        "xf_embedding_api_key": "embedding-key",
        "xf_embedding_api_secret": "embedding-secret",
        "xf_maas_api_key": "maas-key",
        "xf_maas_api_secret": "maas-secret",
        "xf_maas_resource_id": "resource-id",
        "xf_maas_service_id": "service-id",
        "xf_workflow_api_key": "workflow-key",
        "xf_workflow_api_secret": "workflow-secret",
        "xf_workflow_flow_id": "flow-id",
        "tools_service_token": "tool-token",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_load_required_values(monkeypatch, tmp_path: Path):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path))

    settings = Settings(_env_file=None)

    assert settings.xf_app_id == "app-id"
    assert settings.vector_store_dir == tmp_path
    assert settings.retrieval_min_score == 0.35
    assert settings.workflow_url.endswith("/workflow/v1/chat/completions")
    assert settings.maas_max_frames == 1024
    assert settings.maas_max_payload_bytes == 2_097_152
    assert settings.maas_max_answer_chars == 32_000
    assert settings.workflow_max_frames == 1024
    assert settings.workflow_max_payload_bytes == 2_097_152
    assert settings.workflow_max_answer_chars == 32_000
    assert settings.gateway_max_buffer_chars == 32_000


def test_settings_reject_missing_secrets(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("token", ["令牌", "token with space", "token\nline"])
def test_settings_reject_non_bearer_compatible_tool_tokens(token):
    with pytest.raises(ValidationError):
        configured_settings(tools_service_token=token)


@pytest.mark.parametrize(
    "field",
    [
        "xf_app_id",
        "xf_maas_resource_id",
        "xf_maas_service_id",
        "xf_workflow_flow_id",
    ],
)
def test_settings_reject_blank_required_identifiers(field):
    with pytest.raises(ValidationError):
        configured_settings(**{field: " \t "})


@pytest.mark.parametrize(
    "field",
    [
        "xf_embedding_api_key",
        "xf_embedding_api_secret",
        "xf_maas_api_key",
        "xf_maas_api_secret",
        "xf_workflow_api_key",
        "xf_workflow_api_secret",
        "tools_service_token",
    ],
)
def test_settings_reject_blank_required_secrets_without_echoing_values(field):
    with pytest.raises(ValidationError) as exc_info:
        configured_settings(**{field: " \t "})

    assert "must not be blank" in str(exc_info.value)
    assert "tool-token" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_url", "http://embedding.invalid/"),
        ("workflow_url", "wss://workflow.invalid/v1/chat"),
        ("maas_url", "https://maas.invalid/v1/chat"),
        ("embedding_url", "https:///embedding"),
        ("maas_url", "wss://maas.invalid"),
        ("workflow_url", "https://workflow.invalid"),
    ],
)
def test_settings_reject_insecure_or_incomplete_service_urls(field, value):
    with pytest.raises(ValidationError):
        configured_settings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_url", "https://embedding.invalid /v1/embeddings"),
        ("embedding_url", "https://embedding.invalid/\nembeddings"),
        ("maas_url", "wss://maas.invalid/\tchat"),
        ("maas_url", "wss://maas\u200b.invalid/v1/chat"),
        (
            "workflow_url",
            "https://workflow.invalid/workflow/\ufeffv1/chat",
        ),
        ("workflow_url", "\u00a0https://workflow.invalid/workflow/v1/chat"),
    ],
)
def test_settings_reject_service_urls_with_raw_whitespace_or_controls(
    field, value
):
    with pytest.raises(ValidationError):
        configured_settings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "sentinel"),
    [
        (
            "embedding_url",
            "https://review-url-sentinel@embedding.invalid/v1",
            "review-url-sentinel",
        ),
        (
            "xf_app_id",
            {"review": "review-identifier-sentinel"},
            "review-identifier-sentinel",
        ),
        (
            "xf_embedding_api_key",
            {"review": "review-secret-sentinel"},
            "review-secret-sentinel",
        ),
    ],
)
def test_settings_validation_errors_redact_rejected_input_values(
    field, value, sentinel
):
    with pytest.raises(ValidationError) as exc_info:
        configured_settings(**{field: value})

    rendered = f"{exc_info.value!s}\n{exc_info.value!r}"
    assert sentinel not in rendered


@pytest.mark.parametrize("field", [
    "embedding_timeout_seconds",
    "maas_timeout_seconds",
    "workflow_timeout_seconds",
    "request_context_ttl_seconds",
])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_settings_reject_non_positive_or_non_finite_durations(field, value):
    with pytest.raises(ValidationError):
        configured_settings(**{field: value})


def test_settings_normalizes_supported_log_level_and_rejects_unknown_level():
    assert configured_settings(log_level=" debug ").log_level == "DEBUG"

    with pytest.raises(ValidationError):
        configured_settings(log_level="verbose")


@pytest.mark.parametrize(
    "field",
    [
        "maas_max_frames",
        "maas_max_payload_bytes",
        "maas_max_answer_chars",
        "workflow_max_frames",
        "workflow_max_payload_bytes",
        "workflow_max_answer_chars",
        "gateway_max_buffer_chars",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5, float("inf")])
def test_settings_reject_invalid_stream_budget_limits(field, value):
    with pytest.raises(ValidationError):
        configured_settings(**{field: value})


def test_settings_accepts_environment_style_integer_budget_strings():
    settings = configured_settings(
        maas_max_frames="7",
        workflow_max_payload_bytes="4096",
        gateway_max_buffer_chars="99",
    )

    assert settings.maas_max_frames == 7
    assert settings.workflow_max_payload_bytes == 4096
    assert settings.gateway_max_buffer_chars == 99
