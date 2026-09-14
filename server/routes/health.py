"""Health routes: lightweight liveness and explicit dependency diagnostics."""

from fastapi import APIRouter

from server.services.health_service import diagnose_dependencies, liveness

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> dict:
    """检查 HTTP 服务存活状态。"""
    return liveness()


@router.post("/api/health/diagnostics")
async def diagnostics() -> dict:
    """执行用户主动发起的依赖诊断。"""
    return await diagnose_dependencies()
