# config.py
import logging
from llama_index.core import Settings

logger = logging.getLogger("campus_rag")

# 注意：禁止写 Settings.llm = None / Settings.embed_model = None。
# llama_index 的 setter 会把 None 立即 resolve 成 MockLLM / MockEmbedding
# （并打印 "explicitly disabled" 警告），污染全局状态；之后任何直接读取
# Settings.llm 的代码（如 get_rag_response）都会静默拿到 Mock 对象。
# Settings 单例的初始值本来就是 None，无需显式重置。
Settings.chunk_size = 1024
Settings.chunk_overlap = 50

_llm_initialized = False
_embed_initialized = False


def init_llm() -> bool:
    """Initialize LLM. Returns True on success, False if still unconfigured."""
    global _llm_initialized
    if _llm_initialized and Settings._llm is not None:
        return True
    try:
        from .llm_factory import get_llm
        Settings.llm = get_llm()
        _llm_initialized = True
        return True
    except Exception as e:
        # ERROR 级别：LLM 不可用会让 require_llm 拒绝服务，必须让原因可见
        logger.error("LLM 服务初始化失败: %s", e)
        return False


def init_embed() -> bool:
    """Initialize embedding model. Returns True on success, False if still unconfigured."""
    global _embed_initialized
    if _embed_initialized and Settings._embed_model is not None:
        return True
    try:
        from .llm_factory import get_embed_model
        Settings.embed_model = get_embed_model()
        _embed_initialized = True
        return True
    except Exception as e:
        # ERROR 级别：嵌入不可用会连带 RAGSystem 拒绝初始化，必须让原因可见
        logger.error("嵌入服务初始化失败: %s", e)
        return False


def require_llm():
    """返回真实 LLM；不可用时抛异常，禁止静默降级到 MockLLM。

    注意：不能用 Settings.llm getter 判断是否已初始化——getter 在未初始化时
    会自动 resolve 出 MockLLM，必须走 init 标志位。
    """
    if not init_llm():
        raise RuntimeError(
            "LLM 服务不可用，已拒绝生成回答（避免 MockLLM 静默降级）。"
            "请检查 settings.json 的 api_key/base_url 及 LLM API 的网络可达性。"
        )
    return Settings.llm


def require_embed_model():
    """返回真实嵌入模型；不可用时抛异常，禁止静默降级到 MockEmbedding。"""
    if not init_embed():
        raise RuntimeError(
            "嵌入服务不可用，已拒绝检索（避免 MockEmbedding 静默降级）。"
            "请检查 campus_rag/.env 的 EMBED_* 配置及嵌入 API 的网络可达性。"
        )
    return Settings.embed_model
