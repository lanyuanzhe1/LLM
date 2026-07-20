from functools import lru_cache
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit
from unicodedata import category

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


IDENTIFIER_FIELDS = (
    "xf_app_id",
    "xf_maas_resource_id",
    "xf_maas_service_id",
    "xf_workflow_flow_id",
)
SECRET_FIELDS = (
    "xf_embedding_api_key",
    "xf_embedding_api_secret",
    "xf_maas_api_key",
    "xf_maas_api_secret",
    "xf_workflow_api_key",
    "xf_workflow_api_secret",
    "tools_service_token",
)
DURATION_FIELDS = (
    "embedding_timeout_seconds",
    "maas_timeout_seconds",
    "workflow_timeout_seconds",
    "request_context_ttl_seconds",
)
LIMIT_FIELDS = (
    "maas_max_frames",
    "maas_max_payload_bytes",
    "maas_max_answer_chars",
    "workflow_max_frames",
    "workflow_max_payload_bytes",
    "workflow_max_answer_chars",
    "gateway_max_buffer_chars",
)
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _non_blank_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _non_blank_secret(value: object) -> SecretStr | None:
    if not isinstance(value, SecretStr):
        return None
    try:
        raw_value = value.get_secret_value()
    except Exception:
        return None
    normalized = _non_blank_string(raw_value)
    return SecretStr(normalized) if normalized is not None else None


def _valid_tools_token(value: object) -> SecretStr | None:
    normalized = _non_blank_secret(value)
    if normalized is None:
        return None
    raw = normalized.get_secret_value()
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in raw):
        return None
    return normalized


def _valid_service_url(
    value: object,
    *,
    scheme: str,
    require_endpoint_path: bool,
) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if any(
        character.isspace() or category(character) in {"Cc", "Cf"}
        for character in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != scheme
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None and not 0 < port < 65536
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or require_endpoint_path and parsed.path == "/"
    ):
        return None
    return value


def _positive_finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if isfinite(normalized) and normalized > 0 else None


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _setting_value(settings: object, field: str) -> object:
    try:
        return getattr(settings, field)
    except Exception:
        return None


def cloud_configuration_issues(settings: object) -> tuple[str, ...]:
    """Return invalid cloud setting names without exposing their values."""
    issues: list[str] = []
    for field in IDENTIFIER_FIELDS:
        if _non_blank_string(_setting_value(settings, field)) is None:
            issues.append(field.upper())
    for field in SECRET_FIELDS:
        validator = (
            _valid_tools_token
            if field == "tools_service_token"
            else _non_blank_secret
        )
        if validator(_setting_value(settings, field)) is None:
            issues.append(field.upper())

    url_rules = (
        ("embedding_url", "https", False),
        ("maas_url", "wss", True),
        ("workflow_url", "https", True),
    )
    for field, scheme, require_endpoint_path in url_rules:
        if _valid_service_url(
            _setting_value(settings, field),
            scheme=scheme,
            require_endpoint_path=require_endpoint_path,
        ) is None:
            issues.append(field.upper())
    for field in DURATION_FIELDS:
        if _positive_finite_number(_setting_value(settings, field)) is None:
            issues.append(field.upper())
    for field in LIMIT_FIELDS:
        if _positive_integer(_setting_value(settings, field)) is None:
            issues.append(field.upper())
    log_level = _non_blank_string(_setting_value(settings, "log_level"))
    if log_level is None or log_level.upper() not in LOG_LEVELS:
        issues.append("LOG_LEVEL")
    return tuple(issues)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    xf_app_id: str
    xf_embedding_api_key: SecretStr
    xf_embedding_api_secret: SecretStr
    xf_maas_api_key: SecretStr
    xf_maas_api_secret: SecretStr
    xf_maas_resource_id: str
    xf_maas_service_id: str
    xf_workflow_api_key: SecretStr
    xf_workflow_api_secret: SecretStr
    xf_workflow_flow_id: str
    tools_service_token: SecretStr

    vector_store_dir: Path = Path("vector_store")
    retrieval_min_score: float = Field(default=0.35, ge=-1.0, le=1.0)
    log_level: str = "INFO"
    embedding_url: str = "https://emb-cn-huabei-1.xf-yun.com/"
    maas_url: str = "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat"
    workflow_url: str = (
        "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"
    )
    embedding_timeout_seconds: float = 30.0
    maas_timeout_seconds: float = 60.0
    workflow_timeout_seconds: float = 120.0
    request_context_ttl_seconds: float = 300.0
    maas_max_frames: int = Field(default=1024, gt=0)
    maas_max_payload_bytes: int = Field(default=2_097_152, gt=0)
    maas_max_answer_chars: int = Field(default=32_000, gt=0)
    workflow_max_frames: int = Field(default=1024, gt=0)
    workflow_max_payload_bytes: int = Field(default=2_097_152, gt=0)
    workflow_max_answer_chars: int = Field(default=32_000, gt=0)
    gateway_max_buffer_chars: int = Field(default=32_000, gt=0)

    @field_validator(*IDENTIFIER_FIELDS)
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = _non_blank_string(value)
        if normalized is None:
            raise ValueError("must not be blank")
        return normalized

    @field_validator(*SECRET_FIELDS)
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        normalized = _non_blank_secret(value)
        if normalized is None:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("tools_service_token")
    @classmethod
    def validate_tools_service_token(cls, value: SecretStr) -> SecretStr:
        normalized = _valid_tools_token(value)
        if normalized is None:
            raise ValueError("must be a visible ASCII bearer token")
        return normalized

    @field_validator("embedding_url")
    @classmethod
    def validate_embedding_url(cls, value: str) -> str:
        normalized = _valid_service_url(
            value,
            scheme="https",
            require_endpoint_path=False,
        )
        if normalized is None:
            raise ValueError("must be an HTTPS URL with a host and path")
        return normalized

    @field_validator("maas_url")
    @classmethod
    def validate_maas_url(cls, value: str) -> str:
        normalized = _valid_service_url(
            value,
            scheme="wss",
            require_endpoint_path=True,
        )
        if normalized is None:
            raise ValueError("must be a WSS endpoint URL with a host and path")
        return normalized

    @field_validator("workflow_url")
    @classmethod
    def validate_workflow_url(cls, value: str) -> str:
        normalized = _valid_service_url(
            value,
            scheme="https",
            require_endpoint_path=True,
        )
        if normalized is None:
            raise ValueError("must be an HTTPS endpoint URL with a host and path")
        return normalized

    @field_validator(*DURATION_FIELDS, mode="before")
    @classmethod
    def reject_boolean_duration(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("must be a positive finite number")
        return value

    @field_validator(*DURATION_FIELDS)
    @classmethod
    def validate_duration(cls, value: float) -> float:
        normalized = _positive_finite_number(value)
        if normalized is None:
            raise ValueError("must be a positive finite number")
        return normalized

    @field_validator(*LIMIT_FIELDS, mode="before")
    @classmethod
    def reject_non_integer_limit(cls, value: object) -> object:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("must be a positive integer")
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized.isascii() or not normalized.isdecimal():
                raise ValueError("must be a positive integer")
            return normalized
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = _non_blank_string(value)
        if normalized is None or normalized.upper() not in LOG_LEVELS:
            raise ValueError("must be a supported log level")
        return normalized.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
