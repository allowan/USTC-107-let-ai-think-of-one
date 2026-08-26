import asyncio
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain.tools import tool

logger = logging.getLogger("tools")

# 联网搜索配置与其他嵌入/重排序配置同放 campus_rag/.env；
# 环境变量已存在时不覆盖，保持"环境变量优先级 > 配置文件"约定。
load_dotenv(Path(__file__).resolve().parent.parent / "campus_rag" / ".env")

# 超大页面全文进入 LLM 上下文会撞穿 context window，截断并留痕。
_MAX_CONTENT_CHARS = 50000
_SEARCH_TIMEOUT = 20.0
_TAVILY_ENDPOINT = "https://api.tavily.com/search"

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; campus-assistant/1.0)"}

# 这些标签的内容对阅读正文无意义，剥离以节省上下文
_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "noscript", "iframe")


def _extract_text_from_html(html: str) -> str:
    """Strip non-content tags from HTML and return readable plain text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
    return "\n".join(line for line in lines if line)


@tool("fetch_url")
def fetch_url(url: str) -> str:
    """获取指定 URL 网页的正文文本。当需要精读某条联网搜索结果的完整内容时使用。"""
    try:
        resp = httpx.get(
            url,
            headers=_HEADERS,
            timeout=120.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = _extract_text_from_html(resp.text)
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS] + "\n\n[内容过长已截断]"
        return text
    except httpx.HTTPError as e:
        logger.error("fetch_url failed for %s: %s", url, e)
        return f"Fetch failed: {e}"


def _format_results(results: list[dict]) -> str:
    """把 {title, url, content/body} 结果列表格式化为带编号的文本。"""
    if not results:
        return "未找到相关搜索结果。"
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "") or r.get("href", "")
        content = r.get("content", "") or r.get("body", "")
        lines.append(f"{i}. {title}\n链接: {url}\n摘要: {content}")
    return "\n\n".join(lines)


async def _search_tavily(query: str) -> str:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return (
            "联网搜索未配置：请在 campus_rag/.env 中设置 TAVILY_API_KEY"
            "（Tavily 免费版 https://tavily.com），或设置 WEBSEARCH_PROVIDER=ddg "
            "使用免 Key 的 DuckDuckGo 搜索。"
        )
    async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
        resp = await client.post(
            _TAVILY_ENDPOINT,
            json={"query": query, "search_depth": "basic", "max_results": 5},
            headers={**_HEADERS, "Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    return _format_results(results)


def _search_ddg(query: str) -> str:
    # duckduckgo_search 已更名 ddgs，两个包名都兼容
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    return _format_results(results)


@tool("web_search")
async def search_web(query: str) -> str:
    """联网搜索：输入关键词，返回网页搜索结果列表（标题/摘要/链接）。
    本地知识库查不到的时效性信息、校外信息、最新动态时使用。"""
    provider = os.getenv("WEBSEARCH_PROVIDER", "tavily").strip().lower()
    try:
        if provider == "ddg":
            return await asyncio.to_thread(_search_ddg, query)
        return await _search_tavily(query)
    except Exception as e:
        logger.error("web_search failed: %s", e, exc_info=True)
        return f"联网搜索失败: {e}"
