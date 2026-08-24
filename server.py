"""
Compatibility shim: re-exports the FastAPI app from the server package.
Use "python server.py" or "python server/main.py" to start the server.
"""

import sys

try:
    from server import app  # noqa: F401
except ModuleNotFoundError as exc:
    # 直接用系统 Python 启动时依赖不在当前解释器里，裸 traceback 容易被误判为
    # 代码故障；给出可操作的修复指引后退出。
    print(
        f"[启动失败] 当前 Python 解释器缺少依赖: {exc.name}\n"
        f"解释器路径: {sys.executable}\n"
        "请先激活项目虚拟环境再启动：\n"
        "  .venv\\Scripts\\Activate.ps1\n"
        "  python server.py\n"
        "若虚拟环境未安装依赖：.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        "或直接用虚拟环境解释器启动：.venv\\Scripts\\python.exe server.py",
        file=sys.stderr,
    )
    sys.exit(1)

if __name__ == "__main__":
    import signal
    import logging
    import uvicorn

    logger = logging.getLogger("server")

    def _shutdown_uvicorn(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _shutdown_uvicorn)
    signal.signal(signal.SIGTERM, _shutdown_uvicorn)

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        timeout_graceful_shutdown=10,
    )
