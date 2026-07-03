#llm_factory.py
import os

def get_llm():
    provider=os.getenv("LLM_PROVIDER","ollama") 
    if provider=="ollama":
        from llama_index.llms.ollama import Ollama
        return Ollama(
            model=os.getenv("OLLAMA_MODEL","llama3.1:8b"),
            temperature=0.1,
            request_timeout=120.0,
        )
    elif provider=="openai":
        from llama_index.llms.openai import OpenAI
        return OpenAI(
            model=os.getenv("OPENAI_MODEL","gpt-4"),
            api_key=os.getenv("OPENAI_API_KEY"),
            api_base=os.getenv("OPENAI_BASE_URL"),
            temperature=0.1,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

def get_embed_model():
    provider=os.getenv("EMBED_PROVIDER","ollama")
    if provider=="ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding
        return OllamaEmbedding(
            model_name=os.getenv("OLLAMA_EMBED_MODEL","nomic-embed-text"),
        )
    elif provider=="openai":
        from llama_index.embeddings.openai import OpenAIEmbedding
        return OpenAIEmbedding(
            model=os.getenv("OPENAI_EMBED_MODEL","text-embedding-3-small"),
            api_key=os.getenv("OPENAI_API_KEY"),
            api_base=os.getenv("OPENAI_BASE_URL"),
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")

