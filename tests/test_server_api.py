"""server 层契约测试

覆盖前后端数据传输边界：路由参数校验、路径编码往返、历史消息格式、
同步状态机、thread_id 契约。全部离线可运行（RAG 依赖用 stub 替代）。

用法：
    python -m pytest tests/test_server_api.py -v
"""

import asyncio
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


# ── 历史消息转换 ─────────────────────────────────────────────────────


class _FakeMsg:
    """模拟 LangChain 消息（只需 type / content 两个属性）。"""

    def __init__(self, mtype: str, content):
        self.type = mtype
        self.content = content


class TestHistoryTransform(unittest.TestCase):
    """get_history 的消息转换规则（空气泡过滤 + 连续 assistant 合并）。"""

    def _convert(self, msgs):
        from main import _checkpoint_messages_to_history
        return _checkpoint_messages_to_history(msgs)

    def test_empty_ai_messages_filtered(self):
        # 仅带 tool_calls 的 AI 消息 content 为空，不得传给前端渲染空气泡
        msgs = [
            _FakeMsg("human", "你好"),
            _FakeMsg("ai", ""),
            _FakeMsg("ai", "   "),
            _FakeMsg("ai", "你好！"),
        ]
        result = self._convert(msgs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["content"], "你好！")

    def test_tool_messages_excluded(self):
        msgs = [
            _FakeMsg("human", "查一下"),
            _FakeMsg("ai", ""),
            _FakeMsg("tool", "工具返回的原始内容"),
            _FakeMsg("ai", "结果如下"),
        ]
        result = self._convert(msgs)
        self.assertEqual([m["role"] for m in result], ["user", "assistant"])
        self.assertNotIn("工具返回", result[1]["content"])

    def test_consecutive_ai_merged(self):
        # 多跳推理产生多条连续 AI 消息，应合并为单条（与流式单气泡一致）
        msgs = [
            _FakeMsg("human", "问题"),
            _FakeMsg("ai", "我先检索一下"),
            _FakeMsg("ai", ""),
            _FakeMsg("ai", "最终答案"),
        ]
        result = self._convert(msgs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["content"], "我先检索一下\n\n最终答案")

    def test_non_string_content_coerced(self):
        msgs = [_FakeMsg("ai", [{"type": "text", "text": "多模态块"}])]
        result = self._convert(msgs)
        self.assertIsInstance(result[0]["content"], str)

    def test_user_messages_never_merged(self):
        msgs = [_FakeMsg("human", "a"), _FakeMsg("human", "b")]
        result = self._convert(msgs)
        self.assertEqual(len(result), 2)


# ── thread_id 契约 ───────────────────────────────────────────────────


class TestThreadIdContract(unittest.TestCase):
    """话题删除 / 历史加载 / 对话写入三处依赖同一 thread_id 格式，
    任一侧漂移都会导致历史丢失或删错 checkpoint。"""

    def test_all_producers_agree(self):
        from campus_rag import auth
        from server.services.chat_service import ChatService
        expected = "user-local_user-topic-abc123"
        self.assertEqual(auth._thread_id("local_user", "abc123"), expected)
        self.assertEqual(ChatService._thread_id("local_user", "abc123"), expected)


# ── 聊天路由参数校验 ─────────────────────────────────────────────────


class TestChatRouteValidation(unittest.TestCase):
    """/api/chat/stream 入参校验（不触碰真实 ChatService）。"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import server
        from server.services.chat_service import get_chat_service
        # 校验在 handler 中先于业务逻辑执行，但依赖注入仍会解析，用 stub 顶替
        server.app.dependency_overrides[get_chat_service] = lambda: object()
        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        import server
        server.app.dependency_overrides.clear()

    def test_empty_content_rejected(self):
        r = self.client.post("/api/chat/stream", json={"content": "  ", "topic_id": "t"})
        self.assertEqual(r.status_code, 400)

    def test_missing_content_rejected(self):
        r = self.client.post("/api/chat/stream", json={"topic_id": "t"})
        self.assertEqual(r.status_code, 400)

    def test_oversized_content_rejected(self):
        r = self.client.post("/api/chat/stream", json={"content": "x" * 10001})
        self.assertEqual(r.status_code, 400)


# ── 个人数据路由编码契约 ─────────────────────────────────────────────
#
# 注意：starlette TestClient 的路径解码行为与真实 uvicorn 不一致
# （已实测），编码往返必须对真实服务器验证，故此处起真实 uvicorn。


class _RecordingRAGStub:
    """记录收到的参数，供断言解码结果。"""

    def __init__(self):
        self.calls = []

    def list_user_data(self, user):
        return {"ids": [], "metadatas": [], "documents": [], "previews": []}

    def add_user_data(self, user, content, source):
        self.calls.append(("add", user, source, content))

    def update_user_data(self, user, source, content):
        self.calls.append(("update", user, source, content))

    def delete_user_data(self, user, source):
        self.calls.append(("delete", user, source))
        return 1


class TestPersonalDataEncoding(unittest.TestCase):
    """PUT/DELETE 路径参数的编码往返：前端 encodeURIComponent → FastAPI
    解码一次 → 路由层 unquote 一次，服务层收到的必须是原始字符串。"""

    PORT = 8791

    @classmethod
    def setUpClass(cls):
        import uvicorn
        import server
        from server.services.rag_service import get_rag_service

        cls.stub = _RecordingRAGStub()
        server.app.dependency_overrides[get_rag_service] = lambda: cls.stub

        config = uvicorn.Config(
            server.app, host="127.0.0.1", port=cls.PORT,
            log_level="warning", lifespan="off",  # 跳过 ChatService 初始化，路由依赖已 stub
        )
        cls.uvi = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.uvi.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.uvi.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("测试用服务器未能启动")

    @classmethod
    def tearDownClass(cls):
        import server
        cls.uvi.should_exit = True
        cls.thread.join(timeout=5)
        server.app.dependency_overrides.clear()

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.PORT}{path}", method=method, data=data)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode()

    def test_put_source_with_percent(self):
        source = "100%进度"
        encoded = urllib.parse.quote(source, safe="")
        status, _ = self._request("PUT", f"/api/personal-data/{encoded}", {"content": "新内容"})
        self.assertEqual(status, 200)
        self.assertEqual(self.stub.calls[-1], ("update", "local_user", source, "新内容"))

    def test_put_source_with_space(self):
        source = "我的 课表"
        encoded = urllib.parse.quote(source, safe="")
        status, _ = self._request("PUT", f"/api/personal-data/{encoded}", {"content": "内容"})
        self.assertEqual(status, 200)
        self.assertEqual(self.stub.calls[-1][2], source)

    def test_delete_source_literal_percent(self):
        # 字面含 % 的 source 是最容易双重解码出错的场景
        source = "a%20b"
        encoded = urllib.parse.quote(source, safe="")
        status, _ = self._request("DELETE", f"/api/personal-data/{encoded}")
        self.assertEqual(status, 200)
        self.assertEqual(self.stub.calls[-1], ("delete", "local_user", source))

    def test_post_empty_content_rejected(self):
        try:
            self._request("POST", "/api/personal-data", {"content": "   "})
            self.fail("空内容应返回 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


class _OutOfOrderRAGStub:
    """返回同一来源的多个分块且顺序打乱（模拟 ChromaDB 无序返回）。"""

    def list_user_data(self, user):
        return {
            "ids": ["c2", "c0", "c1"],
            "metadatas": [
                {"source": "长文档.txt", "chunk_index": 2},
                {"source": "长文档.txt", "chunk_index": 0},
                {"source": "长文档.txt", "chunk_index": 1},
            ],
            "documents": ["第三段", "第一段", "第二段"],
            "previews": ["第三段", "第一段", "第二段"],
        }


class TestPersonalDataAggregation(unittest.TestCase):
    """多分块文档按来源聚合必须按 chunk_index 还原，不得依赖存储返回序。"""

    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        from server.services.rag_service import get_rag_service
        server.app.dependency_overrides[get_rag_service] = lambda: _OutOfOrderRAGStub()
        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        import server
        server.app.dependency_overrides.clear()

    def test_chunks_reordered_by_chunk_index(self):
        r = self.client.get("/api/personal-data")
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["full_content"], "第一段\n第二段\n第三段")
        self.assertEqual(items[0]["chunks"], 3)


class _EmbedUnavailableRAGStub:
    """模拟 campus_rag fail-fast 守卫：嵌入不可用时抛 RuntimeError。"""

    def add_user_data(self, user, content, source):
        raise RuntimeError("嵌入服务不可用，已拒绝入库")

    def update_user_data(self, user, source, content):
        raise RuntimeError("嵌入服务不可用，已拒绝更新个人数据")


class TestPersonalDataEmbedUnavailable(unittest.TestCase):
    """嵌入不可用是服务不可用（503 + 可操作详情），不得与真实内部错误 500 混淆。"""

    @classmethod
    def setUpClass(cls):
        import server
        from fastapi.testclient import TestClient
        from server.services.rag_service import get_rag_service
        server.app.dependency_overrides[get_rag_service] = lambda: _EmbedUnavailableRAGStub()
        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        import server
        server.app.dependency_overrides.clear()

    def test_add_returns_503_with_detail(self):
        r = self.client.post("/api/personal-data", json={"content": "内容"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("嵌入服务不可用", r.json()["detail"])

    def test_update_returns_503_with_detail(self):
        r = self.client.put("/api/personal-data/课表", json={"content": "新内容"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("嵌入服务不可用", r.json()["detail"])


# ── 同步服务状态机 ───────────────────────────────────────────────────


class TestSyncServiceState(unittest.TestCase):
    """本地版本号持久化 + 离线时的错误语义。"""

    def test_local_version_roundtrip(self):
        from server.services import sync_service
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "sync_state.json"
            with patch.object(sync_service, "SYNC_STATE_PATH", state_path):
                self.assertEqual(sync_service.SyncService.get_local_version(), 0)
                sync_service.SyncService._set_local_version(7)
                self.assertEqual(sync_service.SyncService.get_local_version(), 7)

    def test_sync_offline_returns_error(self):
        from server.services.sync_service import SyncService

        async def _no_fetch(url):
            return None

        svc = SyncService()
        with patch.object(SyncService, "_fetch", staticmethod(_no_fetch)):
            result = asyncio.run(svc.sync())
        self.assertEqual(result["status"], "error")

    def test_sync_already_up_to_date(self):
        from server.services.sync_service import SyncService

        async def _fetch(url):
            if url.endswith("/api/sync/version"):
                return {"version": 3}
            return None

        svc = SyncService()
        with patch.object(SyncService, "_fetch", staticmethod(_fetch)), \
             patch.object(SyncService, "get_local_version", return_value=3):
            result = asyncio.run(svc.sync())
        self.assertEqual(result["status"], "ok")
        self.assertIn("已是最新", result["message"])


# ── 设置路由契约 ─────────────────────────────────────────────────────


class TestSettingsRoutes(unittest.TestCase):
    """/api/settings/* 只读与校验路径（不写真实 settings.json）。"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import server
        from server.services.chat_service import get_chat_service
        server.app.dependency_overrides[get_chat_service] = lambda: object()
        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        import server
        server.app.dependency_overrides.clear()

    def test_get_settings_shape(self):
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("env", data)
        self.assertIn("groups", data)

    def test_switch_model_requires_fields(self):
        r = self.client.post("/api/settings/model", json={"group": "", "model": ""})
        self.assertEqual(r.status_code, 400)

    def test_get_tools_shape(self):
        r = self.client.get("/api/settings/tools")
        self.assertEqual(r.status_code, 200)
        tools = r.json()["tools"]
        self.assertGreater(len(tools), 0)
        for t in tools:
            self.assertIn("name", t)
            self.assertIn("enabled", t)

    def test_update_tools_validates_type(self):
        r = self.client.put("/api/settings/tools", json={"tools": "not-a-dict"})
        self.assertEqual(r.status_code, 400)

    def test_get_settings_missing_file_uses_safe_defaults(self):
        # 首次启动没有私有配置时，设置页仍应可打开且不得暴露示例占位 Key。
        from server.routes import settings as settings_routes
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "settings.json"
            with patch.object(settings_routes, "_SETTINGS_PATH", missing):
                r = self.client.get("/api/settings")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertIn("env", data)
            self.assertIn("groups", data)
            self.assertEqual(data["env"]["api_key"], "")

    def test_update_settings_ignores_empty_values(self):
        # 前端清空字段保存时不得把 base_url 写成空串（会直接打断 LLM 初始化）
        import server
        from server.routes import settings as settings_routes
        from server.services.chat_service import get_chat_service

        class _ChatStub:
            def clear_agent_cache(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"env": {"api_key": "k", "base_url": "https://x", "api_type": "chat-completions"}}), encoding="utf-8")
            server.app.dependency_overrides[get_chat_service] = lambda: _ChatStub()
            try:
                with patch.object(settings_routes, "_SETTINGS_PATH", path):
                    r = self.client.put("/api/settings", json={"api_key": "", "base_url": "  "})
                self.assertEqual(r.status_code, 200)
                data = json.loads(path.read_text(encoding="utf-8"))
            finally:
                server.app.dependency_overrides[get_chat_service] = lambda: object()
            self.assertEqual(data["env"]["base_url"], "https://x", "空值不得覆盖已有配置")
            self.assertEqual(data["env"]["api_key"], "k")


# ── 同步变更日志合并规则 ──────────────────────────────────────────


class TestSyncChangeLog(unittest.TestCase):
    """增量同步批次内同一 source 多次变更的合并规则。

    关键场景：先 upsert 后 delete 时，delete 指令必须仍然下发，
    否则已持有旧副本的客户端会永久残留已删除的通知。
    """

    def setUp(self):
        import sync_server.database as db
        self._db = db
        self._old_path = db.DB_PATH
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "sync.db"
        db.init_db()

    def tearDown(self):
        self._db.DB_PATH = self._old_path
        self._tmp.cleanup()

    def test_delete_after_upsert_in_batch_still_emitted(self):
        self._db.upsert_document("a.txt", "旧内容")
        base = self._db.current_version()
        self._db.upsert_document("a.txt", "新内容")
        self._db.delete_document("a.txt")
        changes = self._db.get_changes(base)
        self.assertEqual(changes["upsert"], [], "批内最后动作是删除，不得再下发内容")
        self.assertIn("a.txt", changes["deleted_sources"],
                      "客户端可能已持有旧副本，删除指令不得被吞")
        self.assertIsNone(self._db.get_document_content("a.txt"))

    def test_delete_then_upsert_emits_both(self):
        self._db.upsert_document("b.txt", "更早的内容")
        base = self._db.current_version()
        self._db.delete_document("b.txt")
        self._db.upsert_document("b.txt", "新内容")
        changes = self._db.get_changes(base)
        # 客户端先应用 deleted 再应用 upsert，净结果为新内容，两者都需下发
        self.assertEqual([u["source"] for u in changes["upsert"]], ["b.txt"])
        self.assertIn("b.txt", changes["deleted_sources"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
