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
        # The chat agent uses the LLM_* names. Keep OPENAI_* as an override so
        # the RAG summarizer works with the same local configuration instead of
        # constructing a client with an empty key and failing much later.
        api_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or settings.get("api_key", "")
        )
        base_url = (
            os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or settings.get("base_url", "https://api.deepseek.com")
        )
        model = (
            os.getenv("OPENAI_MODEL")
            or os.getenv("LLM_MODEL")
            or settings.get("model", "deepseek-chat")
        )
        if not api_key:
            raise RuntimeError(
                "未配置 LLM API Key。请设置 LLM_API_KEY 或 OPENAI_API_KEY，"
                "或在 settings.json 的 env.api_key 中配置。"
            )

        try:
            request_timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
        except ValueError:
            request_timeout = 45.0
        request_timeout = max(5.0, min(request_timeout, 120.0))

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
            timeout=request_timeout,
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
        return OpenAIEmbedding(
            model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            api_key=(
                os.getenv("OPENAI_API_KEY")
                or os.getenv("LLM_API_KEY")
                or settings.get("api_key", "")
            ),
            api_base=(
                os.getenv("OPENAI_BASE_URL")
                or os.getenv("LLM_BASE_URL")
                or settings.get("base_url", "https://api.deepseek.com")
            ),
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")
