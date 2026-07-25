"""
Entry point: python server/main.py  or  python -m server.main
"""

import signal
import logging
import uvicorn

logger = logging.getLogger("server.main")

if __name__ == "__main__":
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
