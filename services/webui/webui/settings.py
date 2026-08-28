"""Minimal settings for the extracted webui service (replaces open_webui.env)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/webui.db")
WEBUI_SECRET_KEY = os.environ.get("WEBUI_SECRET_KEY", "")
WEBUI_AUTH = os.environ.get("WEBUI_AUTH", "true").strip().lower() != "false"
JWT_EXPIRES_IN = os.environ.get("JWT_EXPIRES_IN", "4w")

APP_UPSTREAM_BASE_URL = os.environ.get(
    "APP_UPSTREAM_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")
OPENAI_COMPAT_API_KEY = os.environ.get("OPENAI_COMPAT_API_KEY", "")

FRONTEND_BUILD_DIR = os.environ.get(
    "FRONTEND_BUILD_DIR",
    str(BASE_DIR.parent.parent / "frontend" / "webui" / "build"),
)
CORS_ALLOW_ORIGIN = os.environ.get("CORS_ALLOW_ORIGIN", "*")

ENABLE_ADMIN_CHAT_ACCESS = (
    os.environ.get("ENABLE_ADMIN_CHAT_ACCESS", "false").strip().lower() == "true"
)


def validate_startup() -> None:
    if WEBUI_AUTH and not WEBUI_SECRET_KEY:
        raise RuntimeError(
            "WEBUI_SECRET_KEY must be set when WEBUI_AUTH is enabled"
        )
