import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sync_web_sources import _safe_output_path
from tools.search import (
    _CourseReviewSearchParser,
    _DuckDuckGoParser,
    _format_markdown_link,
    _format_search_results,
    _validate_course_review_url,
    _validate_public_url,
    _validate_ustc_url,
    extract_page_text,
    load_course_review_sites,
    load_ustc_sites,
    search_course_reviews_text,
)


class WebSearchTest(unittest.TestCase):
    def test_extracts_article_text_and_ignores_navigation(self):
        page = """
        <html><body><nav>导航噪声</nav>
        <div class="wp_articlecontent"><p>西区服务地址</p><p>周末休息</p></div>
        <script>secret()</script></body></html>
        """
        text = extract_page_text(page)
        self.assertIn("西区服务地址", text)
        self.assertIn("周末休息", text)
        self.assertNotIn("导航噪声", text)
        self.assertNotIn("secret", text)

    def test_parses_search_result_redirect(self):
        parser = _DuckDuckGoParser()
        parser.feed(
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fustc.edu.cn%2Fnews">通知</a>'
        )
        self.assertEqual(parser.results[0]["title"], "通知")
        self.assertEqual(parser.results[0]["url"], "https://ustc.edu.cn/news")

    def test_formats_search_results_as_clickable_markdown_links(self):
        result = _format_search_results([
            {"title": "科大通知", "url": "https://ustc.edu.cn/news?id=1"},
        ])
        self.assertEqual(result, "1. [科大通知](https://ustc.edu.cn/news?id=1)")

    def test_escapes_markdown_label_and_closing_parenthesis(self):
        result = _format_markdown_link(
            "通知 [2026]", "https://example.com/article_(latest)"
        )
        self.assertEqual(
            result,
            r"[通知 \[2026\]](https://example.com/article_(latest%29)",
        )

    def test_fetch_tools_format_page_source_as_markdown(self):
        from tools.search import fetch_text_from_url, fetch_ustc_text_from_url

        with patch("tools.search.fetch_page_text", return_value="网页正文"):
            result = fetch_text_from_url.invoke({"url": "https://example.com/article"})
        self.assertIn("来源: [网页原文](https://example.com/article)", result)

        with patch("tools.search.fetch_ustc_page_text", return_value="科大正文"):
            result = fetch_ustc_text_from_url.invoke(
                {"url": "https://www.ustc.edu.cn/info/1366/25592.htm"}
            )
        self.assertIn(
            "来源: [网页原文](https://www.ustc.edu.cn/info/1366/25592.htm)",
            result,
        )

    def test_blocks_private_network(self):
        with patch("tools.search.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaisesRegex(ValueError, "私有或保留"):
                _validate_public_url("http://example.test/")

    def test_allows_ustc_fake_ip_used_by_local_proxy(self):
        fake_ip = [(2, 1, 6, "", ("198.18.0.156", 443))]
        with patch("tools.search.socket.getaddrinfo", return_value=fake_ip):
            self.assertEqual(
                _validate_public_url("https://ustcnet.ustc.edu.cn/40939/list.htm"),
                "https://ustcnet.ustc.edu.cn/40939/list.htm",
            )

    def test_allows_icourse_fake_ip_used_by_local_proxy(self):
        fake_ip = [(2, 1, 6, "", ("198.18.0.191", 443))]
        with patch("tools.search.socket.getaddrinfo", return_value=fake_ip):
            self.assertEqual(
                _validate_course_review_url("https://icourse.club/course/123/"),
                "https://icourse.club/course/123/",
            )

    def test_rejects_output_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "非法输出文件名"):
                _safe_output_path(Path(directory), "../outside.txt")

    def test_ustc_site_directory_contains_common_services(self):
        sites = load_ustc_sites()
        names = {site["name"] for site in sites}
        self.assertIn("本科生院教务处", names)
        self.assertIn("综合教务系统", names)
        self.assertIn("本科课程目录与公共查询", names)
        self.assertIn("研究生院", names)
        self.assertIn("就业信息网", names)
        self.assertIn("图书馆", names)

    def test_course_review_directory_contains_icourse(self):
        sites = load_course_review_sites()
        self.assertTrue(any(site["name"] == "USTC评课社区" for site in sites))

    def test_parses_icourse_site_search_results(self):
        parser = _CourseReviewSearchParser()
        parser.feed('<a class="px16" href="/course/123/">数据结构（教师）</a>')
        self.assertEqual(
            parser.results,
            [{"title": "数据结构（教师）", "url": "https://icourse.club/course/123/"}],
        )

    def test_course_review_search_filters_to_course_pages(self):
        with patch(
            "tools.search._search_course_review_site_results",
            return_value=[
                {"title": "课程评价", "url": "https://icourse.club/course/123/"},
                {"title": "课程附件", "url": "https://icourse.club/uploads/course.pdf"},
                {"title": "其他站点", "url": "https://example.com/course/123/"},
            ],
        ):
            result = search_course_reviews_text("数据结构")
        self.assertIn("[课程评价](https://icourse.club/course/123/)", result)
        self.assertNotIn("课程附件", result)
        self.assertNotIn("其他站点", result)

    def test_course_review_fetch_rejects_non_course_page(self):
        public_ip = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with patch("tools.search.socket.getaddrinfo", return_value=public_ip):
            with self.assertRaisesRegex(ValueError, "只允许读取课程详情页面"):
                _validate_course_review_url("https://icourse.club/")

    def test_ustc_fetch_rejects_non_whitelisted_host(self):
        public_ip = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with patch("tools.search.socket.getaddrinfo", return_value=public_ip):
            with self.assertRaisesRegex(ValueError, "不在中国科大"):
                _validate_ustc_url("https://example.com/")


class WebSearchProviderTest(unittest.TestCase):
    """web_search 的 provider 选择：Tavily 主 + DuckDuckGo 兜底。"""

    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in ("TAVILY_API_KEY", "WEBSEARCH_PROVIDER")
        }

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_tavily_results_formatted_as_markdown_links(self):
        from tools import search
        payload = {
            "results": [
                {"title": "结果一", "url": "https://a.example.com", "content": "摘要一"},
                {"title": "结果二", "url": "https://b.example.com", "content": "摘要二"},
            ]
        }
        captured = {}

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse()

        os.environ["WEBSEARCH_PROVIDER"] = "tavily"
        os.environ["TAVILY_API_KEY"] = "tvly-test-key"
        with patch.object(search.httpx, "post", side_effect=fake_post):
            result = search.search_web.invoke({"query": "中科大新闻"})
        self.assertIn("1. [结果一](https://a.example.com)", result)
        self.assertIn("2. [结果二](https://b.example.com)", result)
        # Bearer 认证头必须携带，请求必须打到 Tavily 端点
        self.assertEqual(captured["headers"]["Authorization"], "Bearer tvly-test-key")
        self.assertEqual(captured["url"], search.TAVILY_ENDPOINT)
        self.assertEqual(captured["json"]["query"], "中科大新闻")

    def test_missing_tavily_key_falls_back_to_ddg(self):
        from tools import search
        os.environ["WEBSEARCH_PROVIDER"] = "tavily"
        os.environ.pop("TAVILY_API_KEY", None)
        with patch.object(search, "search_web_text", return_value="兜底结果") as ddg:
            result = search.search_web.invoke({"query": "任意查询"})
        self.assertEqual(result, "兜底结果")
        ddg.assert_called_once_with("任意查询")

    def test_ddg_provider_skips_tavily(self):
        from tools import search
        os.environ["WEBSEARCH_PROVIDER"] = "ddg"
        os.environ["TAVILY_API_KEY"] = "tvly-test-key"
        with patch.object(search, "_search_tavily_results") as tavily:
            with patch.object(search, "search_web_text", return_value="ddg 结果"):
                result = search.search_web.invoke({"query": "任意查询"})
        self.assertEqual(result, "ddg 结果")
        tavily.assert_not_called()


class ToolRegistrationTest(unittest.TestCase):
    """main.py 中工具注册与元数据契约。"""

    def test_tool_metadata_matches_registered_tools(self):
        from main import TOOL_METADATA, _shared_tools
        meta_names = {m["name"] for m in TOOL_METADATA}
        for name in _shared_tools:
            self.assertIn(name, meta_names, f"共享工具 {name} 缺少 TOOL_METADATA 条目")

    def test_shared_tool_names(self):
        from main import _shared_tools
        # LangChain 工具的实际注册名必须与偏好存储的名称一致
        for name, tool in _shared_tools.items():
            self.assertEqual(tool.name, name)


if __name__ == "__main__":
    unittest.main()
