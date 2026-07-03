# config.py
from llama_index.core import Settings
from .llm_factory import get_llm, get_embed_model

Settings.llm = get_llm()
Settings.embed_model = get_embed_model()
# 其他全局设置
Settings.chunk_size = 1024
Settings.chunk_overlap = 50