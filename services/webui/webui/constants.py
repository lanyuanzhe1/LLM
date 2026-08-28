"""Constants extracted (trimmed) from open_webui.constants.

Only the ERROR_MESSAGES members referenced by the kept code are present,
verbatim from the reference. Add further members verbatim as later tasks
need them.
"""

from enum import Enum


class ERROR_MESSAGES(str, Enum):
    def __str__(self) -> str:
        return super().__str__()

    INVALID_TOKEN = 'Your session has expired or the token is invalid. Please sign in again.'
    UNAUTHORIZED = '401 Unauthorized'
    ACCESS_PROHIBITED = (
        'You do not have permission to access this resource. Please contact your administrator for assistance.'
    )
