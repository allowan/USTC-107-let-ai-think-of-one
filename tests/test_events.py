"""campus_rag.events 守护测试：确定性日期抽取 + 时间索引 + Agent 工具。

重点守护对抗性审查中修复的三类假阳性：
- 中文子串误命中（"上报" in "水上报告厅"）
- 无发布日时把过去日期捏造成未来截止
- 跨句关键词与日期误配
"""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from llama_index.core import Document

from campus_rag import events


def _mk_event(source: str, deadline: str | None, category: str = "报名",
              title: str | None = None, deadline_text: str | None = None,
              url: str | None = None) -> dict:
    return {
        "source": source,
        "source_hash": f"hash-{source}-{deadline}",
        "title": title or f"通知-{source}",
        "category": category,
        "audience": None,
        "publish_date": None,
        "deadline": deadline,
        "deadline_text": deadline_text,
        "url": url,
    }


class ParseDateTest(unittest.TestCase):
    """日期解析与年份推断。"""

    def test_full_chinese_date_deadline(self):
        text = "标题：中期检查\n本次中期检查截止期为 2026年6月12日 ，请完成。\n教务处\n2026年5月29日"
        r = events.parse_notice(text, "1.txt", today=date(2026, 5, 1))
        self.assertEqual(r["deadline"], "2026-06-12")
        self.assertEqual(r["publish_date"], "2026-05-29")

    def test_numeric_publish_date(self):
        text = "标题：助教\n报名截止时间：2026.9.4\n教务处\n2026.7.13"
        r = events.parse_notice(text, "2.txt", today=date(2026, 7, 1))
        self.assertEqual(r["publish_date"], "2026-07-13")
        self.assertEqual(r["deadline"], "2026-09-04")

    def test_yearless_bumps_only_with_publish_anchor(self):
        # 12 月发布、次年 1 月截止：有发布日 → 无年份日期跳到下一年
        text = "报名截止时间为 1月10日 。\n教务处\n2026年12月1日"
        r = events.parse_notice(text, "3.txt", today=date(2026, 12, 1))
        self.assertEqual(r["deadline"], "2027-01-10")

    def test_yearless_no_fabrication_without_publish(self):
        # 无发布日时绝不跳年：过去的 6月15日 不得被捏造成 2027
        text = "6月15日下午，某报告在东区水上报告厅举行。"
        r = events.parse_notice(text, "4.txt", today=date(2026, 9, 5))
        self.assertIsNone(r["publish_date"])
        self.assertIsNone(r["deadline"])

    def test_invalid_date_rejected(self):
        # 2 月 30 日非法，不得抛异常，应被忽略
        text = "报名截止时间为 2026年2月30日 。"
        r = events.parse_notice(text, "5.txt", today=date(2026, 1, 1))
        self.assertIsNone(r["deadline"])


class DeadlinePrecisionTest(unittest.TestCase):
    """对抗性审查修复的假阳性守护。"""

    def test_substring_keyword_not_matched(self):
        # "上报" 是 "水上报告厅" 的子串，且与日期同句，仍不得误判为截止
        text = "水上报告厅于6月15日举办讲座，欢迎参加。"
        r = events.parse_notice(text, "6.txt", today=date(2026, 6, 1))
        self.assertIsNone(r["deadline"])

    def test_past_news_event_not_deadline(self):
        text = (
            "标题：某领导讲授思政课\n"
            "6月15日下午，领导在东区水上报告厅为毕业生讲授思政课。\n"
            "课程围绕多个篇章展开。"
        )
        r = events.parse_notice(text, "7.txt", today=date(2026, 9, 5))
        self.assertIsNone(r["deadline"])

    def test_application_window_end_is_deadline(self):
        # 无"截止"二字的报名窗口，取范围结束日
        text = "助教申请时间：7月13日-9月4日\n任课老师审核录用截止时间：9月8日\n教务处\n2026.7.13"
        r = events.parse_notice(text, "8.txt", today=date(2026, 7, 13))
        # 主截止取锚点之后最近的一个 = 申请结束 9月4日（而非教师审核 9月8日）
        self.assertEqual(r["deadline"], "2026-09-04")

    def test_date_followed_by_before_marker(self):
        text = "补报名队伍于7月20日前扫描二维码报名。\n2026年7月14日"
        r = events.parse_notice(text, "9.txt", today=date(2026, 7, 1))
        self.assertEqual(r["deadline"], "2026-07-20")

    def test_expired_deadline_returns_none(self):
        # 候选为完整的过去日期（早于发布日）→ 已过期 → None（不捏造未来）
        text = "报名截止时间为 2026年3月1日 。\n教务处\n2026年6月1日"
        r = events.parse_notice(text, "10.txt", today=date(2026, 6, 1))
        self.assertIsNone(r["deadline"])


class ClassifyTest(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(events.parse_notice("标题：本科生选课通知", "a").get("category"), "选课")
        self.assertEqual(events.parse_notice("标题：开发大赛补报名", "b").get("category"), "竞赛")
        self.assertEqual(events.parse_notice("标题：助教岗位申请", "c").get("category"), "助教")
        self.assertEqual(events.parse_notice("标题：学术讲座通知", "d").get("category"), "讲座")
        self.assertEqual(events.parse_notice("标题：奖学金评审", "e").get("category"), "评奖")
        self.assertEqual(events.parse_notice("标题：食堂菜单", "f").get("category"), "其他")

    def test_title_and_url_extraction(self):
        text = "来源：https://www.teach.ustc.edu.cn/notice/20161.html\n标题：中期检查通知\n各学院：\n正文"
        r = events.parse_notice(text, "20161_x.txt")
        self.assertEqual(r["title"], "中期检查通知")
        self.assertEqual(r["url"], "https://www.teach.ustc.edu.cn/notice/20161.html")
        self.assertEqual(r["audience"], "各学院")

    def test_title_falls_back_to_filename(self):
        r = events.parse_notice("正文无标题行", "20425_选课通知.txt")
        self.assertEqual(r["title"], "选课通知")


class EventStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = events.EventStore(Path(self.tmp.name) / "events.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_is_idempotent_by_source(self):
        self.store.upsert_events([_mk_event("a.txt", "2026-09-10")])
        self.store.upsert_events([_mk_event("a.txt", "2026-09-10")])
        self.assertEqual(self.store.count(), 1)

    def test_upsert_updates_existing_source(self):
        self.store.upsert_events([_mk_event("a.txt", "2026-09-10")])
        self.store.upsert_events([_mk_event("a.txt", "2026-10-01")])
        rows = self.store.query_upcoming(days=400, today=date(2026, 9, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deadline"], "2026-10-01")

    def test_delete_by_source(self):
        self.store.upsert_events([_mk_event("a.txt", "2026-09-10"), _mk_event("b.txt", "2026-09-11")])
        self.assertEqual(self.store.delete_by_source("a.txt"), 1)
        self.assertEqual(self.store.count(), 1)

    def test_clear(self):
        self.store.upsert_events([_mk_event("a.txt", "2026-09-10")])
        self.store.clear()
        self.assertEqual(self.store.count(), 0)

    def test_query_upcoming_window_sort_and_filter(self):
        self.store.upsert_events([
            _mk_event("past.txt", "2026-09-04"),      # 早于 today，排除
            _mk_event("none.txt", None),               # 无截止，排除
            _mk_event("today.txt", "2026-09-05"),      # 边界：今天，含
            _mk_event("edge.txt", "2026-09-12"),       # 边界：today+7，含
            _mk_event("out.txt", "2026-09-13"),        # 超窗，排除
            _mk_event("mid.txt", "2026-09-08"),
        ])
        rows = self.store.query_upcoming(days=7, today=date(2026, 9, 5))
        self.assertEqual([r["source"] for r in rows], ["today.txt", "mid.txt", "edge.txt"])

    def test_query_upcoming_category_filter(self):
        self.store.upsert_events([
            _mk_event("a.txt", "2026-09-10", category="选课"),
            _mk_event("b.txt", "2026-09-11", category="竞赛"),
        ])
        rows = self.store.query_upcoming(days=30, category="竞赛", today=date(2026, 9, 1))
        self.assertEqual([r["source"] for r in rows], ["b.txt"])


class SyncFacadeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 替换门面单例，指向临时库，避免污染项目根 events.db
        self._patcher = patch.object(events, "_store", events.EventStore(Path(self.tmp.name) / "events.db"))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self.tmp.cleanup()

    def test_sync_skips_unchanged_by_hash(self):
        docs = [Document(text="报名截止时间为 2026年9月10日 。", metadata={"source": "a.txt"})]
        self.assertEqual(events.sync_events_from_documents(docs, today=date(2026, 9, 1)), 1)
        # 内容未变 → 哈希命中 → 跳过
        self.assertEqual(events.sync_events_from_documents(docs, today=date(2026, 9, 1)), 0)

    def test_sync_skips_docs_without_source_or_text(self):
        docs = [
            Document(text="报名截止 2026年9月10日", metadata={}),          # 无 source
            Document(text="   ", metadata={"source": "empty.txt"}),        # 空正文
        ]
        self.assertEqual(events.sync_events_from_documents(docs, today=date(2026, 9, 1)), 0)

    def test_sync_prefers_metadata_url(self):
        docs = [Document(
            text="来源：http://body.example/1\n报名截止 2026年9月10日",
            metadata={"source": "a.txt", "url": "http://meta.example/1"},
        )]
        events.sync_events_from_documents(docs, today=date(2026, 9, 1))
        rows = events.get_upcoming_events(days=30, today=date(2026, 9, 1))
        self.assertEqual(rows[0]["url"], "http://meta.example/1")

    def test_sync_tolerates_per_doc_failure(self):
        class _Bad:
            text = "报名截止 2026年9月10日"
            metadata = {"source": "bad.txt"}

            def __getattr__(self, name):  # 触发抽取内部异常
                raise RuntimeError("boom")

        good = Document(text="报名截止 2026年9月11日 。", metadata={"source": "good.txt"})
        # 坏文档不得中断整批
        n = events.sync_events_from_documents([_Bad(), good], today=date(2026, 9, 1))
        self.assertGreaterEqual(n, 1)

    def test_delete_and_clear_facade(self):
        docs = [Document(text="报名截止 2026年9月10日 。", metadata={"source": "a.txt"})]
        events.sync_events_from_documents(docs, today=date(2026, 9, 1))
        self.assertEqual(events.delete_events_by_source("a.txt"), 1)
        events.sync_events_from_documents(docs, today=date(2026, 9, 1))
        events.clear_events()
        self.assertEqual(events.get_event_store().count(), 0)

    def test_sync_notice_events_from_dir(self):
        # 启动入口：从指定目录加载种子语料并写入事件索引（无需嵌入）
        with tempfile.TemporaryDirectory() as src:
            (Path(src) / "n1.txt").write_text(
                "来源：http://x/1\n标题：夏令营报名\n"
                "报名截止时间为 2026年9月10日 。\n教务处\n2026年8月1日",
                encoding="utf-8",
            )
            n = events.sync_notice_events(data_dir=src, today=date(2026, 8, 1))
            self.assertEqual(n, 1)
            rows = events.get_upcoming_events(days=60, today=date(2026, 8, 1))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["deadline"], "2026-09-10")
            self.assertEqual(rows[0]["title"], "夏令营报名")


class ToolWrapperTest(unittest.TestCase):
    """main.get_upcoming_events 工具的格式化与参数传递。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._patcher = patch.object(events, "_store", events.EventStore(Path(self.tmp.name) / "events.db"))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self.tmp.cleanup()

    def _seed(self):
        events.get_event_store().upsert_events([
            _mk_event("a.txt", "2026-09-08", category="报名", title="夏令营报名",
                      deadline_text="报名截止 2026年9月8日", url="http://x/1"),
            _mk_event("b.txt", "2026-09-20", category="选课", title="秋季选课"),
        ])

    def test_tool_formats_remaining_days_and_order(self):
        import main
        self._seed()
        with patch("main.datetime") as fake_dt:
            fake_dt.now.return_value = datetime(2026, 9, 5)
            out = main.get_upcoming_events.invoke({"days": 30, "category": ""})
        self.assertIn("夏令营报名", out)
        self.assertIn("2026-09-08", out)
        self.assertIn("还剩 3 天", out)
        self.assertIn("http://x/1", out)
        # 按截止日升序：报名应在选课前
        self.assertLess(out.index("夏令营报名"), out.index("秋季选课"))

    def test_tool_empty_message(self):
        import main
        with patch("main.datetime") as fake_dt:
            fake_dt.now.return_value = datetime(2026, 9, 5)
            out = main.get_upcoming_events.invoke({"days": 7, "category": ""})
        self.assertIn("没有", out)

    def test_tool_passes_category(self):
        import main
        self._seed()
        with patch("main.datetime") as fake_dt:
            fake_dt.now.return_value = datetime(2026, 9, 5)
            out = main.get_upcoming_events.invoke({"days": 60, "category": "选课"})
        self.assertIn("秋季选课", out)
        self.assertNotIn("夏令营报名", out)


class RealCorpusRegressionTest(unittest.TestCase):
    """真实种子语料回归：守护 95379 新闻假阳性修复与 20406 申请窗口。"""

    def _read(self, prefix: str) -> str:
        data_dir = Path(events.__file__).resolve().parent / "data"
        for name in data_dir.iterdir():
            if name.name.startswith(prefix):
                return name.read_text(encoding="utf-8")
        self.skipTest(f"语料 {prefix} 不存在")

    def test_news_notice_has_no_deadline(self):
        r = events.parse_notice(self._read("95379"), "95379.txt", today=date(2026, 9, 5))
        self.assertIsNone(r["deadline"])

    def test_ta_notice_picks_application_deadline(self):
        r = events.parse_notice(self._read("20406"), "20406.txt", today=date(2026, 7, 13))
        self.assertEqual(r["deadline"], "2026-09-04")


if __name__ == "__main__":
    unittest.main()
