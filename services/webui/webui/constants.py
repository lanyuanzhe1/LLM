"""Constants extracted (trimmed) from open_webui.constants.

Only the ERROR_MESSAGES members referenced by the kept code are present,
verbatim from the reference. Add further members verbatim as later tasks
need them.
"""

from enum import Enum


class ERROR_MESSAGES(str, Enum):
    def __str__(self) -> str:
        return super().__str__()

    CREATE_USER_ERROR = 'Oops! Something went wrong while creating your account. Please try again later. If the issue persists, contact support for assistance.'
    EMAIL_TAKEN = 'Uh-oh! This email is already registered. Sign in with your existing account or choose another email to start anew.'
    PASSWORD_TOO_LONG = (
        'Uh-oh! The password you entered is too long. Please make sure your password is less than 72 bytes long.'
    )

    INVALID_TOKEN = 'Your session has expired or the token is invalid. Please sign in again.'
    INVALID_CRED = 'The email or password provided is incorrect. Please check for typos and try logging in again.'
    INVALID_EMAIL_FORMAT = "The email format you entered is invalid. Please double-check and make sure you're using a valid email address (e.g., yourname@example.com)."
    INCORRECT_PASSWORD = 'The password provided is incorrect. Please check for typos and try again.'

    EXISTING_USERS = "You can't turn off authentication because there are existing users. If you want to disable WEBUI_AUTH, make sure your web interface doesn't have any existing users and is a fresh installation."

    UNAUTHORIZED = '401 Unauthorized'
    ACCESS_PROHIBITED = (
        'You do not have permission to access this resource. Please contact your administrator for assistance.'
    )
    ACTION_PROHIBITED = 'The requested action has been restricted as a security measure.'

    # Callable members: assigned lambdas become plain class attributes (not
    # enum members), matching the reference's call syntax
    # ``ERROR_MESSAGES.INVALID_PASSWORD(hint)``.
    INVALID_PASSWORD = lambda err='': err if err else 'The password does not meet the required validation criteria.'
