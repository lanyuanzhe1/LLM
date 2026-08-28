"""Auth utils extracted (trimmed) from open_webui.utils.auth.

Kept (verbatim bodies unless noted): create_token / decode_token /
get_password_hash / verify_password / get_current_user (Bearer + cookie JWT
path only) / get_verified_user / get_admin_user.

Deleted vs. reference:
- API-key auth: get_current_user_by_api_key, the `sk-` branch and the
  request.state.token middleware fallback inside get_current_user.
- License machinery: verify_signature / override_static / get_license_data
  (AESGCM, ed25519, JSONCodec, requests outbound).
- WEBUI_AUTH_TRUSTED_EMAIL_HEADER branch and ENABLE_OTEL span blocks.
- Redis token revocation: is_valid_token / invalidate_token /
  revoke_user_tokens (this service has no Redis).
- Users.update_last_active_by_id fire-and-forget call (the method was not
  extracted with the Users model in Task 7).
- Helpers unused by the kept set: extract_token_from_auth_header,
  create_api_key, get_http_authorization_cred, get_verified_user_by_token,
  get_verified_user_by_id, get_optional_verified_user_from_request,
  create_admin_user, validate_password.

Imports retargeted: open_webui.env -> webui.settings,
open_webui.constants -> webui.constants, open_webui.models -> webui.models.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Union

import bcrypt
import jwt
from fastapi import BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pytz import UTC

from webui.constants import ERROR_MESSAGES
from webui.models.users import Users
from webui.settings import PASSWORD_HASH_ALGORITHM, WEBUI_SECRET_KEY

log = logging.getLogger(__name__)

SESSION_SECRET = WEBUI_SECRET_KEY
ALGORITHM = 'HS256'
PASSWORD_BCRYPT_MAX_BYTES = 72

##############
# Auth Utils
##############

bearer_security = HTTPBearer(auto_error=False)


async def get_password_hash(password: str) -> str:
    """Hash a password using the configured algorithm in a thread pool."""
    if PASSWORD_HASH_ALGORITHM == 'argon2':
        from argon2 import PasswordHasher

        return await asyncio.to_thread(PasswordHasher().hash, password)
    if PASSWORD_HASH_ALGORITHM == 'bcrypt':
        return (await asyncio.to_thread(bcrypt.hashpw, password.encode('utf-8'), bcrypt.gensalt())).decode('utf-8')

    raise ValueError(f'Unsupported PASSWORD_HASH_ALGORITHM: {PASSWORD_HASH_ALGORITHM}')


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password using the algorithm encoded in its hash."""
    if not hashed_password:
        return False

    if hashed_password.startswith('$argon2'):
        from argon2 import PasswordHasher
        from argon2.exceptions import InvalidHashError, VerificationError

        try:
            return await asyncio.to_thread(PasswordHasher().verify, hashed_password, plain_password)
        except (InvalidHashError, VerificationError):
            return False

    password_bytes = plain_password.encode('utf-8')[:PASSWORD_BCRYPT_MAX_BYTES]
    try:
        return await asyncio.to_thread(
            bcrypt.checkpw,
            password_bytes,
            hashed_password.encode('utf-8'),
        )
    except ValueError:
        return False


# Let the one who signed this token be remembered at every gate,
# and may the claims therein honor the creator long after
# the session has closed.
def create_token(data: dict, expires_delta: Union[timedelta, None] = None) -> str:
    payload = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
        payload.update({'exp': expire})

    jti = str(uuid.uuid4())
    payload.update({'jti': jti, 'iat': datetime.now(UTC)})

    encoded_jwt = jwt.encode(payload, SESSION_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict | None:
    try:
        decoded = jwt.decode(token, SESSION_SECRET, algorithms=[ALGORITHM])
        return decoded
    except Exception:
        return None


async def get_current_user(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    auth_token: HTTPAuthorizationCredentials = Depends(bearer_security),
    # NOTE: We intentionally do NOT use Depends(get_session) here.
    # Sessions are managed internally with short-lived context managers.
    # This ensures connections are released immediately after auth queries,
    # not held for the entire request duration (e.g., during 30+ second LLM calls).
):
    token = None

    if auth_token is not None:
        token = auth_token.credentials

    if token is None and 'token' in request.cookies:
        token = request.cookies.get('token')

    if token is None:
        raise HTTPException(status_code=401, detail='Not authenticated')

    # auth by jwt token
    try:
        try:
            data = decode_token(token)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid token',
            )

        if data is not None and 'id' in data:
            user = await Users.get_user_by_id(data['id'])
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=ERROR_MESSAGES.INVALID_TOKEN,
                )

            # Scope-backed, so outer middleware (audit) can reuse the resolved user
            request.state.user = user
            return user
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )
    except Exception as e:
        # Delete the token cookie
        if request.cookies.get('token'):
            response.delete_cookie('token')

        if request.cookies.get('oauth_id_token'):
            response.delete_cookie('oauth_id_token')

        # Delete OAuth session if present
        if request.cookies.get('oauth_session_id'):
            response.delete_cookie('oauth_session_id')

        raise e


VERIFIED_USER_ROLES = {'user', 'admin'}


def get_verified_user(user=Depends(get_current_user)):
    if user.role not in VERIFIED_USER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user


def get_admin_user(user=Depends(get_current_user)):
    if user.role != 'admin':
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return user
