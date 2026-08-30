"""Auth router extracted (trimmed) from open_webui.routers.auths.

Kept endpoints: ``GET /`` (session user), ``POST /signin``, ``POST /signup``,
``POST /signout``, ``POST /update/password`` — plus the shared helpers
``create_session_response`` / ``signup_handler`` and the session response
models.

Deleted vs. reference:
- ldap / oauth / api_key / admin-config / trusted-header endpoints and their
  imports (``ldap3``, ``aiohttp``, ``open_webui.config``, ``models.groups``,
  ``models.oauth_sessions``, ``utils.groups``, ``utils.rate_limit``,
  ``utils.redis``); the module-level ``RateLimiter`` instantiations and the
  signin rate-limit check.
- ``ENABLE_PASSWORD_AUTH`` gate on signin (lives in the un-extracted
  ``open_webui.config``).
- ``request.state.token`` fallback in ``get_session_user`` (no middleware in
  this service sets it) and the now-unused ``db`` dependency there.

Explicit deviations (task brief):
1. ``signup_handler`` no longer runs
   ``await Config.upsert({'ui.enable_signup': False})`` — signup stays open
   after the first (admin) user registers.
2. ``apply_default_group_assignment`` call and the ``ui.default_group_id``
   read are removed (groups are not extracted).
3. ``create_session_response`` / ``get_session_user`` drop the
   ``get_permissions(...)`` assembly: ``permissions`` is always ``{}`` and
   ``profile_image_url`` is always ``''``.

Also: the ``ENABLE_INITIAL_ADMIN_SIGNUP`` branch of ``signup`` is removed —
first-user registration is always allowed. Cookie behavior follows the
reference (HttpOnly ``token`` cookie + JSON token), with
``WEBUI_AUTH_COOKIE_SAME_SITE`` / ``WEBUI_AUTH_COOKIE_SECURE`` /
``WEBUI_AUTH_SIGNOUT_REDIRECT_URL`` coming from ``webui.settings``.
``publish_event`` is the no-op ``webui.events`` stub; ``revoke_user_tokens``
(Redis) is dropped from ``update_password``.
"""

from __future__ import annotations

import datetime
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from webui.constants import ERROR_MESSAGES
from webui.events import EVENTS, publish_event
from webui.internal.db import get_async_session
from webui.models.auths import (
    Auths,
    SigninForm,
    SignupForm,
    Token,
    UpdatePasswordForm,
)
from webui.models.config import Config
from webui.models.users import (
    UserModel,
    UserProfileImageResponse,
    Users,
    UserStatus,
)
from webui.settings import (
    WEBUI_AUTH,
    WEBUI_AUTH_COOKIE_SAME_SITE,
    WEBUI_AUTH_COOKIE_SECURE,
    WEBUI_AUTH_SIGNOUT_REDIRECT_URL,
)
from webui.utils.auth import (
    create_token,
    decode_token,
    get_current_user,
    get_http_authorization_cred,
    get_password_hash,
    verify_password,
)
from webui.utils.misc import parse_duration
from webui.utils.validate import validate_email_format, validate_password

router = APIRouter()

log = logging.getLogger(__name__)


async def create_session_response(
    request: Request,
    user,
    db,
    response: Response = None,
    set_cookie: bool = False,
    source: str = 'api',
) -> dict:
    """
    Create JWT token and build session response for a user.
    Shared helper for signin and signup endpoints.

    Args:
        request: FastAPI request object
        user: User object
        db: Database session
        response: FastAPI response object (required if set_cookie is True)
        set_cookie: Whether to set the auth cookie on the response
    """
    expires_delta = parse_duration(await Config.get('auth.jwt_expiry'))
    expires_at = None
    if expires_delta:
        expires_at = int(time.time()) + int(expires_delta.total_seconds())

    token = create_token(
        data={'id': user.id},
        expires_delta=expires_delta,
    )

    if set_cookie and response:
        datetime_expires_at = datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc) if expires_at else None
        max_age = int(expires_delta.total_seconds()) if expires_delta else None
        response.set_cookie(
            key='token',
            value=token,
            expires=datetime_expires_at,
            httponly=True,
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
            **({'max_age': max_age} if max_age is not None else {}),
        )

    await publish_event(
        request,
        EVENTS.AUTH_LOGIN,
        actor=user,
        subject_id=user.id,
        subject_type='user',
        source=source,
        data={'auth_method': source},
    )

    return {
        'token': token,
        'token_type': 'Bearer',
        'expires_at': expires_at,
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'role': user.role,
        'profile_image_url': '',
        'permissions': {},
    }


############################
# GetSessionUser
############################


class SessionUserResponse(Token, UserProfileImageResponse):
    expires_at: int | None = None
    permissions: dict | None = None


class SessionUserInfoResponse(SessionUserResponse, UserStatus):
    bio: str | None = None
    gender: str | None = None
    date_of_birth: datetime.date | None = None


@router.get('/', response_model=SessionUserInfoResponse)
async def get_session_user(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
):
    token = None
    auth_header = request.headers.get('Authorization')
    if auth_header:
        auth_token = get_http_authorization_cred(auth_header)
        if auth_token is not None:
            token = auth_token.credentials
    if token is None:
        token = request.cookies.get('token')
    data = decode_token(token) if token else None

    expires_at = None

    if data:
        expires_at = data.get('exp')

        if (expires_at is not None) and int(time.time()) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.INVALID_TOKEN,
            )

        # Set the cookie token
        max_age = int(expires_at - time.time()) if expires_at else None
        response.set_cookie(
            key='token',
            value=token,
            expires=(datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc) if expires_at else None),
            httponly=True,  # Ensures the cookie is not accessible via JavaScript
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
            **({'max_age': max_age} if max_age is not None else {}),
        )

    response_data = {
        'token': token,
        'token_type': 'Bearer',
        'expires_at': expires_at,
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'role': user.role,
        'profile_image_url': '',
        'bio': user.bio,
        'gender': user.gender,
        'date_of_birth': user.date_of_birth,
        'status_emoji': user.status_emoji,
        'status_message': user.status_message,
        'status_expires_at': user.status_expires_at,
        'permissions': {},
    }

    return response_data


############################
# Update Password
############################


@router.post('/update/password', response_model=bool)
async def update_password(
    request: Request,
    form_data: UpdatePasswordForm,
    session_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session),
):
    if session_user:
        user = await Auths.authenticate_user(
            session_user.email,
            lambda pw: verify_password(form_data.password, pw),
            db=db,
        )

        if user:
            try:
                validate_password(form_data.new_password)
            except Exception as e:
                raise HTTPException(400, detail=str(e))
            hashed = await get_password_hash(form_data.new_password)
            success = await Auths.update_user_password_by_id(user.id, hashed, db=db)
            if success:
                await publish_event(
                    request,
                    EVENTS.AUTH_PASSWORD_CHANGED,
                    actor=user,
                    subject_id=user.id,
                    subject_type='user',
                )
            return success
        else:
            raise HTTPException(400, detail=ERROR_MESSAGES.INCORRECT_PASSWORD)
    else:
        raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)


############################
# SignIn
############################


@router.post('/signin', response_model=SessionUserResponse)
async def signin(
    request: Request,
    response: Response,
    form_data: SigninForm,
    db: AsyncSession = Depends(get_async_session),
):
    auth_source = 'password'

    if WEBUI_AUTH == False:
        auth_source = 'system'
        admin_email = 'admin@localhost'
        admin_password = 'admin'

        if await Users.get_user_by_email(admin_email.lower(), db=db):
            user = await Auths.authenticate_user(
                admin_email.lower(),
                lambda pw: verify_password(admin_password, pw),
                db=db,
            )
        else:
            if await Users.has_users(db=db):
                raise HTTPException(400, detail=ERROR_MESSAGES.EXISTING_USERS)

            await signup_handler(
                request,
                admin_email,
                admin_password,
                'User',
                db=db,
                source='system',
            )

            user = await Auths.authenticate_user(
                admin_email.lower(),
                lambda pw: verify_password(admin_password, pw),
                db=db,
            )
    else:
        user = await Auths.authenticate_user(
            form_data.email.lower(),
            lambda pw: verify_password(form_data.password, pw),
            db=db,
        )

    if user:
        return await create_session_response(request, user, db, response, set_cookie=True, source=auth_source)
    else:
        raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)


############################
# SignUp
############################


async def signup_handler(
    request: Request,
    email: str,
    password: str,
    name: str,
    profile_image_url: str = '/user.png',
    *,
    db: AsyncSession,
    source: str = 'api',
) -> UserModel:
    """
    Core user-creation logic shared by the signup endpoint and
    trusted-header / no-auth auto-registration flows.

    Returns the newly created UserModel.
    Raises HTTPException on failure.
    """
    # Insert with default role first to avoid TOCTOU race on first signup.
    # If has_users() is checked before insert, concurrent requests during
    # first-user registration can all see an empty table and each get admin.
    hashed = await get_password_hash(password)

    user = await Auths.insert_new_auth(
        email=email.lower(),
        password=hashed,
        name=name,
        profile_image_url=profile_image_url,
        role=await Config.get('ui.default_user_role'),
        db=db,
    )
    if not user:
        raise HTTPException(500, detail=ERROR_MESSAGES.CREATE_USER_ERROR)

    # Atomically check if this is the only user *after* the insert.
    # Only the single user present at this point should become admin.
    if await Users.get_num_users(db=db) == 1:
        await Users.update_user_role_by_id(user.id, 'admin', db=db)
        user = await Users.get_user_by_id(user.id, db=db)

    await publish_event(
        request,
        EVENTS.USER_CREATED,
        actor=user,
        subject_id=user.id,
        source=source,
        data={'role': user.role},
    )

    return user


@router.post('/signup', response_model=SessionUserResponse)
async def signup(
    request: Request,
    response: Response,
    form_data: SignupForm,
    db: AsyncSession = Depends(get_async_session),
):
    has_users = await Users.has_users(db=db)

    if WEBUI_AUTH:
        if has_users:
            if not await Config.get('ui.enable_signup') or not await Config.get('ui.enable_login_form'):
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)
    else:
        if has_users:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    if not validate_email_format(form_data.email.lower()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.INVALID_EMAIL_FORMAT)

    if await Users.get_user_by_email(form_data.email.lower(), db=db):
        raise HTTPException(400, detail=ERROR_MESSAGES.EMAIL_TAKEN)

    try:
        try:
            validate_password(form_data.password)
        except Exception as e:
            raise HTTPException(400, detail=str(e))

        user = await signup_handler(
            request,
            form_data.email,
            form_data.password,
            form_data.name,
            form_data.profile_image_url,
            db=db,
        )
        await publish_event(
            request,
            EVENTS.AUTH_SIGNUP,
            actor=user,
            subject_id=user.id,
            subject_type='user',
            data={'email': user.email},
        )
        return await create_session_response(request, user, db, response, set_cookie=True)
    except HTTPException:
        raise
    except Exception as err:
        log.error(f'Signup error: {str(err)}')
        raise HTTPException(500, detail='An internal error occurred during signup.')


@router.post('/signout')
async def signout(request: Request, response: Response, db: AsyncSession = Depends(get_async_session)):
    # get auth token from headers or cookies
    token = None
    auth_header = request.headers.get('Authorization')
    if auth_header:
        auth_cred = get_http_authorization_cred(auth_header)
        if auth_cred is not None:
            token = auth_cred.credentials
    if token is None:
        token = request.cookies.get('token')

    if token:
        actor = None
        data = decode_token(token)
        if data and data.get('id'):
            actor = await Users.get_user_by_id(data['id'], db=db)
        await publish_event(
            request,
            EVENTS.AUTH_LOGOUT,
            actor=actor,
            subject_id=actor.id if actor else None,
            subject_type='user' if actor else None,
        )

    response.delete_cookie('token')
    try:
        request.session.clear()
    except Exception:
        pass
    response.delete_cookie('owui-session')
    response.delete_cookie('oui-session')
    response.delete_cookie('oauth_id_token')

    if WEBUI_AUTH_SIGNOUT_REDIRECT_URL:
        return JSONResponse(
            status_code=200,
            content={
                'status': True,
                'redirect_url': WEBUI_AUTH_SIGNOUT_REDIRECT_URL,
            },
            headers=response.headers,
        )

    return JSONResponse(status_code=200, content={'status': True}, headers=response.headers)
