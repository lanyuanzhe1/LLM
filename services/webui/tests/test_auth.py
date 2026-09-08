def test_signup_first_user_becomes_admin_and_signup_stays_open(client):
    first = client.post("/api/v1/auths/signup", json={
        "name": "管理员", "email": "admin@example.com", "password": "secret-123",
    })
    assert first.status_code == 200, first.text
    assert first.json()["role"] == "admin"
    assert first.json()["permissions"] == {}
    assert first.json()["profile_image_url"] == ""

    second = client.post("/api/v1/auths/signup", json={
        "name": "学生", "email": "u@example.com", "password": "secret-456",
    })
    assert second.status_code == 200, second.text
    assert second.json()["role"] == "user"  # 开放注册不自动关闭（偏离 1）


def test_signin_and_session_user(client):
    client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": "a@example.com", "password": "secret-123",
    })
    signin = client.post("/api/v1/auths/signin", json={
        "email": "a@example.com", "password": "secret-123",
    })
    assert signin.status_code == 200
    token = signin.json()["token"]

    session = client.get("/api/v1/auths/", headers={"Authorization": f"Bearer {token}"})
    assert session.status_code == 200
    assert session.json()["email"] == "a@example.com"

    # TestClient persists the HttpOnly `token` cookie set by signup/signin
    # (reference cookie behavior is kept: cookie + JSON token 双发). Clear the
    # jar so the final request is genuinely unauthenticated.
    client.cookies.clear()
    assert client.get("/api/v1/auths/").status_code == 401


def test_signin_wrong_password(client):
    client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": "a@example.com", "password": "secret-123",
    })
    bad = client.post("/api/v1/auths/signin", json={
        "email": "a@example.com", "password": "wrong",
    })
    assert bad.status_code in (400, 401)
