import asyncio
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.services.news_service import SOURCES, NewsService, parse_headlines
from server.routes.news import router


def test_dates_sources_and_unsafe_links():
    html = '''<ul><li><a href="/notice/99.html">真实通知</a><span data-date="2026-09-02 17:33">09-02</span></li>
    <li><a href="javascript:alert(1)">坏链接</a><span>2026-09-03</span></li>
    <li><a href="https://evil.example/99.html">外部链接</a><span>2026-09-03</span></li>
    <li><a href="/guide/12.html">常用导航</a></li></ul>'''
    items = parse_headlines(html, SOURCES[1])
    assert len(items) == 1
    assert items[0]['published_at'] == '2026-09-02'
    assert items[0]['source_name'] == '本科生院教务处'


def test_library_does_not_invent_year():
    items = parse_headlines('<li><a href="/notice/foo"><p class="ellipsis">2026年通知</p><span>07-30</span></a></li>', SOURCES[4])
    assert items[0]['published_at'] is None
    assert items[0]['date_label'] == '07-30（来源未标年份）'


def test_network_title_and_deduplication():
    html = '<li><a href="/2026/0831/c33415a751714/page.htm"><div class="news_meta">08/31</div><div class="news_title">网络公告</div></a></li>'
    items = parse_headlines(html * 2, SOURCES[2])
    assert len(items) == 1
    assert items[0]['title'] == '网络公告'
    assert items[0]['published_at'] == '2026-08-31'


def test_source_failure_retains_cache(monkeypatch):
    async def fail(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx.AsyncClient, 'get', fail)
    service = NewsService()
    item = {'published_at': '2026-09-02', 'title': '已有消息'}
    service.cache['ustc'] = {'items': [item], 'updated_at': 'old'}
    data = asyncio.run(service.get_news(True))
    assert data['items'] == [item]
    assert data['sources'][0]['status'] == 'stale'
    assert data['sources'][0]['updated_at'] == 'old'
    assert data['sources'][1]['status'] == 'error'


def test_route(monkeypatch):
    from server.routes.news import news_service
    async def response(refresh=False):
        return {'items': [], 'sources': [], 'refreshed': refresh}
    monkeypatch.setattr(news_service, 'get_news', response)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/api/news?refresh=true').json()['refreshed'] is True
