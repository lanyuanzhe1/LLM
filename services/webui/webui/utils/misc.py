"""Minimal misc helpers referenced by the extracted models.

Verbatim from open_webui.utils.misc, except:
- ``JSONCodec.dumps`` is replaced with stdlib ``json.dumps`` (the extracted
  service has no orjson toggle).
- ``SURROGATE_RE`` is built via chr(0xD800)/chr(0xDFFF) instead of raw
  surrogate source literals; the compiled pattern is identical.
"""

from __future__ import annotations

import json
import re

SURROGATE_RE = re.compile('[' + chr(0xD800) + '-' + chr(0xDFFF) + ']')


def sanitize_text_for_db(text: str) -> str:
    """Remove null bytes and invalid UTF-8 surrogates from text for PostgreSQL storage."""
    if not isinstance(text, str):
        return text
    # Fast path: skip work when there are no null bytes or surrogate code points.
    if '\x00' not in text and not SURROGATE_RE.search(text):
        return text
    return SURROGATE_RE.sub('', text.replace('\x00', ''))


def _strip_null_bytes_deep(obj):
    """Inner recursive walk — only called when null bytes are known to be present."""
    if isinstance(obj, str):
        return sanitize_text_for_db(obj)
    elif isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            cleaned[sanitize_text_for_db(k) if isinstance(k, str) else k] = _strip_null_bytes_deep(v)
        return cleaned
    elif isinstance(obj, list):
        return [_strip_null_bytes_deep(v) for v in obj]
    return obj


def sanitize_data_for_db(obj):
    """Recursively sanitize all strings in a data structure for database storage.

    Performs a fast pre-check: serializes the structure once and scans for
    null bytes or invalid UTF-8 surrogates. If none are found, the
    original object is returned immediately, skipping the expensive
    recursive walk.
    """
    if isinstance(obj, str):
        return sanitize_text_for_db(obj)
    # Fast path: check for null bytes and surrogate code points in the serialized form.
    # json.dumps is implemented in C and much faster than a Python-level
    # recursive walk over every leaf string.
    try:
        serialized = json.dumps(obj, ensure_ascii=False)
        if '\\u0000' not in serialized:
            serialized.encode('utf-8')
            return obj
    except (TypeError, ValueError, UnicodeEncodeError):
        pass
    return _strip_null_bytes_deep(obj)
