"""Minimal settings for the extracted webui service (replaces open_webui.env)."""

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/webui.db")
WEBUI_SECRET_KEY = os.environ.get("WEBUI_SECRET_KEY", "")
WEBUI_AUTH = os.environ.get("WEBUI_AUTH", "true").strip().lower() != "false"
JWT_EXPIRES_IN = os.environ.get("JWT_EXPIRES_IN", "4w")
PASSWORD_HASH_ALGORITHM = os.environ.get("PASSWORD_HASH_ALGORITHM", "bcrypt").lower()

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

# Auth cookie behavior (reference: open_webui.env).
WEBUI_AUTH_COOKIE_SAME_SITE = os.environ.get("WEBUI_AUTH_COOKIE_SAME_SITE", "lax")
WEBUI_AUTH_COOKIE_SECURE = (
    os.environ.get("WEBUI_AUTH_COOKIE_SECURE", "false").strip().lower() == "true"
)
WEBUI_AUTH_SIGNOUT_REDIRECT_URL = os.environ.get("WEBUI_AUTH_SIGNOUT_REDIRECT_URL", None)

# Password policy knobs (verbatim from open_webui.env); consumed by
# webui.utils.validate.validate_password.
ENABLE_PASSWORD_VALIDATION = os.environ.get("ENABLE_PASSWORD_VALIDATION", "False").lower() == "true"
PASSWORD_VALIDATION_REGEX_PATTERN = os.environ.get(
    "PASSWORD_VALIDATION_REGEX_PATTERN",
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$",
)

try:
    PASSWORD_VALIDATION_REGEX_PATTERN = rf"{PASSWORD_VALIDATION_REGEX_PATTERN}"
    PASSWORD_VALIDATION_REGEX_PATTERN = re.compile(PASSWORD_VALIDATION_REGEX_PATTERN)
except Exception as e:
    log.error(f"Invalid PASSWORD_VALIDATION_REGEX_PATTERN: {e}")
    PASSWORD_VALIDATION_REGEX_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$")

PASSWORD_VALIDATION_HINT = os.environ.get("PASSWORD_VALIDATION_HINT", "")


def validate_startup() -> None:
    if WEBUI_AUTH and not WEBUI_SECRET_KEY:
        raise RuntimeError(
            "WEBUI_SECRET_KEY must be set when WEBUI_AUTH is enabled"
        )
