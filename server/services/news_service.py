"""Read public campus headlines; no model or personal credentials are required."""
import asyncio
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

SOURCES = [
    {'id': 'ustc', 'name': '中国科大 · 服务通知', 'url': 'https://www.ustc.edu.cn/tzgg/fwltz.htm'},
    {'id': 'teach', 'name': '本科生院教务处', 'url': 'https://www.teach.ustc.edu.cn/'},
    {'id': 'net', 'name': '网络信息中心', 'url': 'https://ustcnet.ustc.edu.cn/'},
    {'id': 'grad', 'name': '研究生院', 'url': 'https://gradschool.ustc.edu.cn/'},
    {'id': 'lib', 'name': '图书馆', 'url': 'https://lib.ustc.edu.cn/'},
]


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        # Iterative traversal: recursive descent overflows on pathologically
        # nested pages, and that exception would bubble up to a 500.
        parts, stack = [], list(reversed(self.children))
        while stack:
            c = stack.pop()
            if isinstance(c, str):
                parts.append(c)
            else:
                stack.extend(reversed(c.children))
        return ' '.join(parts).strip()

    def walk(self):
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            for c in reversed(node.children):
                if isinstance(c, Node):
                    stack.append(c)


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_headlines(html, source):
    items = {}
    for row in Tree(html).root.walk():
        if row.tag not in {'li', 'tr'}:
            continue
        nodes = list(row.walk())
        date = ''
        for n in nodes:
            # Read date elements, not years mentioned in a headline.
            value = n.attrs.get('data-date', '') or (n.text() if n.tag in {'span', 'td'} and len(n.text()) < 24 else '')
            match = re.search(r'\b(20\d{2})[-/.](\d{2})[-/.](\d{2})\b', value)
            if match:
                date = '-'.join(match.groups())
                break
        links = [n for n in nodes if n.tag == 'a' and n.attrs.get('href')]
        if source['id'] == 'grad' and row.attrs.get('data-link', '').startswith('/article/'):
            links = [Node('a', [('href', row.attrs['data-link']), ('title', next((n.attrs['title'] for n in nodes if n.tag == 'p' and n.attrs.get('title')), ''))])]
            m = re.search(r'(\d{2})/(\d{2})\s+(20\d{2})', row.text())
            if m:
                date = f'{m[3]}-{m[1]}-{m[2]}'
        for a in links:
            url = urljoin(source['url'], a.attrs['href'])
            if urlparse(url).scheme not in {'https', 'http'} or urlparse(url).hostname != urlparse(source['url']).hostname:
                continue
            path = urlparse(url).path
            kind = source['id']
            if kind == 'ustc' and not (re.search(r'/info/\d+/\d+\.htm$', path) or path.endswith('tzggcontent.jsp')):
                continue
            if kind == 'teach' and not (date and re.search(r'/\d+\.html$', path)):
                continue
            if kind == 'net':
                m = re.search(r'/(20\d{2})/(\d{2})(\d{2})/c33415a\d+/page.htm', path)
                if not m:
                    continue
                date = '-'.join(m.groups())
            if kind == 'grad' and not (row.attrs.get('data-link') and date):
                continue
            title = a.attrs.get('title') or a.text()
            if kind == 'net':
                title = next((n.text() for n in nodes if 'news_title' in n.attrs.get('class', '')), title)
            title = ' '.join(title.split())
            display_date = date
            if kind == 'lib':
                headline = next((n for n in nodes if n.tag == 'p' and 'ellipsis' in n.attrs.get('class', '')), None)
                if not headline:
                    continue
                title = headline.text()
                partial = next((n.text() for n in nodes if n.tag == 'span' and re.fullmatch(r'\d{2}-\d{2}', n.text())), '')
                display_date = f'{partial}（来源未标年份）' if partial else ''
            if not title.strip():
                continue
            items[url] = {'title': title.strip(), 'url': url, 'source_id': kind, 'source_name': source['name'], 'source_url': source['url'], 'published_at': date or None, 'date_label': display_date or '来源未提供日期'}
    return sorted(items.values(), key=lambda x: x['published_at'] or '', reverse=True)[:20]


class NewsService:
    def __init__(self):
        self.cache = {}
        self.checked = 0
        self.lock = asyncio.Lock()

    async def get_news(self, refresh=False):
        async with self.lock:
            if refresh or not self.checked or time.monotonic() - self.checked > 300:
                async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={'User-Agent': 'USTC-Campus-News/1.0'}) as client:
                    async def fetch(source):
                        previous = self.cache.get(source['id'], {})
                        try:
                            response = await client.get(source['url'])
                            response.raise_for_status()
                            items = parse_headlines(response.text, source)
                            if not items:
                                raise ValueError('No headlines')
                            return source['id'], {**source, 'items': items, 'status': 'ok', 'updated_at': datetime.now(timezone.utc).isoformat()}
                        except (httpx.HTTPError, ValueError):
                            return source['id'], {**source, 'items': previous.get('items', []), 'status': 'stale' if previous.get('items') else 'error', 'updated_at': previous.get('updated_at')}
                    self.cache = dict(await asyncio.gather(*(fetch(s) for s in SOURCES)))
                self.checked = time.monotonic()
            items = [item for s in self.cache.values() for item in s['items']]
            items.sort(key=lambda x: x['published_at'] or '', reverse=True)
            return {'items': items, 'sources': [{k: v for k, v in s.items() if k != 'items'} for s in self.cache.values()]}


news_service = NewsService()
