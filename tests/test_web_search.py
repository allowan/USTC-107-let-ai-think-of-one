import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sync_web_sources import _safe_output_path
from tools.search import (
    _DuckDuckGoParser,
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
