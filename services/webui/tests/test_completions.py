def _signup(client, email="a@example.com"):
    return client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": email, "password": "secret-123",
    }).json()["token"]


def test_completion_streams_persists_and_restores(client):
    token = _signup(client)
    res = client.post("/api/chat/completions", headers={"Authorization": f"Bearer {token}"}, json={
        "model": "grain-storage-agent",
        "messages": [{"role": "user", "content": "低温储粮如何抑制害虫"}],
        "stream": True,
    })
    assert res.status_code == 200
    frames = [f for f in res.text.split("\n\n") if f.startswith("data: ")]
    assert '"type":"chat_id"' in frames[0]
    chat_id = __import__("json").loads(frames[0][6:])["event"]["data"]["chat_id"]

    detail = client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    history = detail.json()["chat"]["history"]
    assert history["currentId"] is not None
    current = history["messages"][history["currentId"]]
    assert current["role"] == "assistant"
    assert current["content"]  # stub 上游全文
    assert current["sources"]  # source 事件已落库
    user_msg = history["messages"][current["parentId"]]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "低温储粮如何抑制害虫"


def test_completion_upstream_failure_persists_nothing(client, failing_upstream):
    # conftest 提供 failing_upstream fixture：MockTransport 返回 502
    token = _signup(client)
    res = client.post("/api/chat/completions", headers={"Authorization": f"Bearer {token}"}, json={
        "model": "grain-storage-agent",
        "messages": [{"role": "user", "content": "会失败的问题"}],
        "stream": True,
    }, )
    assert res.status_code == 200  # SSE 外形保持，错误以事件表达
    assert '"error"' in res.text
    listing = client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token}"}).json()
    # 失败轮整轮不落库，新建的空 chat 一并撤销
    assert listing == []


def test_completion_multibyte_delta_split_across_chunks(client, split_chunk_upstream):
    # 回归：aiter_bytes 不保证字符边界，旁路缓冲必须增量解码，
    # 否则跨块的中文（'低' 被切成两块）落库成 U+FFFD 乱码
    token = _signup(client)
    res = client.post("/api/chat/completions", headers={"Authorization": f"Bearer {token}"}, json={
        "model": "grain-storage-agent",
        "messages": [{"role": "user", "content": "跨块字符测试"}],
        "stream": True,
    })
    assert res.status_code == 200
    frames = [f for f in res.text.split("\n\n") if f.startswith("data: ")]
    chat_id = __import__("json").loads(frames[0][6:])["event"]["data"]["chat_id"]

    detail = client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token}"})
    history = detail.json()["chat"]["history"]
    current = history["messages"][history["currentId"]]
    assert "\ufffd" not in current["content"]  # 无替换字符残留
    assert current["content"] == "低温储粮"  # 跨块字符完整无损
