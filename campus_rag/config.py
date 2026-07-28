# config.py
import logging
from llama_index.core import Settings

logger = logging.getLogger("campus_rag")

Settings.llm = None
Settings.embed_model = None
Settings.chunk_size = 1024
Settings.chunk_overlap = 50

_llm_initialized = False
_embed_initialized = False


def init_llm() -> bool:
    """Initialize LLM. Returns True on success, False if still unconfigured."""
    global _llm_initialized
    if _llm_initialized and Settings.llm is not None:
        return True
    try:
        from .llm_factory import get_llm
        Settings.llm = get_llm()
        _llm_initialized = True
        return True
    except Exception as e:
        logger.debug("LLM not available: %s", e)
        return False


def init_embed() -> bool:
    """Initialize embedding model. Returns True on success, False if still unconfigured."""
    global _embed_initialized
    if _embed_initialized and Settings.embed_model is not None:
        return True
    try:
        from .llm_factory import get_embed_model
        Settings.embed_model = get_embed_model()
        _embed_initialized = True
        return True
    except Exception as e:
        logger.debug("Embedding not available: %s", e)
        return False
