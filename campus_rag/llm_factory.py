# llm_factory.py
import json
import os
from pathlib import Path

_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"


def _read_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f).get("env", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_llm():
    settings = _read_settings()
    provider = os.getenv("LLM_PROVIDER", "openai")

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY") or settings.get("api_key", "")
        base_url = os.getenv("OPENAI_BASE_URL") or settings.get("base_url", "https://api.deepseek.com")
        model = os.getenv("OPENAI_MODEL") or "deepseek-chat"

        # DeepSeek V4 模型挂在 /beta 端点下，settings.json 的 base_url 若未带该后缀
        # 会 404。此处幂等地补上 /beta，使配置无论写不写后缀均可正常调用。
        if "api.deepseek.com" in base_url and not base_url.rstrip("/").endswith("/beta"):
            base_url = base_url.rstrip("/") + "/beta"

        import llama_index.llms.openai.utils as oai_utils
        import llama_index.llms.openai.base as oai_base
        _orig = oai_utils.openai_modelname_to_contextsize
        def _patched(name):
            if name.startswith("deepseek"):
                return 131072
            return _orig(name)
        oai_utils.openai_modelname_to_contextsize = _patched
        oai_base.openai_modelname_to_contextsize = _patched

        from llama_index.llms.openai import OpenAI
        return OpenAI(
            model=model,
            api_key=api_key,
            api_base=base_url,
            temperature=0.1,
            timeout=120.0,
            max_tokens=4096,
        )

    elif provider == "ollama":
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(key, None)
        os.environ.setdefault("NO_PROXY", "*")
        from llama_index.llms.ollama import Ollama
        return Ollama(
            model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            temperature=0.1,
            request_timeout=360.0,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def get_embed_model():
    settings = _read_settings()
    provider = os.getenv("EMBED_PROVIDER", "ollama")

    if provider == "ollama":
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(key, None)
        os.environ.setdefault("NO_PROXY", "*")
        from llama_index.embeddings.ollama import OllamaEmbedding
        return OllamaEmbedding(
            model_name=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            base_url=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
        )

    elif provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding
        # 独立 EMBED_* 变量优先，避免与 LLM 分支的 OPENAI_* 变量互相污染
        # （OPENAI_* 同时也是 get_llm 的覆盖项，不能用于嵌入配置）。
        # 注意：必须用 model_name 关键字传自定义模型名，直接传 model= 会触发
        # OpenAIEmbeddingModelType 枚举校验（仅认 OpenAI 官方模型名）报错。
        return OpenAIEmbedding(
            model_name=os.getenv("EMBED_MODEL") or os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            api_key=os.getenv("EMBED_API_KEY") or os.getenv("OPENAI_API_KEY") or settings.get("api_key", ""),
            api_base=os.getenv("EMBED_BASE_URL") or os.getenv("OPENAI_BASE_URL") or settings.get("base_url", ""),
            timeout=60.0,
            max_retries=3,  # 默认 10 次在网络不可达时挂起太久，交互式场景收敛为 3 次
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")
