"""campus_rag 全功能测试

覆盖模块：auth, data_loader, keyword_retriever, index_manager,
         ingest, query, query_engine

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


# ── Auth ─────────────────────────────────────────────────────────────


class TestAuth(unittest.TestCase):
    """认证模块：注册、登录、用户列表。"""

    @classmethod
    def setUpClass(cls):
        from campus_rag import auth as auth_module
        cls.auth = auth_module
        cls.test_user = "test_auth_runner"
        cls.test_pass = "test1234"

    @classmethod
    def tearDownClass(cls):
        db = cls.auth.SessionLocal()
        user = db.query(cls.auth.User).filter_by(username=cls.test_user).first()
        if user:
            db.delete(user)
            db.commit()
        db.close()

    def test_01_default_admin_exists(self):
        ok, is_admin = self.auth.authenticate("admin", "admin123")
        self.assertTrue(ok, "默认管理员应能登录")
        self.assertTrue(is_admin, "admin 应为管理员")

    def test_02_register_new_user(self):
        ok = self.auth.register_user(self.test_user, self.test_pass)
        self.assertTrue(ok, "注册新用户应成功")

    def test_03_register_duplicate_fails(self):
        ok = self.auth.register_user(self.test_user, "other")
        self.assertFalse(ok, "重复注册应失败")

    def test_04_authenticate_success(self):
        ok, is_admin = self.auth.authenticate(self.test_user, self.test_pass)
        self.assertTrue(ok, "正确密码应登录成功")
        self.assertFalse(is_admin, "新用户不应是管理员")

    def test_05_authenticate_wrong_password(self):
        ok, _ = self.auth.authenticate(self.test_user, "wrong")
        self.assertFalse(ok, "错误密码应登录失败")

    def test_06_authenticate_nonexistent(self):
        ok, _ = self.auth.authenticate("nonexistent_user", "x")
        self.assertFalse(ok, "不存在的用户应登录失败")

    def test_07_list_users(self):
        users = self.auth.list_users()
        self.assertIsInstance(users, list)
        usernames = [u[0] for u in users]
        self.assertIn("admin", usernames, "列表中应包含 admin")
        self.assertIn(self.test_user, usernames, "列表中应包含测试用户")


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
        results = bm25.retrieve("暑假有什么活动", top_k=3)
        self.assertGreater(len(results), 0, "应能检索到结果")
        # 第一条应最相关（暑期学校）
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

    def test_06_get_combined_query_engine(self):
        pub, user = self.rag.get_combined_query_engine(self.TEST_USER)
        self.assertIsNotNone(pub)
        self.assertIsNotNone(user)

    def test_07_clear_user_index(self):
        self.rag.clear_user_index(self.TEST_USER)
        from llama_index.core import Document
        doc = Document(text="重新添加。", metadata={"source": "after_clear"})
        idx = self.rag.add_user_documents(self.TEST_USER, [doc])
        self.assertIsNotNone(idx)


# ── ingest ───────────────────────────────────────────────────────────


class TestIngest(unittest.TestCase):
    """动态入库（不依赖 embedding 的部分单独测；依赖的在后面）。"""

    TEST_USER = "test_ingest_runner"

    @classmethod
    def tearDownClass(cls):
        try:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(cls.TEST_USER)
        except Exception:
            pass

    def test_01_add_public_without_admin_fails(self):
        from campus_rag import add_public_activity
        with self.assertRaises(PermissionError):
            add_public_activity("未授权的通知", admin_check=False)

    def test_02_add_user_files_not_exist(self):
        from campus_rag.ingest import add_user_files
        with self.assertRaises(FileNotFoundError):
            add_user_files(self.TEST_USER, "/nonexistent/path/file.txt")

    def test_03_add_user_files_non_txt(self):
        from campus_rag.ingest import add_user_files
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
class TestIngestWithEmbedding(unittest.TestCase):
    """入库 + 检索联动测试（需要 embedding）。"""

    TEST_USER = "test_ingest_embed_runner"

    @classmethod
    def tearDownClass(cls):
        try:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(cls.TEST_USER)
        except Exception:
            pass

    def test_01_add_user_activity_and_retrieve(self):
        from campus_rag import add_user_activity, search_user_data
        add_user_activity(self.TEST_USER, "【算法竞赛】7月15日将在线上举办编程比赛，欢迎参加。")
        result = search_user_data("编程比赛", user_id=self.TEST_USER)
        self.assertIsInstance(result, str)
        self.assertNotIn("未在个人数据中找到", result, "应能检索到刚入库的内容")

    def test_02_add_user_files_from_dir(self):
        from campus_rag.ingest import add_user_files
        from campus_rag import search_user_data
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
        from campus_rag.ingest import add_user_files
        from campus_rag import search_user_data
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
    """检索接口：search_notices / search_user_data / search_all。"""

    def test_01_search_notices_returns_string(self):
        from campus_rag import search_notices
        result = search_notices("暑假有什么活动")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_02_search_notices_finds_content(self):
        from campus_rag import search_notices
        result = search_notices("C9暑期学校")
        self.assertIn("暑期", result, "应能搜到 C9 暑期学校相关通知")

    def test_03_search_notices_no_match(self):
        from campus_rag import search_notices
        result = search_notices("火星移民计划")
        self.assertIsInstance(result, str)
        # 向量检索始终返回最近似的 top_k 条结果，不会返回空列表，
        # 这里只验证返回格式正确且不含无意义的空内容
        self.assertNotIn("来源: 未知来源", result, "每条结果应有明确的来源文件名")

    def test_04_search_all_returns_labeled(self):
        from campus_rag import search_all
        result = search_all("比赛", user_id="test_query_runner")
        self.assertIsInstance(result, str)
        # 至少应有官方通知的结果
        self.assertIn("官方通知", result)

    def test_05_search_user_data_empty(self):
        from campus_rag import search_user_data
        result = search_user_data("什么数据", user_id="test_query_empty_user")
        self.assertIn("未在个人数据中找到", result)

    def test_06_search_user_data_with_content(self):
        from campus_rag import add_user_data, search_user_data
        from llama_index.core import Document
        uid = "test_query_user"
        doc = Document(text="Python高级编程技巧：装饰器与元类详解。")
        add_user_data(uid, [doc])
        try:
            result = search_user_data("Python装饰器", user_id=uid)
            self.assertIn("Python", result)
        finally:
            from campus_rag.index_manager import RAGSystem
            RAGSystem().clear_user_index(uid)


# ── query_engine ─────────────────────────────────────────────────────


class TestRerankNodes(unittest.TestCase):
    """重排序（需要 reranker 模型，首次运行会下载）。"""

    def test_rerank_sorts_by_relevance(self):
        from campus_rag.query_engine import rerank_nodes, _reranker_available
        from llama_index.core.schema import NodeWithScore, TextNode

        nodes = [
            NodeWithScore(node=TextNode(text="苹果是一种常见的水果。"), score=0.5),
            NodeWithScore(node=TextNode(text="深度学习使用反向传播算法。"), score=0.5),
            NodeWithScore(node=TextNode(text="机器学习是人工智能的分支。"), score=0.5),
        ]
        reranked = rerank_nodes("神经网络训练方法", nodes, top_n=2)
        self.assertEqual(len(reranked), 2, "应返回 top_n 条结果")
        if _reranker_available:
            self.assertIn("反向传播", reranked[0].node.text,
                          "机器学习相关节点应排在最前")

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

    def test_02_get_rag_response_hybrid(self):
        from campus_rag import RAGSystem, get_rag_response_hybrid
        rag = RAGSystem(persist_dir=self.CHROMA_DIR)
        pub_idx = rag.get_public_index()
        answer = get_rag_response_hybrid("比赛", pub_idx, data_dir=self.DATA_DIR)
        self.assertIsInstance(answer, str)
        self.assertTrue(len(answer) > 0)

    def test_03_no_match_graceful(self):
        from campus_rag import RAGSystem, get_rag_response
        rag = RAGSystem(persist_dir=self.CHROMA_DIR)
        pub_idx = rag.get_public_index()
        answer = get_rag_response("火星移民计划详细方案", pub_idx)
        self.assertIsInstance(answer, str)
        # 理应回复"未找到"或说明信息不足
        self.assertTrue(
            "未找" in answer or "不足" in answer or "没有" in answer or "无法" in answer,
            f"无匹配时应诚实回复，实际返回: {answer[:100]}",
        )


# ── 公开 API 完整性 ──────────────────────────────────────────────────


class TestPublicAPI(unittest.TestCase):
    """验证 __init__.py 导出的公开接口都可用。"""

    def test_all_exports_importable(self):
        from campus_rag import (
            search_notices,
            search_user_data,
            search_all,
            add_user_data,
            add_user_files,
            authenticate,
            register_user,
            list_users,
            add_public_activity,
            add_user_activity,
            get_rag_response,
            get_rag_response_hybrid,
            rerank_nodes,
            RAGSystem,
        )
        self.assertTrue(callable(search_notices))
        self.assertTrue(callable(search_user_data))
        self.assertTrue(callable(search_all))
        self.assertTrue(callable(add_user_data))
        self.assertTrue(callable(add_user_files))
        self.assertTrue(callable(authenticate))
        self.assertTrue(callable(register_user))
        self.assertTrue(callable(list_users))
        self.assertTrue(callable(add_public_activity))
        self.assertTrue(callable(add_user_activity))
        self.assertTrue(callable(get_rag_response))
        self.assertTrue(callable(get_rag_response_hybrid))
        self.assertTrue(callable(rerank_nodes))
        self.assertIsNotNone(RAGSystem)


# ── main ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=" * 60)
    print("campus_rag 全功能测试")
    print("=" * 60)
    if has_embedding():
        print("[OK] Embedding 服务可用 → 将运行全部测试")
    else:
        print(f"[SKIP] Embedding 服务不可用 → {_last_embed_error}")
        print("       请确认: 1) Ollama 已启动  2) nomic-embed-text 已拉取")
    if has_llm():
        print("[OK] LLM 服务可用 → 将运行 LLM 生成测试")
    else:
        print(f"[SKIP] LLM 服务不可用 → {_last_llm_error}")
        print("       请确认: 1) Ollama 已启动  2) llama3.1:8b 已拉取")
    print("=" * 60)
    print()
    unittest.main(verbosity=2)
