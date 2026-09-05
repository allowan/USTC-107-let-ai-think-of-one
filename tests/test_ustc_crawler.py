import unittest

from tools.ustc_crawler import (
    article_id,
    column_page_urls,
    discover_total_pages,
    extract_article_links,
    notice_filename,
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

    def test_extracts_teach_and_gradschool_links(self):
        # 教务处 <栏目>/<子栏目>/<id>.html；研究生院 /article/<id>
        page = """
        <a href="/notice/notice-teaching/20425.html" title="选课通知">选课</a>
        <a href="/article/3510">学期注册通知</a>
        <a href="/category/notice/notice-teaching" title="栏目页">栏目</a>
        <a href="/feedback" title="反馈">反馈</a>
        """
        teach = extract_article_links(page, "https://www.teach.ustc.edu.cn/category/notice/notice-teaching")
        grad = extract_article_links(page, "https://gradschool.ustc.edu.cn/column/9")
        self.assertEqual(len(teach), 2)
        self.assertEqual(len(grad), 2)
        self.assertEqual(article_id("https://www.teach.ustc.edu.cn/notice/notice-teaching/20425.html"), "20425")
        self.assertEqual(article_id("https://gradschool.ustc.edu.cn/article/3510"), "3510")

    def test_title_falls_back_to_link_text(self):
        # a 标签无 title 属性时用链接文本（研究生院栏目页的形态）
        links = extract_article_links(
            '<a href="/article/3511">学科交叉项目申报通知</a>',
            "https://gradschool.ustc.edu.cn/column/9",
        )
        self.assertEqual(links, [{"title": "学科交叉项目申报通知",
                                  "url": "https://gradschool.ustc.edu.cn/article/3511"}])

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

    def test_notice_filename_matches_seed_convention(self):
        """文件名 {通知ID}_{标题}.txt：ID 必须出现在源 URL 中，否则源链接提取失效。"""
        self.assertEqual(
            notice_filename("https://www.ustc.edu.cn/info/1366/25525.htm", "关于西校区英才路部分道路封闭施工的通知"),
            "25525_关于西校区英才路部分道路封闭施工的通知.txt",
        )
        self.assertEqual(
            notice_filename("https://www.teach.ustc.edu.cn/notice/notice-info/20429.html", "选课通知"),
            "20429_选课通知.txt",
        )
        # Windows 非法字符替换为下划线
        self.assertEqual(
            notice_filename("https://gradschool.ustc.edu.cn/article/3384", 'a/b:c?d"e'),
            "3384_a_b_c_d_e.txt",
        )
        # 哈希兜底 ID（无法解析文章号的 URL）加 x 前缀，避免数字前缀被误当通知 ID
        hashed = notice_filename("https://www.ustc.edu.cn/some/odd/path", "标题")
        self.assertTrue(hashed.startswith("x"))
        self.assertTrue(hashed.endswith("_标题.txt"))


if __name__ == "__main__":
    unittest.main()
