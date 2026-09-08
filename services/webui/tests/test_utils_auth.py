from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_token_roundtrip_and_expiry():
    from webui.utils.auth import create_token, decode_token

    token = create_token(data={"id": "u1"})
    assert decode_token(token)["id"] == "u1"

    expired = create_token(data={"id": "u1"}, expires_delta=timedelta(seconds=-1))
    assert decode_token(expired) is None


async def test_password_hash_verify():
    from webui.utils.auth import get_password_hash, verify_password

    hashed = await get_password_hash("secret-123")
    assert await verify_password("secret-123", hashed)
    assert not await verify_password("wrong", hashed)


def test_parse_duration():
    from webui.utils.misc import parse_duration

    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("7d") == timedelta(days=7)
    assert parse_duration("4w") == timedelta(weeks=4)
    assert parse_duration("") is None


def test_role_gates():
    from webui.utils.auth import get_admin_user, get_verified_user

    user = SimpleNamespace(role="user")
    admin = SimpleNamespace(role="admin")
    pending = SimpleNamespace(role="pending")

    assert get_verified_user(user) is user
    assert get_verified_user(admin) is admin
    assert get_admin_user(admin) is admin
    with pytest.raises(HTTPException):
        get_verified_user(pending)
    with pytest.raises(HTTPException):
        get_admin_user(user)
