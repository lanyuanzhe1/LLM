"""Validation utilities for user-supplied input."""

import os
import re
from urllib.parse import urlparse

from webui.constants import ERROR_MESSAGES
from webui.settings import (
    ENABLE_PASSWORD_VALIDATION,
    PASSWORD_HASH_ALGORITHM,
    PASSWORD_VALIDATION_HINT,
    PASSWORD_VALIDATION_REGEX_PATTERN,
)

# Mirrors webui.utils.auth.PASSWORD_BCRYPT_MAX_BYTES; duplicated here because
# importing webui.utils.auth would create an import cycle
# (auth -> models.users -> utils.validate).
PASSWORD_BCRYPT_MAX_BYTES = 72

# Inlined from open_webui.env (kept local to keep webui/settings.py to its
# curated symbol list); same env-var names and defaults as the reference.
PROFILE_IMAGE_ALLOWED_MIME_TYPES = frozenset(
    t.strip()
    for t in os.getenv(
        'PROFILE_IMAGE_ALLOWED_MIME_TYPES',
        'image/png,image/jpeg,image/gif,image/webp',
    ).split(',')
    if t.strip()
)
_profile_image_max_data_uri_size = os.getenv('PROFILE_IMAGE_MAX_DATA_URI_SIZE', '').strip()
PROFILE_IMAGE_MAX_DATA_URI_SIZE = int(_profile_image_max_data_uri_size) if _profile_image_max_data_uri_size else None

_USER_PROFILE_IMAGE_RE = re.compile(r'^/api/v1/users/[^/?#]+/profile/image$')

# Data-URI prefix validator derived from PROFILE_IMAGE_ALLOWED_MIME_TYPES.
_mime_suffixes = '|'.join(re.escape(t.split('/')[-1]) for t in sorted(PROFILE_IMAGE_ALLOWED_MIME_TYPES))
_SAFE_DATA_URI_RE = re.compile(rf'^data:image/({_mime_suffixes});base64,', re.IGNORECASE)

# Exact relative paths accepted as profile images. These are the only
# static-asset paths OWUI itself assigns; no prefix/wildcard matching is
# used so that arbitrary relative paths cannot trigger authenticated GETs
# against internal endpoints when rendered as ``<img>`` sources.
# LICENSE covers the Open WebUI favicon fallback paths below. Do not alter,
# remove, obscure, or replace them except as LICENSE permits:
# https://docs.openwebui.com/license.
_SAFE_STATIC_PATHS = frozenset(
    {
        '/user.png',
        '/favicon.png',
        '/static/favicon.png',
    }
)


def validate_profile_image_url(url: str) -> str:
    """
    Pydantic-compatible validator for profile image URLs.

    Allowed formats:
    - Empty string (falls back to default avatar)
    - Known static-asset paths assigned by OWUI (exact match)
    - The OWUI profile-image API route ``/api/v1/users/{id}/profile/image``
    - ``http://`` and ``https://`` URLs with a valid hostname
    - ``data:image/{png,jpeg,gif,webp};base64,...`` URIs

    Everything else is rejected, including:
    - Dangerous schemes (javascript:, file:, ftp:, …)
    - SVG data URIs (can contain embedded scripts)
    - Arbitrary relative paths (prevents authenticated GET triggers)
    - Scheme-relative URLs (``//host/path``)
    - data URIs larger than PROFILE_IMAGE_MAX_DATA_URI_SIZE bytes
    """
    if not url:
        return url

    # --- Relative paths (exact match + anchored regex only) -----------

    if url in _SAFE_STATIC_PATHS:
        return url

    if _USER_PROFILE_IMAGE_RE.match(url):
        return url

    # --- Absolute URLs -------------------------------------------------

    # urlparse normalises the scheme to lowercase, giving us
    # case-insensitive scheme matching for free.
    parsed = urlparse(url)

    # External images served over HTTP(S), e.g. OAuth provider avatars.
    # Require a non-empty hostname (not just netloc, which can be ":80"
    # for a URL like http://:80/path with no actual host).
    if parsed.scheme in ('http', 'https'):
        if not parsed.hostname:
            raise ValueError('Invalid profile image URL: HTTP(S) URLs must include a host.')
        return url

    # Base64-encoded raster images uploaded via the frontend.
    # The regex enforces the ;base64, boundary and is case-insensitive
    # per the data-URI / MIME-type specs.
    if _SAFE_DATA_URI_RE.match(url):
        if PROFILE_IMAGE_MAX_DATA_URI_SIZE and len(url) > PROFILE_IMAGE_MAX_DATA_URI_SIZE:
            raise ValueError(
                f'Invalid profile image URL: data URI exceeds the {PROFILE_IMAGE_MAX_DATA_URI_SIZE}-byte limit.'
            )
        return url

    raise ValueError(
        'Invalid profile image URL: must be a known internal path, '
        'an HTTP(S) URL with a host, or a data:image URI (png/jpeg/gif/webp).'
    )


def validate_email_format(email: str) -> bool:
    if email.endswith('@localhost'):
        return True

    return bool(re.match(r'[^@]+@[^@]+\.[^@]+', email))


def validate_password(password: str) -> bool:
    # bcrypt only accepts 72 bytes; reject long new passwords instead of storing an unusable hash.
    if PASSWORD_HASH_ALGORITHM == 'bcrypt' and len(password.encode('utf-8')) > PASSWORD_BCRYPT_MAX_BYTES:
        raise Exception(
            ERROR_MESSAGES.PASSWORD_TOO_LONG,
        )

    if ENABLE_PASSWORD_VALIDATION:
        if not PASSWORD_VALIDATION_REGEX_PATTERN.match(password):
            raise Exception(ERROR_MESSAGES.INVALID_PASSWORD(PASSWORD_VALIDATION_HINT))

    return True
