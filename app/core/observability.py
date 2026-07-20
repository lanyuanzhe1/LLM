import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


logger = logging.getLogger("grain_core.http")
_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


def _request_id(value: str | None) -> str:
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID")
        client_request_id = (
            supplied_request_id
            if supplied_request_id is not None
            and _REQUEST_ID.fullmatch(supplied_request_id)
            else None
        )
        request_id = _request_id(supplied_request_id)
        request.state.request_id = request_id
        request.state.client_request_id = client_request_id
        started = time.monotonic()
        status_code = 500
        completed = False

        def log_completion() -> None:
            nonlocal completed
            if completed:
                return
            completed = True
            logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "client_request_id": client_request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000,
                        2,
                    ),
                },
            )

        try:
            response = await call_next(request)
        except BaseException:
            log_completion()
            raise

        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        original_body_iterator = response.body_iterator

        async def body_iterator():
            try:
                async for chunk in original_body_iterator:
                    yield chunk
            finally:
                log_completion()

        response.body_iterator = body_iterator()
        return response
