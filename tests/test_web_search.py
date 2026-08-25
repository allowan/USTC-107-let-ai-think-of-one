import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sync_web_sources import _safe_output_path
from tools.search import (
    _DuckDuckGoParser,
    _format_markdown_link,
    _format_search_results,
    _validate_public_url,
    _validate_ustc_url,
    extract_page_text,
    load_ustc_sites,
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

    def test_rejects_output_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "非法输出文件名"):
                _safe_output_path(Path(directory), "../outside.txt")

    def test_ustc_site_directory_contains_common_services(self):
        sites = load_ustc_sites()
        names = {site["name"] for site in sites}
        self.assertIn("本科生院教务处", names)
        self.assertIn("研究生院", names)
        self.assertIn("就业信息网", names)
        self.assertIn("图书馆", names)

    def test_ustc_fetch_rejects_non_whitelisted_host(self):
        public_ip = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with patch("tools.search.socket.getaddrinfo", return_value=public_ip):
            with self.assertRaisesRegex(ValueError, "不在中国科大"):
                _validate_ustc_url("https://example.com/")


if __name__ == "__main__":
    unittest.main()
