from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class ConfigurationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            "CONFIGURATION_ERROR", message, status_code=500, retryable=False
        )


class ProviderUnavailable(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=502, retryable=True)


class VectorStoreNotReady(AppError):
    def __init__(self, message: str = "向量库尚未就绪") -> None:
        super().__init__(
            "VECTOR_STORE_NOT_READY", message, status_code=503, retryable=True
        )
