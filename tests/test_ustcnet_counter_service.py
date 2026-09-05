"""Tests for the USTC Network Information Center counter-service document."""

import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "campus_rag" / "data"
DOCUMENT = DATA_DIR / "40939_中国科大网络信息中心柜面服务.txt"


def embedding_available() -> bool:
    try:
        from campus_rag.llm_factory import get_embed_model

        get_embed_model().get_text_embedding("ping")
        return True
    except Exception:
        return False


class TestCounterServiceDocument(unittest.TestCase):
    def test_document_contains_source_and_service_facts(self):
        text = DOCUMENT.read_text(encoding="utf-8")
        self.assertIn("https://ustcnet.ustc.edu.cn/40939/list.htm", text)
        self.assertIn("东区师生活动中心北一楼", text)
        self.assertIn("西区教三楼一楼B区", text)
        self.assertIn("高新区师生活动中心107", text)
        self.assertIn("63600800", text)

    def test_bm25_retrieves_counter_service_document(self):
        from campus_rag.keyword_retriever import BM25Retriever

        results = BM25Retriever(str(DATA_DIR)).retrieve("高新区柜面服务地址", top_k=3)
        self.assertTrue(results)
        self.assertIn("高新区师生活动中心107", results[0].node.text)

    @unittest.skipUnless(embedding_available(), "需要 Embedding 服务")
    def test_vector_retrieval_finds_west_campus_hours(self):
        from campus_rag.index_manager import RAGSystem

        # ChromaDB 的 PersistentClient 不释放文件句柄，Windows 上临时目录清理
        # 必然报 PermissionError；若断言写在 with 之外，清理失败会让断言根本
        # 不执行（测试假红，检索结果实际没被验证）。故断言必须在块内，
        # 并容忍 Windows 的清理失败（pytest 的 tmp_path 同样策略）。
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_root:
            root = Path(temp_root)
            fixture_dir = root / "data"
            fixture_dir.mkdir()
            (fixture_dir / DOCUMENT.name).write_text(
                DOCUMENT.read_text(encoding="utf-8"), encoding="utf-8"
            )
            rag = RAGSystem(persist_dir=str(root / "chroma"))
            index = rag.create_public_index(str(fixture_dir))
            results = index.as_retriever(similarity_top_k=3).retrieve("西区周末能办理业务吗")

            self.assertTrue(results)
            combined = "\n".join(node.get_content() for node in results)
            self.assertIn("周末、法定节日休息", combined)


if __name__ == "__main__":
    unittest.main()
