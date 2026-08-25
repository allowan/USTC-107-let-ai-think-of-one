"""Crawler helpers for configured USTC notice columns."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from tools.search import USER_AGENT, fetch_ustc_page_text


class _ArticleLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href", "")
        title = values.get("title", "").strip()
        if not title or not (
            re.search(r"/info/\d+/\d+\.htm(?:$|[?#])", urljoin(self.base_url, href))
            or "tzggcontent.jsp" in href
        ):
            return
        self.links.append({"title": title, "url": urljoin(self.base_url, href)})


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
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def discover_total_pages(content: str) -> int:
    """Return the Visual SiteBuilder page count, defaulting to one page."""
    matches = re.findall(r"\b\d+\s*/\s*(\d+)\b", content)
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


def fetch_column_links(url: str, max_pages: int = 1) -> list[dict[str, str]]:
    first_response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )
    first_response.raise_for_status()
    links = extract_article_links(first_response.text, str(first_response.url))
    total_pages = discover_total_pages(first_response.text)
    for page_url in column_page_urls(url, max_pages, total_pages)[1:]:
        response = httpx.get(
            page_url,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        links.extend(extract_article_links(response.text, str(response.url)))
    unique = {}
    for item in links:
        unique[item["url"]] = item
    return list(unique.values())


def sync_column(column: dict, data_dir: Path) -> dict:
    links = fetch_column_links(column["url"], int(column.get("max_pages", 1)))
    links = links[: int(column.get("max_articles", 30))]
    prefix = column.get("output_prefix", "ustc_notice")
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
        body = fetch_ustc_page_text(item["url"], max_chars=200_000)
        document = f"标题：{item['title']}\n来源：{item['url']}\n栏目：{column['name']}\n\n{body.strip()}\n"
        return item, document

    with ThreadPoolExecutor(max_workers=min(4, len(links) or 1)) as executor:
        futures = {executor.submit(fetch, item): item for item in links}
        for future in as_completed(futures):
            item = futures[future]
            try:
                _, document = future.result()
                output = data_dir / f"{prefix}_{article_id(item['url'])}.txt"
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
