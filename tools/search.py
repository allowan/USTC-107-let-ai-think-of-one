"""Safe, text-oriented web search and page fetching tools."""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain.tools import tool

# 联网搜索配置与嵌入/重排序同处 campus_rag/.env；环境变量已存在时不覆盖，
# 保持"环境变量优先于配置文件"约定。main.py 先于 campus_rag 导入本模块，
# 不能依赖 campus_rag 包初始化时才加载。
load_dotenv(Path(__file__).resolve().parent.parent / "campus_rag" / ".env")

USER_AGENT = "Mozilla/5.0 (compatible; USTC-Campus-Agent/1.0)"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOOL_CHARS = 20_000
# Keep a failed proxy/DNS request from making the whole conversation appear
# frozen. The connect timeout is intentionally shorter than the read timeout:
# a reachable site may still need a few seconds to return its HTML.
SEARCH_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
FETCH_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
TRUSTED_PROXY_HOST_SUFFIXES = ("ustc.edu.cn",)
USTC_SITES_PATH = Path(__file__).resolve().parent.parent / "campus_rag" / "ustc_sites.json"
TAVILY_ENDPOINT = "https://api.tavily.com/search"
logger = logging.getLogger("tools.search")


def _is_trusted_proxy_host(host: str) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in TRUSTED_PROXY_HOST_SUFFIXES)


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持有效的 HTTP/HTTPS URL")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("不允许访问本机或局域网地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError(f"域名无法解析: {host}") from exc
    if not _is_trusted_proxy_host(host) and any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("不允许访问本机、私有或保留地址")
    return parsed.geturl()


class _TextExtractor(HTMLParser):
    """Prefer article-like containers, falling back to visible body text."""

    _BLOCKED = {"script", "style", "noscript", "svg", "canvas"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    _TARGET_CLASSES = {"wp_articlecontent", "article", "entry-content", "post-content"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._depth = 0
        self._target_roots: list[int] = []
        self._all: list[str] = []
        self._target: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in self._VOID:
            self._depth += 1
        if tag in self._BLOCKED:
            self._blocked_depth += 1
        classes = set(dict(attrs).get("class", "").split())
        if tag in {"article", "main"} or classes.intersection(self._TARGET_CLASSES):
            self._target_roots.append(self._depth)
        if tag in {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4"}:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCKED and self._blocked_depth:
            self._blocked_depth -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self._append("\n")
        if self._target_roots and self._target_roots[-1] == self._depth:
            self._target_roots.pop()
        if tag not in self._VOID:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth:
            self._append(data)

    def _append(self, value: str) -> None:
        self._all.append(value)
        if self._target_roots:
            self._target.append(value)

    def text(self) -> str:
        values = self._target if any(v.strip() for v in self._target) else self._all
        text = html.unescape(" ".join(values)).replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_page_text(content: str) -> str:
    parser = _TextExtractor()
    parser.feed(content)
    return parser.text()


def fetch_page_text(
    url: str,
    max_chars: int = MAX_TOOL_CHARS,
    allowed_hosts: set[str] | None = None,
) -> str:
    safe_url = _validate_public_url(url)
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT, follow_redirects=True
    ) as client:
        with client.stream("GET", safe_url) as response:
            response.raise_for_status()
            _validate_public_url(str(response.url))
            final_host = urlparse(str(response.url)).hostname.lower()
            if allowed_hosts is not None and final_host not in allowed_hosts:
                raise ValueError("网页重定向到了白名单之外的站点")
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("网页响应超过 2 MiB 限制")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
    text = extract_page_text(b"".join(chunks).decode(encoding, errors="replace"))
    if not text:
        raise ValueError("网页没有可提取的正文")
    return text[:max_chars]


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href: str | None = None
        self._title: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and "result__a" in attrs_dict.get("class", ""):
            self._href = attrs_dict.get("href")
            self._title = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        href = urljoin("https://html.duckduckgo.com", self._href)
        redirected = parse_qs(urlparse(href).query).get("uddg")
        if redirected:
            href = unquote(redirected[0])
        title = " ".join(self._title).strip()
        if title and href.startswith(("http://", "https://")):
            self.results.append({"title": title, "url": href})
        self._href = None
        self._title = []


def _search_web_results(query: str, max_results: int = 5) -> list[dict[str, str]]:
    query = query.strip()
    if not query:
        raise ValueError("搜索关键词不能为空")
    response = httpx.get(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        headers={"User-Agent": USER_AGENT},
        timeout=SEARCH_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    parser = _DuckDuckGoParser()
    parser.feed(response.text)
    return parser.results[: max(1, min(max_results, 10))]


def _search_tavily_results(query: str, api_key: str, max_results: int = 5) -> list[dict[str, str]]:
    """Tavily 搜索结果（需 TAVILY_API_KEY），返回 {title, url} 列表。"""
    query = query.strip()
    if not query:
        raise ValueError("搜索关键词不能为空")
    response = httpx.post(
        TAVILY_ENDPOINT,
        json={"query": query, "search_depth": "basic", "max_results": max_results},
        headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {api_key}"},
        timeout=SEARCH_TIMEOUT,
    )
    response.raise_for_status()
    return [
        {"title": item.get("title") or item.get("url", ""), "url": item.get("url", "")}
        for item in response.json().get("results", [])
        if item.get("url")
    ][: max(1, min(max_results, 10))]


def _format_search_results(results: list[dict[str, str]]) -> str:
    if not results:
        return "未找到网页搜索结果。"
    return "\n".join(
        f"{index}. {_format_markdown_link(item['title'], item['url'])}"
        for index, item in enumerate(results, start=1)
    )


def _format_markdown_link(label: str, url: str) -> str:
    """Format a trusted HTTP(S) result as a Markdown link for the Agent.

    Search results are passed to the model as tool output. Keeping the title
    and URL together in Markdown makes it possible for the final chat UI to
    render the source as a clickable link instead of showing a bare URL.
    """
    safe_label = re.sub(r"\s+", " ", label).strip()
    safe_label = safe_label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    # A closing parenthesis would terminate the Markdown destination early.
    # Percent-encoding it preserves the destination while keeping the link
    # valid for CommonMark parsers.
    safe_url = url.strip().replace(")", "%29")
    return f"[{safe_label}]({safe_url})"


def search_web_text(query: str, max_results: int = 5) -> str:
    return _format_search_results(_search_web_results(query, max_results))


def load_ustc_sites() -> list[dict[str, str]]:
    return json.loads(USTC_SITES_PATH.read_text(encoding="utf-8"))


def _ustc_allowed_hosts() -> set[str]:
    return {urlparse(site["url"]).hostname.lower() for site in load_ustc_sites()}


def _validate_ustc_url(url: str) -> str:
    validated = _validate_public_url(url)
    host = urlparse(validated).hostname.lower()
    if host not in _ustc_allowed_hosts():
        raise ValueError("该 URL 不在中国科大官方站点白名单中")
    return validated


def search_ustc_web_text(query: str, max_results: int = 5) -> str:
    results = _search_web_results(f"site:ustc.edu.cn {query}", max_results=10)
    allowed = _ustc_allowed_hosts()
    official = [
        item for item in results
        if urlparse(item["url"]).hostname
        and urlparse(item["url"]).hostname.lower() in allowed
    ][:max_results]
    return _format_search_results(official)


def fetch_ustc_page_text(url: str, max_chars: int = MAX_TOOL_CHARS) -> str:
    return fetch_page_text(
        _validate_ustc_url(url),
        max_chars=max_chars,
        allowed_hosts=_ustc_allowed_hosts(),
    )


@tool("web_search")
def search_web(query: str) -> str:
    """Search the public web and return result titles and URLs."""
    try:
        # WEBSEARCH_PROVIDER 默认 tavily（需 TAVILY_API_KEY），未配置 Key 或
        # 显式设 ddg 时走免 Key 的 DuckDuckGo 兜底。
        provider = os.getenv("WEBSEARCH_PROVIDER", "tavily").strip().lower()
        if provider == "tavily":
            api_key = os.getenv("TAVILY_API_KEY", "").strip()
            if api_key:
                try:
                    return _format_search_results(_search_tavily_results(query, api_key))
                except (httpx.HTTPError, OSError) as exc:
                    logger.warning("Tavily search failed, falling back to DuckDuckGo: %s", exc)
            else:
                logger.warning("WEBSEARCH_PROVIDER=tavily but TAVILY_API_KEY is not set; falling back to DuckDuckGo")
        return search_web_text(query)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("public web search failed for %r: %s", query, exc)
        return f"搜索失败（网络或代理不可用）：{exc}。请不要重复调用此工具。"


@tool("web_fetch")
def fetch_text_from_url(url: str) -> str:
    """Fetch a public HTTP/HTTPS page and return extracted visible text."""
    try:
        return f"来源: {_format_markdown_link('网页原文', url)}\n\n{fetch_page_text(url)}"
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("web fetch failed for %s: %s", url, exc)
        return f"网页读取失败（网络或代理不可用）：{exc}。请不要重复调用此工具。"


@tool("ustc_web_search")
def search_ustc_web(query: str) -> str:
    """Search configured official USTC websites for up-to-date public information."""
    try:
        return search_ustc_web_text(query)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("USTC web search failed for %r: %s", query, exc)
        return f"科大网站搜索失败（网络或代理不可用）：{exc}。请不要重复调用此工具。"


@tool("ustc_web_fetch")
def fetch_ustc_text_from_url(url: str) -> str:
    """Fetch visible text from a URL on the configured official USTC website whitelist."""
    try:
        return f"来源: {_format_markdown_link('网页原文', url)}\n\n{fetch_ustc_page_text(url)}"
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("USTC fetch failed for %s: %s", url, exc)
        return f"科大网页读取失败（网络或代理不可用）：{exc}。请不要重复调用此工具。"
