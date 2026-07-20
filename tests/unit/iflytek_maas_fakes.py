class FakeConnection:
    def __init__(self, frames: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self.frames = iter(
            frames
            or [
                (
                    '{"header":{"code":0,"status":2},'
                    '"payload":{"choices":{"status":2,"text":[]}}}'
                )
            ]
        )
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        return next(self.frames)

    async def close(self) -> None:
        self.closed = True


class FakeConnectContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, *exc_info) -> None:
        await self.connection.close()


def terminal_frame() -> dict:
    return {
        "header": {"code": 0, "message": "Success", "status": 2},
        "payload": {
            "choices": {
                "status": 2,
                "text": [{"content": "done"}],
            }
        },
    }
