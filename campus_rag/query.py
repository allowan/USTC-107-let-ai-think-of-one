from pathlib import Path

_base = Path(__file__).resolve().parent

from .index_manager import RAGSystem
from llama_index.core.prompts import PromptTemplate

CUSTOM_PROMPT = PromptTemplate(
    "你是校园通知助手，请严格根据下面的通知片段回答用户问题。\n\n"
    "要求：\n"
    "1. 用中文回答，简洁清晰\n"
    "2. 若涉及多个条目（如多个活动、多项通知），请用序号排列\n"
    "3. 若通知片段中没有相关信息，请明确说\"未在通知中找到相关信息\"，不要编造\n"
    "通知片段：\n{context_str}\n\n"
    "用户问题：{query_str}\n\n"
    "你的回答："
)

_rag = None
_query_engine = None


def _init():
    global _rag, _query_engine
    if _rag is None:
        _rag = RAGSystem()
        index = _rag.get_or_create_public_index(str(_base / "data"))
        _query_engine = index.as_query_engine(
            similarity_top_k=20,
            text_qa_template=CUSTOM_PROMPT,
        )


def search_notices(query: str) -> str:
    """在校园通知中搜索相关信息，包括活动、比赛、课程、讲座等。"""
    _init()
    response = _query_engine.query(query)
    return str(response)
