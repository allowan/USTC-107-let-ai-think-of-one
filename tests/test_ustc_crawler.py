import unittest

from tools.ustc_crawler import (
    article_id,
    column_page_urls,
    discover_total_pages,
    extract_article_links,
)


class USTCCrawlerTest(unittest.TestCase):
    def test_extracts_current_and_legacy_article_links(self):
        page = """
        <a href="../info/1366/25592.htm" title="班车通知">班车</a>
        <a href="../tzggcontent.jsp?wbnewsid=25568" title="消杀通知">消杀</a>
        <a href="../index.htm" title="首页">首页</a>
        """
        links = extract_article_links(page, "https://www.ustc.edu.cn/tzgg/fwltz.htm")
        self.assertEqual(len(links), 2)
        self.assertEqual(article_id(links[0]["url"]), "1366_25592")
        self.assertEqual(article_id(links[1]["url"]), "legacy_25568")

    def test_deduplicates_article_urls(self):
        anchor = '<a href="../info/1366/25592.htm" title="班车通知">班车</a>'
        links = extract_article_links(anchor + anchor, "https://www.ustc.edu.cn/tzgg/fwltz.htm")
        self.assertEqual(len(links), 1)

    def test_discovers_visual_sitebuilder_page_count(self):
        self.assertEqual(discover_total_pages('<span class="p_t">1/27</span>'), 27)
        self.assertEqual(discover_total_pages("no pagination"), 1)

    def test_builds_descending_visual_sitebuilder_page_urls(self):
        urls = column_page_urls(
            "https://www.ustc.edu.cn/tzgg/fwltz.htm", max_pages=3, total_pages=27
        )
        self.assertEqual(
            urls,
            [
                "https://www.ustc.edu.cn/tzgg/fwltz.htm",
                "https://www.ustc.edu.cn/tzgg/fwltz/26.htm",
                "https://www.ustc.edu.cn/tzgg/fwltz/25.htm",
            ],
        )


if __name__ == "__main__":
    unittest.main()
