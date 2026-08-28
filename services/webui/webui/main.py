"""Minimal FastAPI app factory for the extracted webui service.

Task 9 lands only what the auth E2E flow needs: lifespan (startup validation,
table creation, idempotent Config seeding) + the auths router + CORS.
Task 11 extends this with version/config/models endpoints and static hosting.
Task 10 mounts the chats router (list/detail/delete); Task 12 adds the slim
/api/chat/completions orchestrator.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from webui.internal.db import create_all_tables
from webui.models.config import Config
from webui.routers import auths, chats
from webui.settings import (
    CORS_ALLOW_ORIGIN,
    FRONTEND_BUILD_DIR,
    JWT_EXPIRES_IN,
    validate_startup,
)
from webui.utils import upstream
from webui.utils.auth import get_verified_user

APP_VERSION = '0.1.0'
APP_NAME = '粮储智研助手'

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
    app.include_router(chats.router, prefix='/api/v1/chats', tags=['chats'])

    @app.get('/api/version')
    async def version():
        return {'version': APP_VERSION}

    @app.get('/api/config')
    async def config():
        return {'status': True, 'name': APP_NAME, 'version': APP_VERSION}

    @app.get('/api/models')
    async def models(user=Depends(get_verified_user)):
        response = await upstream.get_json('/v1/models')
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get('content-type', 'application/json'),
        )

    # SPA static hosting; skipped when the build dir is absent (dev: vite serves).
    frontend_build_dir = Path(FRONTEND_BUILD_DIR)
    if frontend_build_dir.is_dir():
        app.mount(
            '/', StaticFiles(directory=frontend_build_dir, html=True), name='spa'
        )

    return app
