import httpx
from langchain.tools import tool

# 超大页面全文进入 LLM 上下文会撞穿 context window，截断并留痕。
_MAX_CONTENT_CHARS = 50000

@tool("web_search")
def fetch_text_from_url(url: str) -> str:
    """Fetch the document from a URL."""
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; quickstart-research/1.0)"},
            timeout=120.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS] + "\n\n[内容过长已截断]"
        return text
    except httpx.HTTPError as e:
        return f"Fetch failed: {e}"