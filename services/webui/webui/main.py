"""Minimal FastAPI app factory for the extracted webui service.

Task 9 lands only what the auth E2E flow needs: lifespan (startup validation,
table creation, idempotent Config seeding) + the auths router + CORS.
Task 11 extends this with version/config/models endpoints and static hosting.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from webui.internal.db import create_all_tables
from webui.models.config import Config
from webui.routers import auths
from webui.settings import CORS_ALLOW_ORIGIN, JWT_EXPIRES_IN, validate_startup

# Seeded on startup; ``Config.seed_defaults`` only inserts missing keys, so
# existing DB values always win (idempotent across restarts and test wipes).
CONFIG_SEED_DEFAULTS = {
    'ui.default_user_role': 'user',
    'auth.jwt_expiry': JWT_EXPIRES_IN,
    'ui.enable_signup': True,
    'ui.enable_login_form': True,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup()

    # Import model modules so their tables register on Base.metadata first.
    import webui.models.auths  # noqa: F401
    import webui.models.chat_messages  # noqa: F401
    import webui.models.chats  # noqa: F401
    import webui.models.config  # noqa: F401
    import webui.models.users  # noqa: F401

    await create_all_tables()
    await Config.seed_defaults(CONFIG_SEED_DEFAULTS)
    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOW_ORIGIN.split(';'),
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )
    app.include_router(auths.router, prefix='/api/v1/auths', tags=['auths'])
    return app
