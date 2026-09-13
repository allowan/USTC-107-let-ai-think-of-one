"""对抗性接口回归：使用业务替身，不访问用户数据库。"""
import asyncio
from unittest.mock import Mock, patch
from urllib.parse import quote

import pytest
import httpx
from fastapi import FastAPI

with patch("dotenv.load_dotenv"):
    from server.routes.personal_data import router
    from server.routes.digest import router as digest_router
    from server.services.rag_service import get_rag_service


@pytest.mark.parametrize("source", ["学习/网络安全", "https://example.test/a/b", "a%2Fb/笔记"])
def test_source_identifier_survives_path_decoding(source: str) -> None:
    app = FastAPI()
    app.include_router(router)
    app.include_router(digest_router)
    rag = Mock()
    rag.delete_user_data.return_value = 1
    app.dependency_overrides[get_rag_service] = lambda: rag
    path = "/api/personal-data/" + quote(source, safe="")

    async def exercise() -> None:
        # ASGITransport 与真实服务器一样只解码一次，规避旧 TestClient 的重复解码。
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
            response = await client.put(path, json={"content": "新内容"})
            assert response.status_code == 200
            rag.update_user_data.assert_called_once_with("local_user", source, "新内容")
            assert (await client.delete(path)).status_code == 200
            rag.delete_user_data.assert_called_once_with("local_user", source)
            with patch("campus_rag.untrack_event", return_value=True) as remove:
                assert (await client.delete("/api/digest/tracked/" + quote(source, safe=""))).status_code == 200
                remove.assert_called_once_with("local_user", source)

    asyncio.run(exercise())


@pytest.mark.parametrize("body", [
    {"source": "a" * 1025},
    {"source": "a", "date_value": "2026-9-1"},
    {"source": "a", "url": "javascript:alert(1)"},
    {"source": "a", "url": "https://user:pass@example.test/a"},
    {"source": "a", "title": ["not", "text"]},
])
def test_tracked_event_rejects_ambiguous_or_oversized_fields(body: dict) -> None:
    app = FastAPI()
    app.include_router(digest_router)

    async def exercise() -> None:
        with patch("campus_rag.track_event") as track:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost",
            ) as client:
                response = await client.post("/api/digest/tracked", json=body)
            assert response.status_code == 400
            track.assert_not_called()

    asyncio.run(exercise())


def test_digest_storage_failure_returns_retryable_error() -> None:
    from campus_rag import EventQueryError

    app = FastAPI()
    app.include_router(digest_router)
    rag = Mock()
    rag.get_digest.side_effect = EventQueryError("internal detail")
    app.dependency_overrides[get_rag_service] = lambda: rag

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost",
        ) as client:
            response = await client.get("/api/digest")
        assert response.status_code == 503
        assert "internal detail" not in response.text

    asyncio.run(exercise())
