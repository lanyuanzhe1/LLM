def _signup(client, email, name="甲"):
    res = client.post("/api/v1/auths/signup", json={
        "name": name, "email": email, "password": "secret-123",
    })
    return res.json()["token"]


def _new_chat(client, token):
    import uuid
    chat_id = str(uuid.uuid4())
    res = client.post(
        "/api/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "grain-storage-agent",
            "chat_id": chat_id,
            "messages": [{"role": "user", "content": "低温储粮如何抑虫"}],
            "stream": True,
        },
    )
    assert res.status_code == 200, res.text
    return chat_id


def test_chat_list_detail_delete_and_isolation(client):
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com", name="乙")

    # 用 stub 上游产生一个会话（上游 stub 在 conftest 中装配，见 Task 12）
    chat_id = _new_chat(client, token_a)

    listing = client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token_a}"})
    assert listing.status_code == 200
    assert any(item["id"] == chat_id for item in listing.json())

    detail = client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert detail.status_code == 200

    # 非属主 → 404（偏离参考 401）
    assert client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404
    assert client.delete(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404

    assert client.delete(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_a}"}).status_code == 200
    assert client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token_a}"}).json() == []

    # 未登录（TestClient 持久化了 signup 设置的 HttpOnly token cookie，
    # 先清空 jar 才是真正意义上的未登录，同 test_auth.py 先例）
    client.cookies.clear()
    assert client.get("/api/v1/chats/").status_code == 401
