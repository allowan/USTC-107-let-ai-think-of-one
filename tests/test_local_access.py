"""本地访问边界回归，探针端点不读取真实配置或资料。"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv"):
    from server import create_app


@pytest.mark.parametrize("origin", ["https://outside.example", "http://localhost.evil.test", "http://127.0.0.1.evil.test", "null", "http://localhost@outside.example", "http://localhost:99999"])
def test_foreign_origin_cannot_read_or_mutate(origin: str) -> None:
    app = create_app()
    calls = []

    @app.api_route("/api/audit-probe", methods=["GET", "POST"])
    async def probe() -> dict:
        calls.append(True)
        return {"private": "fictional"}

    # create_app 的静态挂载位于末尾，新探针需要排在它之前。
    app.router.routes.insert(0, app.router.routes.pop())
    client = TestClient(app, base_url="http://localhost")
    for method in ("GET", "POST"):
        response = client.request(method, "/api/audit-probe", headers={"Origin": origin})
        assert response.status_code == 403
        assert "fictional" not in response.text
    assert calls == []


@pytest.mark.parametrize("host", ["outside.example", "localhost.evil.test", "127.0.0.1.evil.test"])
def test_untrusted_host_is_rejected(host: str) -> None:
    client = TestClient(create_app(), base_url="http://localhost")
    assert client.get("/api/docs", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
@pytest.mark.parametrize("origin", [None, "http://localhost:3000", "http://127.0.0.1:3000", "http://[::1]:3000"])
def test_local_pages_and_cli_remain_available(host: str, origin: str | None) -> None:
    client = TestClient(create_app(), base_url="http://localhost")
    headers = {"Host": host}
    if origin:
        headers["Origin"] = origin
    assert client.get("/api/docs", headers=headers).status_code == 200


def test_cors_preflight_only_allows_local_pages() -> None:
    client = TestClient(create_app(), base_url="http://localhost")
    for origin, expected in [("http://localhost:3000", 200), ("https://outside.example", 403)]:
        response = client.options("/api/topics", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert response.status_code == expected
        assert response.headers.get("access-control-allow-origin") == (origin if expected == 200 else None)
