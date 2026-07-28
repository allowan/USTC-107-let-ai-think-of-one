import httpx
from langchain.tools import tool

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
        return resp.text
    except httpx.HTTPError as e:
        return f"Fetch failed: {e}"