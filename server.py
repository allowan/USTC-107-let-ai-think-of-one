"""
USTC AI Assistant - FastAPI Server
Bridges the existing RAG system, Agent, and file tools to the frontend.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException,
    UploadFile, File, Query, Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from jose import jwt, JWTError

# Ensure the project root is on sys.path so existing imports work
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from main import build_agent
from campus_rag import authenticate, register_user, search_notices, search_user_data
from campus_rag.auth import list_users, get_user_admin_status, delete_user as auth_delete_user
from campus_rag.index_manager import RAGSystem
from campus_rag.ingest import add_public_activity
from tools.file_tool import WorkspaceFiles, WorkspaceFileError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("JWT_SECRET", "ustc-campus-ai-secret-2026")
ALGORITHM = "HS256"
TOKEN_HOURS = 72
WORKSPACE_DIR = ROOT / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="USTC AI Assistant",
    version="0.1.0",
    docs_url="/api/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Shared state (initialized once at startup)
# ---------------------------------------------------------------------------
agent = None
file_workspace = WorkspaceFiles(str(WORKSPACE_DIR))


def get_agent():
    global agent
    if agent is None:
        agent = build_agent()
    return agent


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")


async def get_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return verify_token(credentials.credentials)


async def require_admin(user: str = Depends(get_user)) -> str:
    if not get_user_admin_status(user):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.exception_handler(WorkspaceFileError)
async def workspace_error_handler(_request: Request, exc: WorkspaceFileError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
async def login(body: dict):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    ok, is_admin = authenticate(username, password)
    if not ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    return {
        "token": create_token(username),
        "user_id": username,
        "username": username,
        "is_admin": is_admin,
    }


@app.post("/api/auth/register")
async def register(body: dict):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少需要 2 个字符")

    ok = register_user(username, password)
    if not ok:
        raise HTTPException(status_code=400, detail="用户名已存在")

    return {
        "token": create_token(username),
        "user_id": username,
        "username": username,
    }


# ---------------------------------------------------------------------------
# Chat WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/chat")
async def chat_websocket(ws: WebSocket, token: str = Query(...)):
    try:
        username = verify_token(token)
    except HTTPException:
        await ws.close(code=4001, reason="unauthorized")
        return

    await ws.accept()
    agent_instance = get_agent()
    thread_id = f"user-{username}"

    try:
        while True:
            data = await ws.receive_json()
            content = (data.get("content") or "").strip()
            if not content:
                continue

            try:
                from langchain_core.messages import AIMessageChunk
                async for msg_chunk, _metadata in agent_instance.astream(
                    {"messages": [{"role": "user", "content": content}]},
                    {"configurable": {"thread_id": thread_id}},
                    stream_mode="messages",
                ):
                    # 只流式输出最终回复，跳过工具调用和工具返回的中间消息
                    if isinstance(msg_chunk, AIMessageChunk) and msg_chunk.content:
                        if msg_chunk.tool_calls or msg_chunk.tool_call_chunks:
                            continue
                        await ws.send_json({"type": "token", "content": msg_chunk.content})
            except Exception as exc:
                await ws.send_json({"type": "error", "content": f"处理失败：{exc}"})

            await ws.send_json({"type": "done"})

    except WebSocketDisconnect:
        pass  # client disconnected normally
    except Exception:
        pass  # swallow unexpected errors so the server doesn't crash


# ---------------------------------------------------------------------------
# File routes
# ---------------------------------------------------------------------------
@app.get("/api/files/list")
async def list_files(path: str = Query(default=""), user: str = Depends(get_user)):
    raw = file_workspace.list_dir(path or ".", recursive=False)
    entries: list[dict] = []
    if raw and raw != "(empty directory)":
        for line in raw.split("\n"):
            if not line or line.startswith("..."):
                continue
            name = line.rstrip("/")
            is_dir = line.endswith("/")
            full = f"{path}/{name}" if path else name
            entries.append({
                "name": name,
                "path": full,
                "type": "directory" if is_dir else "file",
                "size": None,
            })
    return {"files": entries}


@app.get("/api/files/read")
async def read_file(path: str = Query(...), user: str = Depends(get_user)):
    return {"content": file_workspace.read(path), "path": path}


@app.post("/api/files/write")
async def write_file(body: dict, user: str = Depends(get_user)):
    result = file_workspace.write(body["path"], body.get("content", ""))
    return {"message": result}


@app.delete("/api/files/delete")
async def delete_file(path: str = Query(...), user: str = Depends(get_user)):
    result = file_workspace.delete(path)
    return {"message": result}


@app.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    dest_dir: str = Query(default=""),
    user: str = Depends(get_user),
):
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="只支持 UTF-8 文本文件")

    dest = f"{dest_dir}/{file.filename}" if dest_dir else file.filename
    result = file_workspace.write(dest, content)
    return {"message": result, "path": dest}


# ---------------------------------------------------------------------------
# Search routes
# ---------------------------------------------------------------------------
@app.get("/api/search/notices")
async def search_notices_api(q: str = Query(...), user: str = Depends(get_user)):
    return {"query": q, "results": search_notices(q)}


@app.get("/api/search/my-data")
async def search_my_data_api(q: str = Query(...), user: str = Depends(get_user)):
    return {"query": q, "results": search_user_data(q, user)}


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
@app.get("/api/admin/users")
async def admin_get_users(user: str = Depends(require_admin)):
    users = list_users()
    rag = RAGSystem()
    result = []
    for username, is_admin in users:
        index_size = rag.get_user_collection_size(username)
        result.append({"username": username, "is_admin": is_admin, "index_size": index_size})
    return {"users": result}


@app.delete("/api/admin/users/{username}")
async def admin_delete_user(username: str, user: str = Depends(require_admin)):
    if username == user:
        raise HTTPException(status_code=400, detail="不能删除自己")
    ok = auth_delete_user(username)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在或无法删除")
    rag = RAGSystem()
    rag.clear_user_index(username)
    return {"message": f"用户 {username} 已删除"}


@app.get("/api/admin/notices")
async def admin_get_notices(user: str = Depends(require_admin)):
    rag = RAGSystem()
    result = rag.list_public_documents()
    ids = result.get("ids") or []
    metadatas = result.get("metadatas") or []
    previews = result.get("previews") or []
    # Group by source, take first chunk's preview per source
    seen: dict[str, dict] = {}
    for i in range(len(ids)):
        source = metadatas[i].get("source", "未知") if i < len(metadatas) else "未知"
        if source not in seen:
            seen[source] = {"source": source, "preview": previews[i] if i < len(previews) else ""}
    return {"notices": list(seen.values())}


@app.post("/api/admin/notices")
async def admin_add_notice(body: dict, user: str = Depends(require_admin)):
    content = (body.get("content") or "").strip()
    source = (body.get("source") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    add_public_activity(content, source=source, admin_check=True)
    return {"message": "通知已添加"}


@app.delete("/api/admin/notices/{source}")
async def admin_delete_notice(source: str, user: str = Depends(require_admin)):
    from urllib.parse import unquote
    source = unquote(source)
    rag = RAGSystem()
    deleted = rag.delete_public_documents_by_source(source)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"message": f"通知已删除（{deleted} 个文档块）"}


@app.get("/api/admin/stats")
async def admin_get_stats(user: str = Depends(require_admin)):
    users = list_users()
    rag = RAGSystem()
    stats = rag.get_collection_stats()
    notices = rag.list_public_documents()
    unique_sources = len({m.get("source") for m in (notices.get("metadatas") or []) if m.get("source")})
    return {
        "user_count": len(users),
        "public_doc_count": unique_sources,
        "user_collections_count": stats.get("user_collections_count", 0),
        "agent_ready": get_agent() is not None,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {"status": "ok", "agent_ready": agent is not None}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
