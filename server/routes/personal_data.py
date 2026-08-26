"""Personal data routes: /api/personal-data/*"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from server.deps import get_user
from server.services.rag_service import RAGService, get_rag_service

router = APIRouter(prefix="/api/personal-data", tags=["personal-data"])


def _embed_unavailable_to_503(exc: RuntimeError):
    """campus_rag 的 fail-fast 守卫（嵌入不可用）抛 RuntimeError：这是服务
    不可用而非内部错误，用 503 + 原始详情回传，前端能展示可操作的提示，
    也避免与真实的 500 混淆。"""
    raise HTTPException(status_code=503, detail=str(exc))

# 注意：路径参数已由框架解码一次，禁止再次 unquote——双重解码会把字面含 %
# 的 source（如 "100%进度"、"a%20b"）损坏，导致更新/删除找错目标。


@router.get("")
async def get_personal_data(
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    # ChromaDB 读取是同步阻塞，丢进线程池避免卡住事件循环
    data = await asyncio.to_thread(rag.list_user_data, user)
    ids = data.get("ids") or []
    metadatas = data.get("metadatas") or []
    documents = data.get("documents") or []

    # 先按来源收集 (chunk_index, text)：ChromaDB 返回顺序无保证，
    # 多分块文档必须按入库时打的 chunk_index 排序才能还原原文。
    seen: dict[str, list] = {}
    for i in range(len(ids)):
        meta = metadatas[i] if i < len(metadatas) else {}
        source = meta.get("source", "手动输入")
        text = documents[i] if i < len(documents) else ""
        order = meta.get("chunk_index", 0)
        if not isinstance(order, (int, float)):
            order = 0
        seen.setdefault(source, []).append((order, text))

    items = []
    for source, chunks in seen.items():
        ordered = [text for _, text in sorted(chunks, key=lambda p: p[0])]
        full_content = "\n".join(ordered)
        items.append({
            "source": source,
            "preview": full_content[:200] + "..." if len(full_content) > 200 else full_content,
            "full_content": full_content,
            "chunks": len(ordered),
        })

    return {"items": items}


@router.post("")
async def add_personal_data(
    body: dict,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    content = (body.get("content") or "").strip()
    source = (body.get("source") or "").strip() or "手动输入"
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    # 入库含嵌入 API 调用，同步阻塞会卡住事件循环（可能数秒）
    try:
        await asyncio.to_thread(rag.add_user_data, user, content, source)
    except RuntimeError as e:
        _embed_unavailable_to_503(e)
    return {"message": "数据已添加"}


@router.put("/{source}")
async def update_personal_data(
    source: str,
    body: dict,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    try:
        await asyncio.to_thread(rag.update_user_data, user, source, content)
    except RuntimeError as e:
        _embed_unavailable_to_503(e)
    return {"message": "数据已更新"}


@router.delete("/{source}")
async def delete_personal_data(
    source: str,
    user: str = Depends(get_user),
    rag: RAGService = Depends(get_rag_service),
):
    count = await asyncio.to_thread(rag.delete_user_data, user, source)
    if count == 0:
        raise HTTPException(status_code=404, detail="数据不存在")
    return {"message": f"已删除 {count} 条数据"}
