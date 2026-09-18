"""用独立应用验证生产静态托管，不导入主服务或打开真实数据库。"""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.responses import Response
from starlette.types import Scope


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """仅加载待测静态类，避免 server 包导入时初始化应用依赖。"""
    source_path = Path(__file__).parents[1] / "server" / "__init__.py"
    source = ast.parse(source_path.read_text(encoding="utf-8"))
    node = next(item for item in source.body
                if isinstance(item, ast.ClassDef) and item.name == "FrontendStaticFiles")
    namespace = {"StaticFiles": StaticFiles, "Response": Response, "Scope": Scope}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source_path), "exec"), namespace)

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>campus-app</html>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("/* campus asset */", encoding="utf-8")
    (tmp_path / "private.txt").write_text("outside-static-root", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/probe")
    async def probe() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/", namespace["FrontendStaticFiles"](directory=dist, html=True))
    return TestClient(app)


@pytest.mark.parametrize("page", ["today", "chat", "personal-data", "schedule", "news", "sync", "backup"])
@pytest.mark.parametrize("suffix", ["", "/"])
def test_refresh_known_pages(client: TestClient, page: str, suffix: str) -> None:
    response = client.get(f"/{page}{suffix}?from=bookmark")
    assert response.status_code == 200
    assert response.text == "<html>campus-app</html>"
    assert response.headers["content-type"].startswith("text/html")


def test_static_files_api_and_head_keep_their_behavior(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/assets/app.js").text == "/* campus asset */"
    assert client.get("/api/probe").json() == {"ok": True}
    response = client.head("/schedule")
    assert response.status_code == 200
    assert response.content == b""
    assert client.post("/schedule").status_code == 405


@pytest.mark.parametrize("path", [
    "/assets/missing.js", "/api/missing", "/unknown", "/schedule/details",
    "/%2e%2e/private.txt", "/assets/%2e%2e/%2e%2e/private.txt",
    "/assets/%2e%2e/schedule", "/..%5cprivate.txt", "/%252e%252e/private.txt",
])
def test_missing_and_traversal_paths_do_not_receive_app(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert "campus-app" not in response.text
    assert "outside-static-root" not in response.text
