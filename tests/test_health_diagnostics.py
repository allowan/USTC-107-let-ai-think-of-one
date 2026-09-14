"""健康检查回归仅使用 mock，不访问模型或真实数据库。"""

import asyncio
from threading import Event
from unittest.mock import Mock, patch

from pytest import LogCaptureFixture
from fastapi import FastAPI
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv"):
    from server.routes.health import router
    from server.services import health_service


def test_liveness_does_not_probe_dependencies() -> None:
    app = FastAPI()
    app.include_router(router)
    with patch.object(health_service, "_ping_llm") as llm, patch.object(health_service, "_ping_chroma") as chroma:
        response = TestClient(app).get("/api/health")
    assert response.json() == {"status": "ok", "checks": {"service": True}}
    llm.assert_not_called()
    chroma.assert_not_called()


def test_explicit_diagnostics_reports_failure_without_secret(caplog: LogCaptureFixture) -> None:
    app = FastAPI()
    app.include_router(router)
    with patch.object(health_service, "_ping_llm", side_effect=RuntimeError("secret-token")), patch.object(health_service, "_ping_chroma"):
        response = TestClient(app).post("/api/health/diagnostics")
    assert response.json() == {"status": "degraded", "checks": {"llm": False, "chromadb": True}}
    assert "secret-token" not in response.text
    assert "secret-token" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_timeout_reuses_actual_worker_across_requests_and_loops() -> None:
    release = Event()
    started = Event()

    def blocked() -> None:
        started.set()
        assert release.wait(3)

    llm = Mock(side_effect=blocked)
    try:
        with patch.object(health_service, "DIAGNOSTIC_TIMEOUT", 0.02), patch.object(health_service, "_ping_llm", llm), patch.object(health_service, "_ping_chroma"):
            first = asyncio.run(health_service.diagnose_dependencies())
            second = asyncio.run(health_service.diagnose_dependencies())
            assert started.is_set()
            assert first["checks"]["llm"] is False
            assert second["checks"]["llm"] is False
            assert llm.call_count == 1
    finally:
        release.set()
        health_service._pending["llm"].result(timeout=3)


def test_diagnostics_succeeds_and_retries_completed_probes() -> None:
    with patch.object(health_service, "_ping_llm") as llm, patch.object(health_service, "_ping_chroma"):
        assert asyncio.run(health_service.diagnose_dependencies()) == {
            "status": "ok", "checks": {"llm": True, "chromadb": True}
        }
        assert asyncio.run(health_service.diagnose_dependencies())["status"] == "ok"
    assert llm.call_count == 2


def test_concurrent_requests_share_both_inflight_probes() -> None:
    release = Event()
    started = Event()
    calls = Mock()

    def blocked() -> None:
        calls()
        started.set()
        assert release.wait(3)

    async def run_requests() -> None:
        first = asyncio.create_task(health_service.diagnose_dependencies())
        while not started.is_set():
            await asyncio.sleep(0.001)
        second = asyncio.create_task(health_service.diagnose_dependencies())
        await asyncio.sleep(0.02)
        release.set()
        results = await asyncio.gather(first, second)
        assert all(result["status"] == "ok" for result in results)

    try:
        with patch.object(health_service, "_ping_llm", blocked), patch.object(health_service, "_ping_chroma", blocked):
            asyncio.run(run_requests())
    finally:
        release.set()
    assert calls.call_count == 2
