import httpx

from webui.utils import upstream


def test_version_and_config(client):
    assert client.get("/api/version").json()["version"] == "0.1.0"
    config = client.get("/api/config")
    assert config.status_code == 200 and config.json()["status"] is True


def test_models_requires_login(client):
    assert client.get("/api/models").status_code == 401


def test_models_proxy_passthrough(client, monkeypatch):
    client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": "a@example.com", "password": "secret-123",
    })
    signin = client.post("/api/v1/auths/signin", json={
        "email": "a@example.com", "password": "secret-123",
    })
    token = signin.json()["token"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        # 服务密钥头由 upstream.service_headers 注入（conftest 设为 test-compat-key）
        assert request.headers["authorization"] == "Bearer test-compat-key"
        return httpx.Response(200, json={"data": [{"id": "grain-model"}]})

    monkeypatch.setattr(
        upstream,
        "build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://testserver"
        ),
    )

    r = client.get("/api/models", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"data": [{"id": "grain-model"}]}
