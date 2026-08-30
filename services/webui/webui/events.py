"""No-op event stub replacing open_webui.events (audit/webhook 不取）。"""


class EVENTS:
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_SIGNUP = "auth.signup"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"
    USER_CREATED = "user.created"


async def publish_event(*args, **kwargs) -> None:
    return None
