"""Crawler helpers for configured USTC notice columns."""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from tools.search import USER_AGENT, fetch_ustc_page_text

# 各站点文章链接路径模式：
# - ustc.edu.cn 主站栏目：/info/<栏目号>/<文章号>.htm
# - 研究生院：/article/<文章号>
# - 教务处：<栏目>/<子栏目>/<文章号>.html
# - 网络信息中心等 PageWeb 站点：/<年>/<月日>/c<栏目号>a<文章号>/page.htm
_ARTICLE_PATH_RE = re.compile(
    r"/info/\d+/\d+\.htm(?:$|[?#])"
    r"|/article/\d+(?:$|[?#])"
    r"|/[\w-]+/[\w-]+/\d+\.html?(?:$|[?#])"
    r"|/\d{4}/\d{4}/c\d+a\d+/page\.htm(?:$|[?#])"
)


class _ArticleLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._title: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href", "")
        if not href:
            return
        url = urljoin(self.base_url, href)
        if not (_ARTICLE_PATH_RE.search(url) or "tzggcontent.jsp" in href):
            return
        self._href = url
        self._title = values.get("title", "").strip() or None
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        # 研究生院/教务处列表的 a 标签不一定带 title 属性，回退到链接文本
        title = self._title or " ".join("".join(self._text).split())
        if title:
            self.links.append({"title": title, "url": self._href})
        self._href = None
        self._title = None
        self._text = []


def extract_article_links(content: str, base_url: str) -> list[dict[str, str]]:
    parser = _ArticleLinkParser(base_url)
    parser.feed(content)
    unique = {}
    for item in parser.links:
        unique[item["url"]] = item
    return list(unique.values())


def article_id(url: str) -> str:
    match = re.search(r"/info/(\d+)/(\d+)\.htm", url)
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    query = parse_qs(urlparse(url).query)
    if query.get("wbnewsid"):
        return f"legacy_{query['wbnewsid'][0]}"
    # PageWeb 站点：/<年>/<月日>/c<栏目号>a<文章号>/page.htm，沿用"栏目号_文章号"语义
    match = re.search(r"/c(\d+)a(\d+)/page\.htm", url)
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    # 教务处 /…/<id>.html 与研究生院 /article/<id>：路径末段数字即文章号，
    # 与 campus_rag/data 里手动种子文件的命名（20425_…、3384_…）保持同一语义。
    match = re.search(r"/(\d+)(?:\.html?)?$", url)
    if match:
        return match.group(1)
    return hashlib.sha256(url.encode()).hexdigest()[:16]


# 文件名非法字符（Windows 保留字符 + 控制符）
_FILENAME_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def notice_filename(url: str, title: str) -> str:
    """生成 {通知ID}_{标题}.txt 文件名，与手动种子文件的命名规范一致。

    通知 ID 取 article_id 的最后一段（如 1366_25525 取 25525、legacy_22309
    取 22309），保证文件名数字前缀能被 data_loader 的源网址提取逻辑命中。
    哈希兜底的 ID 含非数字字符时加 x 前缀：若哈希恰以数字开头，会被
    extract_source_url 当成通知 ID 去正文里乱匹配出错误源链接。
    """
    notice_id = article_id(url).rsplit("_", 1)[-1]
    if not notice_id.isdigit():
        notice_id = f"x{notice_id}"
    cleaned = _FILENAME_BAD_CHARS.sub("_", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("._ ")
    return f"{notice_id}_{cleaned[:60]}.txt"


# Visual SiteBuilder 的分页器形如 <span class="p_t">1/27</span>：页数比例必须是
# 某个元素的全部文本内容。放宽成任意 "数字/数字" 会把模板资源路径
# （dfiles/11339/_upload/...）误读成上万页。
_PAGER_RE = re.compile(r">\s*\d+\s*/\s*(\d+)\s*<")


def discover_total_pages(content: str) -> int:
    """Return the Visual SiteBuilder page count, defaulting to one page."""
    matches = re.findall(_PAGER_RE, content)
    return max((int(value) for value in matches), default=1)


def column_page_urls(url: str, max_pages: int, total_pages: int = 1) -> list[str]:
    urls = [url]
    stem = url.rsplit("/", 1)[-1].removesuffix(".htm")
    base = url.rsplit("/", 1)[0] + "/"
    requested_pages = min(max(1, max_pages), max(1, total_pages))
    for page_number in range(2, requested_pages + 1):
        # Visual SiteBuilder names page 2 as total_pages-1 and the last page as 1.
        page_file = total_pages - page_number + 1
        urls.append(urljoin(base, f"{stem}/{page_file}.htm"))
    return urls


# 教务处等站点会对短时间内的并发抓取返回 403，退避后重试即可恢复。
_RETRYABLE_STATUS = {403, 408, 429, 500, 502, 503, 504}
# 同一栏目内每个文章请求前的固定间隔，避免短时高频触发站点限流。
POLITE_DELAY = 0.3


def _get_with_retry(url: str, attempts: int = 3, delay: float = 2.0) -> httpx.Response:
    """抓取栏目列表页，对限流/瞬时错误退避重试。

    列表页失败会让整个栏目零产出（discovered=0），比单篇文章失败严重得多，
    因此限流状态码必须重试而不是直接放弃。
    """
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code not in _RETRYABLE_STATUS:
                raise
        except (httpx.TransportError, OSError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay * attempt)
    raise last_error  # type: ignore[misc]


def fetch_column_links(url: str, max_pages: int = 1) -> list[dict[str, str]]:
    first_response = _get_with_retry(url)
    links = extract_article_links(first_response.text, str(first_response.url))
    total_pages = discover_total_pages(first_response.text)
    for page_url in column_page_urls(url, max_pages, total_pages)[1:]:
        response = _get_with_retry(page_url)
        links.extend(extract_article_links(response.text, str(response.url)))
    unique = {}
    for item in links:
        unique[item["url"]] = item
    return list(unique.values())


def fetch_article_text(url: str, attempts: int = 3, delay: float = 1.5) -> str:
    """抓取文章正文，对限流/瞬时错误做退避重试。"""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_ustc_page_text(url, max_chars=200_000)
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code not in _RETRYABLE_STATUS:
                raise
        except (httpx.TransportError, OSError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay * attempt)
    raise last_error  # type: ignore[misc]


def sync_column(column: dict, data_dir: Path) -> dict:
    links = fetch_column_links(column["url"], int(column.get("max_pages", 1)))
    links = links[: int(column.get("max_articles", 30))]
    stats = {
        "discovered": len(links),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }
    data_dir.mkdir(parents=True, exist_ok=True)

    def fetch(item):
        # 并发过高会被站点 nginx 判定为异常流量并返回 403，故降并发 + 请求间隔。
        time.sleep(POLITE_DELAY)
        body = fetch_article_text(item["url"])
        # 文档头与手动种子文件一致：来源 → 标题 → 空行 → 正文
        document = f"来源：{item['url']}\n标题：{item['title']}\n\n{body.strip()}\n"
        return item, document

    with ThreadPoolExecutor(max_workers=min(2, len(links) or 1)) as executor:
        futures = {executor.submit(fetch, item): item for item in links}
        for future in as_completed(futures):
            item = futures[future]
            try:
                _, document = future.result()
                output = data_dir / notice_filename(item["url"], item["title"])
                previous = output.read_text(encoding="utf-8") if output.exists() else None
                if previous == document:
                    stats["unchanged"] += 1
                else:
                    output.write_text(document, encoding="utf-8")
                    stats["created" if previous is None else "updated"] += 1
            except Exception as exc:
                # Some legacy notices redirect to USTC's CAS login. They are
                # intentionally not crawled and must not make a public sync fail.
                if "白名单之外" in str(exc) and "tzggcontent.jsp" in item["url"]:
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
                stats["errors"].append(f"{item['url']}: {type(exc).__name__}: {exc}")
    return stats


def load_columns(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))
