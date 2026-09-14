"""轻量存活检查与用户主动依赖诊断。"""

import asyncio
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Callable

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent
DIAGNOSTIC_TIMEOUT = 10.0
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health-diagnostics")
_pending: dict[str, Future[bool]] = {}
_pending_lock = Lock()
_chroma_client = None


def liveness() -> dict:
    """返回 HTTP 服务存活状态，不初始化外部依赖。"""
    return {"status": "ok", "checks": {"service": True}}


def _ping_llm() -> None:
    from model.config import init_chat

    init_chat().invoke([{"role": "user", "content": "ping"}])


def _ping_chroma() -> None:
    import chromadb

    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=str(ROOT / "chroma_db"))
    _chroma_client.list_collections()


def _probe(name: str, operation: Callable[[], None]) -> bool:
    try:
        operation()
        return True
    except Exception as exc:
        # 诊断边界允许下一次主动重试；异常正文可能包含地址或凭据。
        logger.warning("Dependency diagnostic failed: %s (%s)", name, type(exc).__name__)
        return False


async def _check(name: str, operation: Callable[[], None]) -> bool:
    with _pending_lock:
        pending = _pending.get(name)
        if pending is None or pending.done():
            pending = _executor.submit(_probe, name, operation)
            _pending[name] = pending
    try:
        # 保存线程 Future 而非 asyncio Task，HTTP 取消或事件循环关闭也不会
        # 误判实际探测已结束；每个依赖最多有一个在途任务。
        return await asyncio.wait_for(
            asyncio.shield(asyncio.wrap_future(pending)), timeout=DIAGNOSTIC_TIMEOUT
        )
    except TimeoutError:
        logger.warning("Dependency diagnostic timed out: %s", name)
        return False


async def diagnose_dependencies() -> dict:
    """并行探测依赖，复用在途请求并返回不含底层错误的稳定结果。"""
    llm, chroma = await asyncio.gather(_check("llm", _ping_llm), _check("chromadb", _ping_chroma))
    checks = {"llm": llm, "chromadb": chroma}
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}
