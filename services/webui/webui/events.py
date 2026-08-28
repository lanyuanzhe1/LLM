"""No-op event stub replacing open_webui.events (audit/webhook 不取）。"""


class EVENTS:
    AUTH_LOGIN = "auth.login"
    AUTH_SIGNUP = "auth.signup"
    USER_CREATED = "user.created"


async def publish_event(*args, **kwargs) -> None:
    return None
