"""联网搜索工具测试（tools/search.py）

覆盖：HTML 正文提取与截断、Tavily 结果格式化、未配置时的友好降级。
全部离线可运行（网络请求用 mock 替代）。

用法：
    python -m pytest tests/test_web_tools.py -v
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


class TestExtractHtml(unittest.TestCase):
    """HTML → 纯文本提取逻辑。"""

    def _extract(self, html: str) -> str:
        from tools.search import _extract_text_from_html
        return _extract_text_from_html(html)

    def test_strip_script_and_style(self):
        html = """
        <html><head><style>body{color:red}</style>
        <script>console.log("x")</script></head>
        <body><nav>菜单</nav><p>正文内容</p><footer>页脚</footer></body></html>
        """
        text = self._extract(html)
        self.assertIn("正文内容", text)
        self.assertNotIn("console.log", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("菜单", text)
        self.assertNotIn("页脚", text)

    def test_blank_lines_collapsed(self):
        text = self._extract("<div>a</div>\n\n\n<div>b</div>")
        self.assertEqual(text.splitlines(), ["a", "b"])


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


class TestFetchUrl(unittest.TestCase):
    """fetch_url 工具：HTML 剥离 + 超长截断。"""

    def _fetch(self, html: str) -> str:
        from tools import search
        with patch.object(search.httpx, "get", return_value=_FakeResponse(html)):
            return search.fetch_url.invoke({"url": "https://example.com"})

    def test_html_stripped_to_plain_text(self):
        result = self._fetch("<html><body><script>x=1</script><h1>标题</h1><p>内容</p></body></html>")
        self.assertIn("标题", result)
        self.assertIn("内容", result)
        self.assertNotIn("x=1", result)

    def test_long_content_truncated(self):
        from tools.search import _MAX_CONTENT_CHARS
        html = f"<body>{'字' * (_MAX_CONTENT_CHARS + 1000)}</body>"
        result = self._fetch(html)
        self.assertIn("[内容过长已截断]", result)
        self.assertLessEqual(len(result), _MAX_CONTENT_CHARS + len("[内容过长已截断]") + 2)


class TestSearchWeb(unittest.TestCase):
    """search_web 工具：未配置降级 + Tavily 结果格式化。"""

    def setUp(self):
        # 保存并在测试后恢复真实环境变量，避免污染
        self._saved = {
            k: os.environ.get(k)
            for k in ("TAVILY_API_KEY", "WEBSEARCH_PROVIDER")
        }
        os.environ["WEBSEARCH_PROVIDER"] = "tavily"
        os.environ.pop("TAVILY_API_KEY", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _search(self, query: str) -> str:
        from tools.search import search_web
        return asyncio.run(search_web.ainvoke({"query": query}))

    def test_missing_key_returns_actionable_message(self):
        result = self._search("中科大新闻")
        self.assertIn("联网搜索未配置", result)
        self.assertIn("TAVILY_API_KEY", result)

    def test_tavily_results_formatted(self):
        from tools import search
        payload = {
            "results": [
                {"title": "结果一", "url": "https://a.example.com", "content": "摘要一"},
                {"title": "结果二", "url": "https://b.example.com", "content": "摘要二"},
            ]
        }
        captured = {}

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return _FakeRespJson(payload)

        class _FakeRespJson(_FakeResponse):
            def json(self):
                return payload

        os.environ["TAVILY_API_KEY"] = "tvly-test-key"
        with patch.object(search.httpx, "AsyncClient", _FakeAsyncClient):
            result = self._search("中科大新闻")

        self.assertIn("1. 结果一", result)
        self.assertIn("https://a.example.com", result)
        self.assertIn("摘要二", result)
        # Bearer 认证头必须携带
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tvly-test-key")
        self.assertEqual(captured["json"]["query"], "中科大新闻")

    def test_tavily_empty_results(self):
        from tools import search

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                class _Resp(_FakeResponse):
                    def json(self):
                        return {"results": []}
                return _Resp("")

        os.environ["TAVILY_API_KEY"] = "tvly-test-key"
        with patch.object(search.httpx, "AsyncClient", _FakeAsyncClient):
            result = self._search("无结果查询")
        self.assertIn("未找到相关搜索结果", result)


class TestToolRegistration(unittest.TestCase):
    """main.py 中工具注册与元数据契约。"""

    def test_tool_metadata_matches_registered_tools(self):
        from main import TOOL_METADATA, _shared_tools
        meta_names = {m["name"] for m in TOOL_METADATA}
        self.assertIn("web_search", meta_names)
        self.assertIn("fetch_url", meta_names)
        self.assertIn("web_search", _shared_tools)
        self.assertIn("fetch_url", _shared_tools)

    def test_shared_tool_names(self):
        from main import _shared_tools
        # LangChain 工具的实际注册名必须与偏好存储的名称一致
        self.assertEqual(_shared_tools["web_search"].name, "web_search")
        self.assertEqual(_shared_tools["fetch_url"].name, "fetch_url")


if __name__ == "__main__":
    unittest.main()
