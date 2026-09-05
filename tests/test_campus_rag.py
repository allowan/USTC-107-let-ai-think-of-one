"""campus_rag 全功能测试

覆盖模块：auth, data_loader, keyword_retriever, index_manager,
         query, query_engine

用法：
    python test_campus_rag.py               # 运行全部测试
    python test_campus_rag.py -v            # 详细输出
    python test_campus_rag.py TestAuth      # 只运行某个测试类
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


# ── 辅助函数 ────────────────────────────────────────────────────────

_last_embed_error: str | None = None
_last_llm_error: str | None = None


def embedding_available() -> bool:
    """检查 embedding 模型是否可用（连接后尝试编码一条短文本）。"""
    global _last_embed_error
    try:
        from campus_rag.llm_factory import get_embed_model
        model = get_embed_model()
        model.get_text_embedding("ping")
        return True
    except Exception as e:
        _last_embed_error = f"{type(e).__name__}: {e}"
        return False


def llm_available() -> bool:
    """检查 LLM 是否可用。"""
    global _last_llm_error
    try:
        from campus_rag.llm_factory import get_llm
        llm = get_llm()
        llm.complete("ping")
        return True
    except Exception as e:
        _last_llm_error = f"{type(e).__name__}: {e}"
        return False


_EMBED_OK: bool | None = None
_LLM_OK: bool | None = None


def has_embedding() -> bool:
    global _EMBED_OK
    if _EMBED_OK is None:
        _EMBED_OK = embedding_available()
    return _EMBED_OK


def has_llm() -> bool:
    global _LLM_OK
    if _LLM_OK is None:
        _LLM_OK = llm_available()
    return _LLM_OK


# ── data_loader ──────────────────────────────────────────────────────


class TestDataLoader(unittest.TestCase):
    """文档加载与分块。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_txt(self, name: str, content: str):
        p = os.path.join(self.tmpdir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    def test_01_load_single_file(self):
        from campus_rag.data_loader import load_documents_from_files
        self._write_txt("a.txt", "Hello world.")
        docs = load_documents_from_files(self.tmpdir)
        self.assertEqual(len(docs), 1)
        self.assertIn("Hello world.", docs[0].text)
        self.assertEqual(docs[0].metadata["source"], "a.txt")

    def test_02_skip_non_txt(self):
        from campus_rag.data_loader import load_documents_from_files
        self._write_txt("a.txt", "Hello")
        with open(os.path.join(self.tmpdir, "b.md"), "w") as f:
            f.write("markdown")
        docs = load_documents_from_files(self.tmpdir)
        self.assertEqual(len(docs), 1)

    def test_03_skip_empty_file(self):
        from campus_rag.data_loader import load_documents_from_files
        self._write_txt("empty.txt", "   \n")
        docs = load_documents_from_files(self.tmpdir)
        self.assertEqual(len(docs), 0)

    def test_04_split_documents(self):
        from campus_rag.data_loader import load_documents_from_files, split_documents
        long_text = "测试文本。" * 500
        self._write_txt("long.txt", long_text)
        docs = load_documents_from_files(self.tmpdir)
        nodes = split_documents(docs)
        self.assertGreater(len(nodes), 1, "长文本应被拆分为多个节点")


# ── keyword_retriever ────────────────────────────────────────────────


class TestBM25Retriever(unittest.TestCase):
    """BM25 关键词检索（含中文分词）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._write_txt(
            "notice1.txt",
            "2026年暑期学校报名通知：南京大学将举办C9暑期学校，欢迎报名参加。",
        )
        self._write_txt(
            "notice2.txt",
            "关于举办智能体开发大赛的通知：一等奖金三万元，欢迎大家组队参赛。",
        )
        self._write_txt(
            "notice3.txt",
            "关于开展英才班本科生理实结合计划的通知：请各位同学关注。",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_txt(self, name: str, content: str):
        with open(os.path.join(self.tmpdir, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_01_retrieve_chinese(self):
        from campus_rag.keyword_retriever import BM25Retriever
        bm25 = BM25Retriever(self.tmpdir)
        results = bm25.retrieve("暑期学校报名", top_k=3)
        self.assertGreater(len(results), 0, "应能检索到结果")
        self.assertIn("暑期", results[0].node.text)

    def test_02_retrieve_competition(self):
        from campus_rag.keyword_retriever import BM25Retriever
        bm25 = BM25Retriever(self.tmpdir)
        results = bm25.retrieve("智能体比赛", top_k=3)
        self.assertGreater(len(results), 0)
        self.assertIn("智能体", results[0].node.text)

    def test_03_empty_query_graceful(self):
        from campus_rag.keyword_retriever import BM25Retriever
        bm25 = BM25Retriever(self.tmpdir)
        results = bm25.retrieve("", top_k=3)
        self.assertIsInstance(results, list)

    def test_04_empty_dir_graceful(self):
        from campus_rag.keyword_retriever import BM25Retriever
        empty_dir = tempfile.mkdtemp()
        try:
            bm25 = BM25Retriever(empty_dir)
            results = bm25.retrieve("测试", top_k=3)
            self.assertEqual(results, [])
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    def test_05_tokenize_fallback(self):
        """无 jieba 时回退到正则分词。"""
        from campus_rag.keyword_retriever import _tokenize
        with patch.dict(sys.modules, {"jieba": None}):
            tokens = _tokenize("2026年暑期学校")
            self.assertGreater(len(tokens), 1, "至少分成多个 token")


# ── index_manager ────────────────────────────────────────────────────


@unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
class TestRAGSystem(unittest.TestCase):
    """ChromaDB 索引管理。"""

    TEST_USER = "test_rag_runner"
    _RAG_BASE = Path(__file__).resolve().parent.parent / "campus_rag"

    @classmethod
    def setUpClass(cls):
        from campus_rag.index_manager import RAGSystem
        cls.rag = RAGSystem(persist_dir=str(cls._RAG_BASE / "chroma_db"))
        cls.data_dir = str(cls._RAG_BASE / "data")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.rag.clear_user_index(cls.TEST_USER)
        except Exception:
            pass

    def test_01_get_or_create_public_index(self):
        idx = self.rag.get_or_create_public_index(self.data_dir)
        self.assertIsNotNone(idx)

    def test_02_get_public_index(self):
        idx = self.rag.get_public_index()
        self.assertIsNotNone(idx)

    def test_03_get_or_create_user_index(self):
        idx = self.rag.get_or_create_user_index(self.TEST_USER)
        self.assertIsNotNone(idx)

    def test_04_get_user_index(self):
        idx = self.rag.get_user_index(self.TEST_USER)
        self.assertIsNotNone(idx)

    def test_05_add_user_documents(self):
        from llama_index.core import Document
        doc = Document(text="测试文档内容。", metadata={"source": "manual"})
        idx = self.rag.add_user_documents(self.TEST_USER, [doc])
        self.assertIsNotNone(idx)

    def test_06_clear_user_index(self):
        self.rag.clear_user_index(self.TEST_USER)
        from llama_index.core import Document
        doc = Document(text="重新添加。", metadata={"source": "after_clear"})
        idx = self.rag.add_user_documents(self.TEST_USER, [doc])
        self.assertIsNotNone(idx)


# ── ingest / data management ─────────────────────────────────────────


class TestDataManagement(unittest.TestCase):
    """数据入库（不依赖 embedding 的部分）。"""

    TEST_USER = "test_data_runner"

    @classmethod
    def tearDownClass(cls):
        try:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(cls.TEST_USER)
        except Exception:
            pass

    def test_01_add_user_files_not_exist(self):
        from campus_rag import add_user_files
        with self.assertRaises(FileNotFoundError):
            add_user_files(self.TEST_USER, "/nonexistent/path/file.txt")

    def test_02_add_user_files_non_txt(self):
        from campus_rag import add_user_files
        tmpdir = tempfile.mkdtemp()
        try:
            p = os.path.join(tmpdir, "test.md")
            with open(p, "w") as f:
                f.write("not txt")
            with self.assertRaises(ValueError):
                add_user_files(self.TEST_USER, p)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
    def test_03_add_user_data_and_list(self):
        from campus_rag import add_user_data, list_user_data
        from llama_index.core import Document
        uid = "test_list_user"
        doc = Document(text="算法竞赛 7月15日线上", metadata={"source": "竞赛提醒"})
        add_user_data(uid, [doc])
        try:
            result = list_user_data(uid)
            self.assertIn("documents", result)
            self.assertGreater(len(result.get("documents") or []), 0)
        finally:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(uid)

    @unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
    def test_04_delete_user_data(self):
        from campus_rag import add_user_data, delete_user_data, list_user_data
        from llama_index.core import Document
        uid = "test_delete_user"
        doc = Document(text="待删除的测试数据。", metadata={"source": "delete_test"})
        add_user_data(uid, [doc])
        count = delete_user_data(uid, "delete_test")
        self.assertGreater(count, 0, "应至少删除一条数据")
        result = list_user_data(uid)
        self.assertEqual(len(result.get("documents") or []), 0)


@unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
class TestDataManagementWithEmbedding(unittest.TestCase):
    """入库 + 检索联动测试（需要 embedding）。"""

    TEST_USER = "test_embed_runner"

    @classmethod
    def tearDownClass(cls):
        try:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(cls.TEST_USER)
        except Exception:
            pass

    def test_01_add_user_data_and_retrieve(self):
        from campus_rag import add_user_data, search_user_data
        from llama_index.core import Document
        doc = Document(
            text="【算法竞赛】7月15日将在线上举办编程比赛，欢迎参加。",
            metadata={"source": "竞赛通知"},
        )
        add_user_data(self.TEST_USER, [doc])
        result = search_user_data("编程比赛", user_id=self.TEST_USER)
        self.assertIsInstance(result, str)
        self.assertNotIn("未在个人数据中找到", result, "应能检索到刚入库的内容")

    def test_02_add_user_files_from_dir(self):
        from campus_rag import add_user_files, search_user_data
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "课表.txt"), "w", encoding="utf-8") as f:
                f.write("操作系统 周三3-4节 3A201\n数据库 周五1-2节 线上")
            count = add_user_files(self.TEST_USER, tmpdir)
            self.assertGreater(count, 0, "应导入至少 1 篇文档")
            result = search_user_data("操作系统", user_id=self.TEST_USER)
            self.assertIn("操作系统", result)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_03_add_user_files_single_file(self):
        from campus_rag import add_user_files, search_user_data
        tmpdir = tempfile.mkdtemp()
        try:
            fp = os.path.join(tmpdir, "笔记.txt")
            with open(fp, "w", encoding="utf-8") as f:
                f.write("深度学习入门笔记：反向传播算法推导。")
            count = add_user_files(self.TEST_USER, fp)
            self.assertEqual(count, 1)
            result = search_user_data("反向传播", user_id=self.TEST_USER)
            self.assertIn("反向传播", result)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── query ────────────────────────────────────────────────────────────


@unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
class TestQuery(unittest.TestCase):
    """检索接口：search_notices / search_user_data。"""

    def test_01_search_notices_returns_string(self):
        from campus_rag import search_notices
        result = search_notices("暑假有什么活动")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_02_search_notices_finds_content(self):
        from campus_rag import query as query_module
        from llama_index.core import Document

        source = "test_query_c9_fixture"
        query_module._ensure_init()
        query_module._rag.add_documents_to_public([
            Document(
                text="2026年暑期学校报名通知：南京大学将举办C9暑期学校，欢迎报名参加。",
                metadata={"source": source},
            )
        ])
        try:
            result = query_module.search_notices("C9暑期学校")
            self.assertIn("暑期", result, "应能搜到 C9 暑期学校相关通知")
        finally:
            query_module._rag.delete_public_documents_by_source(source)

    def test_03_search_notices_no_match_format(self):
        from campus_rag import search_notices
        result = search_notices("火星移民计划")
        self.assertIsInstance(result, str)
        self.assertNotIn("来源: 未知来源", result)

    def test_04_search_user_data_empty(self):
        from campus_rag import search_user_data
        result = search_user_data("什么数据", user_id="test_query_empty_user")
        self.assertIn("未在个人数据中找到", result)

    def test_05_search_user_data_with_content(self):
        from campus_rag import add_user_data, search_user_data
        from llama_index.core import Document
        uid = "test_query_user"
        doc = Document(text="Python高级编程技巧：装饰器与元类详解。", metadata={"source": "notes"})
        add_user_data(uid, [doc])
        try:
            result = search_user_data("Python装饰器", user_id=uid)
            self.assertIn("Python", result)
        finally:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(uid)


# ── query_engine ─────────────────────────────────────────────────────


class TestRerankNodes(unittest.TestCase):
    """重排序（API reranker，不可用时降级为原始分数排序）。"""

    def test_rerank_sorts_by_relevance(self):
        from campus_rag import query_engine
        from llama_index.core.schema import NodeWithScore, TextNode

        class _DeterministicReranker:
            @staticmethod
            def compute_score(pairs, normalize=True):
                self.assertEqual(len(pairs), 3)
                return [0.1, 0.9, 0.5]

        nodes = [
            NodeWithScore(node=TextNode(text="苹果是一种常见的水果。"), score=0.5),
            NodeWithScore(node=TextNode(text="深度学习使用反向传播算法。"), score=0.5),
            NodeWithScore(node=TextNode(text="机器学习是人工智能的分支。"), score=0.5),
        ]
        with patch.object(query_engine, "_get_reranker", return_value=_DeterministicReranker()):
            reranked = query_engine.rerank_nodes("神经网络训练方法", nodes, top_n=2)
        self.assertEqual(len(reranked), 2, "应返回 top_n 条结果")
        self.assertIn("反向传播", reranked[0].node.text,
                      "最高重排序分数的节点应排在最前")

    def test_rerank_empty_list(self):
        from campus_rag.query_engine import rerank_nodes
        self.assertEqual(rerank_nodes("test", []), [])


@unittest.skipUnless(has_embedding() and has_llm(),
                     "需要 Embedding 和 LLM 服务")
class TestQueryEngine(unittest.TestCase):
    """高级 RAG 管线：向量检索 + 重排序 + LLM 生成。"""

    _RAG_BASE = Path(__file__).resolve().parent.parent / "campus_rag"
    DATA_DIR = str(_RAG_BASE / "data")
    CHROMA_DIR = str(_RAG_BASE / "chroma_db")

    def test_01_get_rag_response(self):
        from campus_rag import RAGSystem, get_rag_response
        rag = RAGSystem(persist_dir=self.CHROMA_DIR)
        pub_idx = rag.get_public_index()
        answer = get_rag_response("今年暑假有什么活动", pub_idx)
        self.assertIsInstance(answer, str)
        self.assertTrue(len(answer) > 0, "应返回非空回答")
        # MockLLM 会原样回声 prompt；以下两句是 QA_PROMPT 原文，真实 LLM
        # 回答中不应出现（防止静默降级假通过）
        self.assertNotIn("如果资料不足以回答问题", answer,
                         "回答疑似 MockLLM 的 prompt 回声，而非真实 LLM 生成")
        self.assertNotIn("参考资料：", answer,
                         "回答疑似 MockLLM 的 prompt 回声，而非真实 LLM 生成")

    def test_02_no_match_graceful(self):
        from campus_rag import RAGSystem, get_rag_response
        rag = RAGSystem(persist_dir=self.CHROMA_DIR)
        pub_idx = rag.get_public_index()
        answer = get_rag_response("火星移民计划详细方案", pub_idx)
        self.assertIsInstance(answer, str)
        self.assertTrue(
            "未找" in answer or "不足" in answer or "没有" in answer or "无法" in answer,
            f"无匹配时应诚实回复，实际返回: {answer[:100]}",
        )
        # MockLLM 回声会包含 prompt 原文而同样命中上面的关键词，需额外拦截
        self.assertNotIn("如果资料不足以回答问题", answer,
                         "回答疑似 MockLLM 的 prompt 回声，而非真实 LLM 生成")
        self.assertNotIn("参考资料：", answer,
                         "回答疑似 MockLLM 的 prompt 回声，而非真实 LLM 生成")


class TestMockFallbackGuard(unittest.TestCase):
    """LLM/嵌入不可用时必须报错，禁止静默降级到 MockLLM/MockEmbedding。"""

    def test_require_llm_fails_fast_when_unavailable(self):
        from campus_rag import config
        # 模拟 LLM 初始化失败：require_llm 必须抛异常而非返回 MockLLM
        with patch.object(config, "init_llm", return_value=False):
            with self.assertRaises(RuntimeError):
                config.require_llm()

    def test_require_embed_fails_fast_when_unavailable(self):
        from campus_rag import config
        with patch.object(config, "init_embed", return_value=False):
            with self.assertRaises(RuntimeError):
                config.require_embed_model()

    def test_import_does_not_pollute_settings_with_mocks(self):
        # 导入后不应产生 MockLLM/MockEmbedding 全局污染：历史上
        # Settings.llm = None 会被 llama_index setter 立即 resolve 成 Mock
        # 对象，导致后续直接读 Settings.llm 的代码静默降级。用私有属性
        # _llm/_embed_model 检查：公开 getter 未初始化时会自动 resolve 出
        # Mock，无法区分"未初始化"和"已污染"。
        from llama_index.core import Settings
        from llama_index.core.llms.mock import MockLLM
        from llama_index.core.embeddings.mock_embed_model import MockEmbedding
        self.assertNotIsInstance(Settings._llm, MockLLM,
                                 "全局 Settings._llm 被 MockLLM 污染")
        self.assertNotIsInstance(Settings._embed_model, MockEmbedding,
                                 "全局 Settings._embed_model 被 MockEmbedding 污染")


# ── 维度一致性守卫 ──────────────────────────────────────────


@unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
class TestDimensionGuard(unittest.TestCase):
    """防止混用嵌入模型 / MockEmbedding 污染集合（维度不匹配守卫）。"""

    _RAG_BASE = Path(__file__).resolve().parent.parent / "campus_rag"

    @classmethod
    def setUpClass(cls):
        # _get_live_embed_dim 依赖全局 Settings.embed_model，需先初始化
        from campus_rag.config import init_embed
        if not init_embed():
            raise unittest.SkipTest("嵌入服务初始化失败")

    def setUp(self):
        import chromadb
        self.tmpdir = tempfile.mkdtemp()
        self.client = chromadb.PersistentClient(path=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_01_stored_dim_empty_and_nonempty(self):
        from campus_rag.index_manager import _stored_dim
        col = self.client.get_or_create_collection("dim_guard")
        self.assertIsNone(_stored_dim(col), "空集合应返回 None")
        col.add(ids=["a"], embeddings=[[0.5]], documents=["x"])
        self.assertEqual(_stored_dim(col), 1)

    def test_02_assert_raises_on_mock_pollution(self):
        # 模拟 MockEmbedding 污染：写入维度 1 的向量，与真实模型维度不符
        from campus_rag.index_manager import assert_collection_dim
        col = self.client.get_or_create_collection("polluted")
        col.add(ids=["m1"], embeddings=[[0.5]], documents=["mock"])
        with self.assertRaises(RuntimeError):
            assert_collection_dim(col)

    def test_03_assert_passes_when_matching(self):
        from campus_rag.index_manager import _get_live_embed_dim, assert_collection_dim
        col = self.client.get_or_create_collection("healthy")
        col.add(ids=["r1"], embeddings=[[0.1] * _get_live_embed_dim()], documents=["real"])
        assert_collection_dim(col)  # 维度一致时不应抛异常

    def test_04_public_preserved_on_mismatch(self):
        # 维度不匹配必须保留公共集合，远端专有文档未必能从本地恢复
        import chromadb
        from campus_rag import index_manager
        from campus_rag.index_manager import RAGSystem, _get_live_embed_dim, _stored_dim
        db_dir = os.path.join(self.tmpdir, "chroma_db")
        client = chromadb.PersistentClient(path=db_dir)
        col = client.get_or_create_collection("public")
        col.add(ids=["m1"], embeddings=[[0.5]], documents=["mock pollution"])
        old_client = index_manager._chroma_client
        old_client_path = index_manager._chroma_client_path
        try:
            # RAGSystem 的 chroma client 是模块级缓存，测试中临时指向临时库
            index_manager._chroma_client = client
            index_manager._chroma_client_path = str(Path(db_dir).resolve())
            rag = RAGSystem(persist_dir=db_dir)
            with self.assertRaises(RuntimeError):
                rag.get_or_create_public_index(data_dir=str(self._RAG_BASE / "data"))
            preserved = client.get_collection("public")
            self.assertEqual(preserved.get()["documents"], ["mock pollution"])
            self.assertEqual(_stored_dim(preserved), 1)
        finally:
            index_manager._chroma_client = old_client
            index_manager._chroma_client_path = old_client_path


# ── 写路径数据安全守卫 ──────────────────────────────────────────────────


@unittest.skipUnless(has_embedding(), "需要 Embedding 服务")
class TestDataSafetyGuard(unittest.TestCase):
    """先删后写的更新路径：嵌入不可用时必须拒绝且原数据不受影响。"""

    def setUp(self):
        import chromadb
        from campus_rag import index_manager
        self.tmpdir = tempfile.mkdtemp()
        self.client = chromadb.PersistentClient(path=self.tmpdir)
        self.old_client = index_manager._chroma_client
        self.old_client_path = index_manager._chroma_client_path
        self.old_default_persist_dir = index_manager._DEFAULT_PERSIST_DIR
        index_manager._chroma_client = self.client
        index_manager._chroma_client_path = str(Path(self.tmpdir).resolve())
        index_manager._DEFAULT_PERSIST_DIR = self.tmpdir

    def tearDown(self):
        from campus_rag import index_manager, reset_caches
        index_manager._chroma_client = self.old_client
        index_manager._chroma_client_path = self.old_client_path
        index_manager._DEFAULT_PERSIST_DIR = self.old_default_persist_dir
        reset_caches()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_user_data_rejected_when_embed_unavailable(self):
        from campus_rag import config, update_user_data
        with patch.object(config, "init_embed", return_value=False):
            with self.assertRaises(RuntimeError):
                update_user_data("safety_user", "课表", "新内容")

    def test_replace_public_documents_rejected_when_embed_unavailable(self):
        from campus_rag import config, replace_public_documents
        with patch.object(config, "init_embed", return_value=False):
            with self.assertRaises(RuntimeError):
                replace_public_documents([])

    def test_update_user_data_roundtrip(self):
        from campus_rag import add_user_data, delete_user_data, list_user_data, update_user_data
        from llama_index.core import Document
        user = "test_update_safety"
        try:
            add_user_data(user, [Document(text="旧课表内容", metadata={"source": "课表"})])
            update_user_data(user, "课表", "新课表内容已更新")
            data = list_user_data(user)
            joined = "\n".join(data.get("documents") or [])
            self.assertIn("新课表内容已更新", joined, "更新后应包含新内容")
            self.assertNotIn("旧课表内容", joined, "更新后旧内容应被删除")
        finally:
            delete_user_data(user, "课表")
            self.client.delete_collection(f"user_{user}")


# ── 工具偏好与 agent 配置 ─────────────────────────────────────────────


class TestToolPreferenceBehavior(unittest.TestCase):
    """显式禁用全部工具必须被尊重，不得静默回退全启用；
    偏好中未出现的新工具视为用户未表态，默认启用。"""

    def test_all_disabled_yields_empty_tool_list(self):
        from main import _build_tool_list
        tools = _build_tool_list("probe_user", tool_prefs={})
        self.assertEqual(tools, [], "用户显式禁用全部工具时应返回空列表")

    def test_none_means_default_all_enabled(self):
        from main import _build_tool_list
        tools = _build_tool_list("probe_user", tool_prefs=None)
        self.assertGreater(len(tools), 0, "未设置偏好时应默认启用全部工具")

    def test_prefs_only_apply_to_recorded_tools(self):
        # 旧偏好只覆盖保存时存在的工具；之后新增的工具（如 ustc_web_search）
        # 不在偏好字典中，必须默认启用而非被旧偏好静默禁用。
        from main import _build_tool_list
        tools = _build_tool_list("probe_user", tool_prefs={"web_search": True})
        names = {t.name for t in tools}
        self.assertIn("web_search", names)
        self.assertIn("ustc_web_search", names, "新增工具不在旧偏好中时应默认启用")
        # 显式禁用的工具必须被排除，无论新旧
        tools = _build_tool_list("probe_user", tool_prefs={"web_search": False})
        names = {t.name for t in tools}
        self.assertNotIn("web_search", names)
        self.assertIn("ustc_web_search", names)


# ── 同步服务配置 ────────────────────────────────────────────────────


class TestSyncConfig(unittest.TestCase):
    """SYNC_SERVER_URL 必须支持环境变量覆盖（部署位置可变）。"""

    def test_env_var_override(self):
        import importlib
        from server.services import sync_service
        old_url = sync_service.SYNC_SERVER_URL
        try:
            with patch.dict(os.environ, {"SYNC_SERVER_URL": "http://10.0.0.9:9999"}):
                importlib.reload(sync_service)
            self.assertEqual(sync_service.SYNC_SERVER_URL, "http://10.0.0.9:9999")
        finally:
            importlib.reload(sync_service)
            sync_service.SYNC_SERVER_URL = old_url


# ── 公开 API 完整性 ──────────────────────────────────────────────────


class TestPublicAPI(unittest.TestCase):
    """验证 __init__.py 导出的公开接口都可用。"""

    def test_all_exports_importable(self):
        from campus_rag import (
            search_notices,
            search_user_data,
            search_notices_answer,
            search_user_data_answer,
            add_user_data,
            add_user_files,
            list_user_data,
            delete_user_data,
            update_user_data,
            add_public_documents,
            delete_public_data,
            replace_public_documents,
            reset_caches,
            get_rag_response,
            rerank_nodes,
            RAGSystem,
        )
        self.assertTrue(callable(search_notices))
        self.assertTrue(callable(search_user_data))
        self.assertTrue(callable(search_notices_answer))
        self.assertTrue(callable(search_user_data_answer))
        self.assertTrue(callable(add_user_data))
        self.assertTrue(callable(add_user_files))
        self.assertTrue(callable(list_user_data))
        self.assertTrue(callable(delete_user_data))
        self.assertTrue(callable(update_user_data))
        self.assertTrue(callable(add_public_documents))
        self.assertTrue(callable(delete_public_data))
        self.assertTrue(callable(replace_public_documents))
        self.assertTrue(callable(reset_caches))
        self.assertTrue(callable(get_rag_response))
        self.assertTrue(callable(rerank_nodes))
        self.assertIsNotNone(RAGSystem)


# ── 可溯源：源网址提取与检索结果来源头 ──────────────────────────


class TestSourceUrlExtraction(unittest.TestCase):
    """源网址提取：仅按文件名通知 ID 匹配，宁缺毋错。"""

    def test_id_match(self):
        from campus_rag.data_loader import extract_source_url
        url = extract_source_url(
            "20455_实习管理通知.txt",
            "正文...详情见 https://www.teach.ustc.edu.cn/notice/notice-teaching/20455.html 。",
        )
        self.assertEqual(url, "https://www.teach.ustc.edu.cn/notice/notice-teaching/20455.html")

    def test_no_id_match_returns_none(self):
        # 正文链接不含通知 ID（如报名系统地址）时不得误报为源网址
        from campus_rag.data_loader import extract_source_url
        url = extract_source_url("20406_助教岗位通知.txt", "请到 https://tam.cmet.ustc.edu.cn 报名")
        self.assertIsNone(url)

    def test_non_numeric_filename(self):
        from campus_rag.data_loader import extract_source_url
        self.assertIsNone(extract_source_url("课表.txt", "https://x.ustc.edu.cn/123.html"))

    def test_trailing_punctuation_stripped(self):
        from campus_rag.data_loader import extract_source_url
        url = extract_source_url("3384_助教申报通知.txt", "（https://gradschool.ustc.edu.cn/article/3384）。")
        self.assertEqual(url, "https://gradschool.ustc.edu.cn/article/3384")

    def test_crawler_source_line(self):
        """爬虫文档（ustc_* 前缀，无数字 ID）从正文"来源："行提取源链接。"""
        from campus_rag.data_loader import extract_source_url_from_text
        text = (
            "标题：关于某某活动的通知\n"
            "来源：https://www.ustc.edu.cn/info/1366/25445.htm\n"
            "栏目：中国科大服务类通知\n\n正文..."
        )
        self.assertEqual(extract_source_url_from_text(text), "https://www.ustc.edu.cn/info/1366/25445.htm")
        self.assertIsNone(extract_source_url_from_text("正文里没有来源行"))
        # 行尾标点不粘连
        text2 = "来源：https://news.ustc.edu.cn/info/1055/95379.htm。"
        self.assertEqual(extract_source_url_from_text(text2), "https://news.ustc.edu.cn/info/1055/95379.htm")

    def test_crawler_doc_gets_url_metadata(self):
        """load_documents_from_files 必须给爬虫文档补上 url 元数据（回归守护）。"""
        import tempfile
        from campus_rag.data_loader import load_documents_from_files
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "ustc_service_notice_legacy_22309.txt").write_text(
                "标题：某通知\n来源：https://www.ustc.edu.cn/tzggcontent.jsp?urltype=news.NewsContentUrl&wbtreeid=1365&wbnewsid=22309\n\n正文",
                encoding="utf-8",
            )
            docs = load_documents_from_files(tmp)
        self.assertEqual(len(docs), 1)
        self.assertIn("url", docs[0].metadata)

    def test_real_data_files_carry_url_metadata(self):
        from campus_rag.data_loader import load_documents_from_files
        docs = load_documents_from_files(str(Path(__file__).resolve().parent.parent / "campus_rag" / "data"))
        self.assertGreater(len(docs), 0)
        with_url = [d for d in docs if d.metadata.get("url")]
        self.assertGreater(len(with_url), 0, "至少部分本地通知应提取到源网址")
        for d in with_url:
            notice_id = d.metadata["source"].split("_", 1)[0]
            # 数字 ID 前缀文件按 ID 匹配；爬虫文档（ustc_* 前缀）按正文"来源："行匹配
            if notice_id.isdigit():
                self.assertIn(notice_id, d.metadata["url"])


class _FakeNode:
    """模拟检索节点（_format_nodes 只需 metadata + get_content）。"""

    def __init__(self, metadata: dict, text: str):
        self.metadata = metadata
        self._text = text

    def get_content(self):
        return self._text


class _FakeNodeWithScore:
    """模拟 NodeWithScore（_node_context_block 只需 node.metadata + node.text）。"""

    def __init__(self, metadata: dict, text: str):
        from types import SimpleNamespace
        self.node = SimpleNamespace(metadata=metadata, text=text)


class TestRetrievalSourceHeaders(unittest.TestCase):
    """检索结果必须携带来源（文件名）与源链接，否则溯源无从谈起。"""

    def test_format_nodes_includes_source_and_url(self):
        from campus_rag.query import _format_nodes
        nodes = [_FakeNode({"source": "a.txt", "url": "https://x/1.html"}, "正文")]
        out = _format_nodes(nodes, "空")
        self.assertIn("[来源: a.txt]", out)
        self.assertIn("[源链接: https://x/1.html]", out)
        self.assertIn("正文", out)

    def test_format_nodes_without_url_keeps_source(self):
        from campus_rag.query import _format_nodes
        out = _format_nodes([_FakeNode({"source": "b.txt"}, "正文")], "空")
        self.assertIn("[来源: b.txt]", out)
        self.assertNotIn("源链接", out)

    def test_node_context_block_includes_url(self):
        from campus_rag.query_engine import _node_context_block
        block = _node_context_block(_FakeNodeWithScore({"source": "a.txt", "url": "https://x/1.html"}, "正文"))
        self.assertIn("[来源: a.txt] [源链接: https://x/1.html]", block)


# ── 路径锚定：默认向量库目录不得依赖启动 CWD ─────────────────


class TestDefaultPathAnchoring(unittest.TestCase):
    """默认数据/向量库路径必须是锚定项目根的绝对路径：
    相对路径依赖 CWD，从其他目录启动会在错误位置新建空库。"""

    def test_default_persist_dir_is_project_root_absolute(self):
        from campus_rag import index_manager
        expected = str(Path(__file__).resolve().parent.parent / "chroma_db")
        self.assertTrue(os.path.isabs(index_manager._DEFAULT_PERSIST_DIR))
        self.assertEqual(index_manager._DEFAULT_PERSIST_DIR, expected)

    def test_default_data_dir_is_package_absolute(self):
        from campus_rag import index_manager
        expected = str(Path(__file__).resolve().parent.parent / "campus_rag" / "data")
        self.assertTrue(os.path.isabs(index_manager._DEFAULT_DATA_DIR))
        self.assertEqual(index_manager._DEFAULT_DATA_DIR, expected)


class TestPublicReadSafety(unittest.TestCase):
    def test_missing_url_does_not_trigger_rebuild(self) -> None:
        from unittest.mock import Mock
        from campus_rag import index_manager

        rag = object.__new__(index_manager.RAGSystem)
        rag.chroma_client = Mock()
        with patch.object(index_manager, "assert_collection_dim"), \
             patch.object(index_manager, "ChromaVectorStore"), \
             patch.object(index_manager.VectorStoreIndex, "from_vector_store"):
            rag.get_or_create_public_index()
        rag.chroma_client.delete_collection.assert_not_called()


class TestChunkIndexAnnotation(unittest.TestCase):
    """split_documents 必须为每个分块打原文内序号，且不改变嵌入输入。"""

    def test_chunk_index_sequential_per_document(self):
        from llama_index.core import Document
        from campus_rag.data_loader import split_documents
        long_text = "这是第一句。" * 200  # 足以切成多个分块
        docs = [
            Document(text=long_text, metadata={"source": "a.txt"}),
            Document(text="短文档", metadata={"source": "b.txt"}),
        ]
        nodes = split_documents(docs)
        by_source: dict[str, list] = {}
        for n in nodes:
            by_source.setdefault(n.metadata["source"], []).append(n.metadata["chunk_index"])
        self.assertGreater(len(by_source["a.txt"]), 1, "长文档应产生多个分块")
        self.assertEqual(by_source["a.txt"], sorted(by_source["a.txt"]), "序号应从 0 递增")
        # 第二篇文档的序号必须独立从 0 开始，不得接着第一篇累加
        self.assertEqual(by_source["b.txt"], [0])

    def test_chunk_index_excluded_from_embedding(self):
        from llama_index.core import Document
        from campus_rag.data_loader import split_documents
        nodes = split_documents([Document(text="内容" * 300, metadata={"source": "a.txt"})])
        for n in nodes:
            self.assertIn("chunk_index", n.excluded_embed_metadata_keys,
                          "chunk_index 不得进入嵌入输入，否则改变向量内容")


# ── main ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=" * 60)
    print("campus_rag 全功能测试")
    print("=" * 60)
    if has_embedding():
        print("[OK] Embedding 服务可用 → 将运行全部测试")
    else:
        print(f"[SKIP] Embedding 服务不可用 → {_last_embed_error}")
        print("       请确认: campus_rag/.env 已配置 EMBED_* 且 API 可达")
    if has_llm():
        print("[OK] LLM 服务可用 → 将运行 LLM 生成测试")
    else:
        print(f"[SKIP] LLM 服务不可用 → {_last_llm_error}")
        print("       请确认: 1) settings.json 已配置")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)
