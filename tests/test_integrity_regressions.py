"""数据安全、同步快照和并发缓存回归；嵌入与模型均使用离线替身。"""

import asyncio
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import chromadb
import pytest
from llama_index.core import Document, Settings
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import NodeWithScore, TextNode

from campus_rag import config, index_manager, query, query_engine
from server.services.chat_service import ChatService
from server.services.sync_service import SyncService


@pytest.fixture
def rag(monkeypatch: pytest.MonkeyPatch) -> index_manager.RAGSystem:
    model = MockEmbedding(embed_dim=3)
    monkeypatch.setattr(Settings, "_embed_model", model)
    monkeypatch.setattr(config, "init_embed", lambda: True)
    monkeypatch.setattr(config, "require_embed_model", lambda: model)
    monkeypatch.setattr(index_manager, "_embed_dim_cache", 3)
    instance = object.__new__(index_manager.RAGSystem)
    instance.chroma_client = chromadb.EphemeralClient()
    return instance


def test_update_failure_retains_old_data_and_success_replaces_it(
    rag: index_manager.RAGSystem, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = "test_" + uuid4().hex
    old = Document(text="旧课表", metadata={"source": "课表"})
    other = Document(text="其他来源", metadata={"source": "备忘"})
    rag.replace_documents(collection, [old, other])
    stored = rag.chroma_client.get_collection(collection)
    before = stored.get()
    new = Document(text="新课表", metadata={"source": "课表"})
    with monkeypatch.context() as patcher:
        patcher.setattr(MockEmbedding, "get_text_embedding_batch", Mock(side_effect=OSError("offline")))
        with pytest.raises(OSError, match="offline"):
            rag.replace_documents(collection, [new])
    assert stored.get() == before
    rag.replace_documents(collection, [new])
    assert set(stored.get()["documents"]) == {"新课表", "其他来源"}
    rag.replace_documents(collection, [new])
    assert stored.count() == 2


def test_partial_insert_failure_is_cleaned_up(
    rag: index_manager.RAGSystem, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = "test_" + uuid4().hex
    rag.replace_documents(collection, [Document(text="旧", metadata={"source": "a"})])
    stored = rag.chroma_client.get_collection(collection)
    before = stored.get()
    original = index_manager.VectorStoreIndex.insert_nodes

    def broken_insert(index: object, nodes: list, **kwargs: object) -> None:
        original(index, nodes[:1], **kwargs)
        raise OSError("disk failure")

    monkeypatch.setattr(index_manager.VectorStoreIndex, "insert_nodes", broken_insert)
    with pytest.raises(OSError, match="disk failure"):
        rag.replace_documents(collection, [Document(text="新", metadata={"source": "a"})], replace_all=True)
    assert stored.get() == before


def test_delete_error_after_commit_does_not_remove_new_data(
    rag: index_manager.RAGSystem, monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = "test_" + uuid4().hex
    rag.replace_documents(collection, [Document(text="旧", metadata={"source": "a"})])
    stored = rag.chroma_client.get_collection(collection)
    original = type(stored).delete

    def committed_then_failed(instance: object, **kwargs: object) -> None:
        original(instance, **kwargs)
        raise OSError("response lost after commit")

    with monkeypatch.context() as patcher:
        patcher.setattr(type(stored), "delete", committed_then_failed)
        with pytest.raises(OSError):
            rag.replace_documents(collection, [Document(text="新", metadata={"source": "a"})])
    assert stored.get()["documents"] == ["新"]
    rag.replace_documents(collection, [Document(text="新", metadata={"source": "a"})])
    assert stored.get()["documents"] == ["新"]


def test_public_document_constructor_persists_in_chroma(rag: index_manager.RAGSystem) -> None:
    text = "持久化测试-" + uuid4().hex
    rag.create_public_index_via_docs([Document(text=text, metadata={"source": "constructor"})])
    assert text in rag.chroma_client.get_collection("public").get()["documents"]


def test_empty_full_snapshot_preserves_collection_identity(rag: index_manager.RAGSystem) -> None:
    collection = "test_" + uuid4().hex
    rag.replace_documents(collection, [Document(text="旧", metadata={"source": "a"})])
    stored = rag.chroma_client.get_collection(collection)
    identity = stored.id
    rag.replace_documents(collection, [], replace_all=True)
    assert stored.count() == 0
    assert rag.chroma_client.get_collection(collection).id == identity


def test_empty_public_index_is_not_reseeded(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = object.__new__(index_manager.RAGSystem)
    instance.chroma_client = Mock()
    instance.chroma_client.get_collection.return_value.count.return_value = 0
    monkeypatch.setattr(index_manager, "ChromaVectorStore", Mock())
    monkeypatch.setattr(index_manager, "assert_collection_dim", Mock())
    monkeypatch.setattr(index_manager.VectorStoreIndex, "from_vector_store", Mock(return_value="empty"))
    instance.create_public_index = Mock(side_effect=AssertionError("must not reseed"))
    assert instance.get_or_create_public_index() == "empty"


def test_missing_source_is_rejected_before_writing(rag: index_manager.RAGSystem) -> None:
    with pytest.raises(ValueError, match="source"):
        rag.replace_documents("test_" + uuid4().hex, [Document(text="内容")])


def test_dimension_mismatch_never_drops_public_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = object.__new__(index_manager.RAGSystem)
    instance.chroma_client = Mock()
    monkeypatch.setattr(index_manager, "assert_collection_dim", Mock(side_effect=RuntimeError("dimension")))
    with pytest.raises(RuntimeError, match="dimension"):
        instance.get_public_index()
    instance.chroma_client.delete_collection.assert_not_called()


def test_delete_failure_is_not_reported_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = object.__new__(index_manager.RAGSystem)
    instance.chroma_client = Mock()
    instance.chroma_client.get_collection.side_effect = OSError("storage unavailable")
    with pytest.raises(OSError):
        instance.delete_public_documents_by_source("a")


def test_queries_share_pipeline_and_cached_index(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = Mock()
    retriever.retrieve.return_value = [NodeWithScore(node=TextNode(text="结果", metadata={"source": "a"}))]
    index = Mock()
    monkeypatch.setattr(query_engine, "retrieve_nodes", lambda *args, **kwargs: retriever.retrieve(args[0]))
    fake_rag = Mock()
    fake_rag.get_or_create_public_index.return_value = index
    monkeypatch.setattr(query, "_rag", fake_rag)
    monkeypatch.setattr(query, "_public_index", None)
    monkeypatch.setattr(query.events, "sync_events_from_documents", Mock())
    assert "结果" in query.search_notices("查询")
    query.add_public_documents([])
    assert "结果" in query.search_notices("查询")
    assert retriever.retrieve.call_count == 2
    assert fake_rag.get_or_create_public_index.call_count == 1


def test_initialization_failure_can_be_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rag = Mock()
    index = Mock()
    fake_rag.get_or_create_public_index.side_effect = [OSError("unavailable"), index]
    monkeypatch.setattr(query, "RAGSystem", Mock(return_value=fake_rag))
    monkeypatch.setattr(query, "_rag", None)
    monkeypatch.setattr(query, "_public_index", None)
    with pytest.raises(OSError):
        query._ensure_init()
    query._ensure_init()
    assert query._public_index is index


def test_answer_queries_reuse_public_index(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rag = Mock()
    monkeypatch.setattr(query, "_rag", fake_rag)
    monkeypatch.setattr(query, "_public_index", None)
    answer = Mock(return_value="回答")
    monkeypatch.setattr(query_engine, "get_rag_response", answer)
    for _ in range(20):
        assert query.search_notices_answer("问题") == "回答"
    assert fake_rag.get_or_create_public_index.call_count == 1
    indexes = [call.kwargs["public_index"] for call in answer.call_args_list]
    assert all(index is indexes[0] for index in indexes)


def test_concurrent_cold_start_builds_one_index(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rag = Mock()
    monkeypatch.setattr(query, "RAGSystem", Mock(return_value=fake_rag))
    monkeypatch.setattr(query, "_rag", None)
    monkeypatch.setattr(query, "_public_index", None)
    barrier = threading.Barrier(4)

    def initialize() -> bool:
        barrier.wait(timeout=5)
        return query._ensure_init()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda _: initialize(), range(4)))
    assert query.RAGSystem.call_count == 1
    assert fake_rag.get_or_create_public_index.call_count == 1


def test_personal_listing_does_not_initialize_public(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rag = Mock()
    monkeypatch.setattr(query, "_rag", fake_rag)
    monkeypatch.setattr(query, "_ensure_init", Mock(side_effect=AssertionError("public init")))
    query.list_user_data("local_user")
    fake_rag.get_or_create_public_index.assert_not_called()


def test_retriever_cache_is_bounded_and_reuses_hot_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections import OrderedDict

    monkeypatch.setattr(query_engine, "_retriever_cache", OrderedDict())
    monkeypatch.setattr(query_engine, "VectorIndexRetriever", Mock(side_effect=lambda **kw: SimpleNamespace(**kw)))
    hot = SimpleNamespace(index_id="same-id")
    first = query_engine._get_cached_retriever(hot, 10)
    assert query_engine._get_cached_retriever(hot, 10) is first
    for _ in range(200):
        query_engine._get_cached_retriever(SimpleNamespace(index_id="same-id"), 10)
    assert len(query_engine._retriever_cache) == query_engine._MAX_RETRIEVERS


def test_sync_replaces_before_deleting_and_collapses_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    import campus_rag

    replace = Mock()
    remove = Mock()
    monkeypatch.setattr(campus_rag, "upsert_public_documents", replace)
    monkeypatch.setattr(campus_rag, "delete_public_data", remove)
    SyncService()._apply_changes({
        "upsert": [{"source": "a", "content": "old"}, {"source": "a", "content": "new"}],
        "deleted_sources": ["a", "b"],
    })
    assert [(doc.metadata["source"], doc.text) for doc in replace.call_args.args[0]] == [("a", "new")]
    remove.assert_called_once_with("b")


def test_change_log_returns_latest_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sync_server.database as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sync.db")
    db.init_db()
    for content in ("old", "middle", "new"):
        db.upsert_document("a", content)
    assert db.get_changes(0) == {"version": 3, "upsert": [{"source": "a", "content": "new"}], "deleted_sources": []}
    assert db.get_full_snapshot() == {"version": 3, "documents": [{"source": "a", "content": "new"}]}


@pytest.mark.parametrize("operation", ["get_changes", "get_full_snapshot"])
def test_snapshot_remains_consistent_during_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    import sync_server.database as db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sync.db")
    db.init_db()
    db.upsert_document("a", "old")
    connect = db._get_conn

    class Connection:
        def __init__(self) -> None:
            self.inner = connect()

        def execute(self, sql: str, *args: object) -> object:
            cursor = self.inner.execute(sql, *args)
            if "COALESCE(MAX(version)" in sql:
                with monkeypatch.context() as patcher:
                    patcher.setattr(db, "_get_conn", connect)
                    db.upsert_document("a", "new")
            return cursor

        def close(self) -> None:
            self.inner.close()

    monkeypatch.setattr(db, "_get_conn", Connection)
    result = db.get_changes(0) if operation == "get_changes" else db.get_full_snapshot()
    assert result["version"] == 1
    assert (result.get("upsert") or result.get("documents")) == [{"source": "a", "content": "old"}]


def test_agent_invalidation_waits_for_active_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        service = ChatService()
        ctx = SimpleNamespace(conn=object(), built_date=date.today())
        service._user_agents["local_user"] = ctx
        close = AsyncMock()
        monkeypatch.setattr(service, "_close_ctx", close)
        stream = service.stream_chat_events("local_user", "hello", "topic")
        assert await anext(stream) == ("thinking", "")
        service.clear_agent_cache()
        await asyncio.sleep(0)
        close.assert_not_awaited()
        await stream.aclose()
        await asyncio.gather(*service._pending_closes)
        close.assert_awaited_once_with(ctx)
        assert not service._active_contexts
        assert not service._retired_contexts

    asyncio.run(scenario())


def test_same_topic_rejects_second_stream_and_releases_on_close(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        service = ChatService()

        async def tokens(*args: object) -> object:
            yield "token", "hello"

        monkeypatch.setattr(service, "stream_chat_events", tokens)
        stream = service.sse_generator("local_user", "hello", "topic")
        assert '"type": "token"' in await anext(stream)
        second = [item async for item in service.sse_generator("local_user", "hello", "topic")]
        assert '"type": "error"' in second[0]
        await stream.aclose()
        assert not service._active_threads

    asyncio.run(scenario())


def test_configuration_change_during_build_discards_stale_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    import main
    import campus_rag

    async def scenario() -> None:
        service = ChatService()
        started = asyncio.Event()
        proceed = asyncio.Event()
        contexts = [SimpleNamespace(conn=object()), SimpleNamespace(conn=object())]
        builds = 0

        async def build(**kwargs: object) -> object:
            nonlocal builds
            index = builds
            builds += 1
            if index == 0:
                started.set()
                await proceed.wait()
            return contexts[index]

        close = AsyncMock()
        monkeypatch.setattr(service, "_close_ctx", close)
        monkeypatch.setattr(main, "build_agent", build)
        monkeypatch.setattr(campus_rag, "get_user_tool_prefs", lambda _: None)
        pending = asyncio.create_task(service.get_agent("local_user"))
        await asyncio.wait_for(started.wait(), timeout=5)
        service.clear_agent_cache()
        proceed.set()
        assert await pending is contexts[1]
        close.assert_awaited_once_with(contexts[0])

    asyncio.run(scenario())


def test_cancelled_sync_keeps_lock_until_write_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        service = SyncService()
        started = asyncio.Event()
        proceed = asyncio.Event()
        calls = []

        async def sync(force: bool) -> dict:
            calls.append(force)
            started.set()
            await proceed.wait()
            return {"status": "ok"}

        monkeypatch.setattr(service, "_sync", sync)
        first = asyncio.create_task(service.sync())
        await asyncio.wait_for(started.wait(), timeout=5)
        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        second = asyncio.create_task(service.sync(True))
        await asyncio.sleep(0)
        assert calls == [False]
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == {"status": "ok"}
        assert calls == [False, True]

    asyncio.run(scenario())


def test_failed_sync_does_not_advance_version(monkeypatch: pytest.MonkeyPatch) -> None:
    service = SyncService()
    monkeypatch.setattr(service, "check_remote_version", AsyncMock(return_value=2))
    monkeypatch.setattr(service, "get_local_version", Mock(return_value=1))
    monkeypatch.setattr(service, "_fetch", AsyncMock(return_value={"version": 2, "upsert": []}))
    monkeypatch.setattr(service, "_apply_changes", Mock(side_effect=OSError("storage failure")))
    save = Mock()
    monkeypatch.setattr(service, "_set_local_version", save)
    assert asyncio.run(service.sync())["status"] == "error"
    save.assert_not_called()


def test_atomic_version_write_retains_old_state_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.services.sync_service as module

    path = tmp_path / "sync_state.json"
    monkeypatch.setattr(module, "SYNC_STATE_PATH", path)
    SyncService._set_local_version(1)
    monkeypatch.setattr(module.os, "replace", Mock(side_effect=OSError("rename failure")))
    with pytest.raises(OSError):
        SyncService._set_local_version(2)
    assert SyncService.get_local_version() == 1


def test_stream_closes_model_iterator_before_retired_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.messages import AIMessageChunk

    async def scenario() -> None:
        service = ChatService()
        order = []

        async def messages(*args: object, **kwargs: object) -> object:
            try:
                yield AIMessageChunk(content="token"), {}
            finally:
                order.append("model closed")

        async def close(ctx: object) -> None:
            order.append("connection closed")

        ctx = SimpleNamespace(conn=object(), agent=SimpleNamespace(astream=messages), built_date=date.today())
        service._user_agents["local_user"] = ctx
        monkeypatch.setattr(service, "_close_ctx", close)
        stream = service.stream_chat_events("local_user", "hello", "topic")
        await anext(stream)
        await anext(stream)
        service.clear_agent_cache()
        await stream.aclose()
        await asyncio.gather(*service._pending_closes)
        assert order == ["model closed", "connection closed"]

    asyncio.run(scenario())


def test_cancelled_agent_build_closes_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import main

    async def scenario() -> None:
        started = asyncio.Event()
        connection = SimpleNamespace(close=AsyncMock())

        async def pruning(conn: object) -> None:
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(main.config, "init_chat", Mock())
        monkeypatch.setattr(main.aiosqlite, "connect", AsyncMock(return_value=connection))
        monkeypatch.setattr(main, "_prune_checkpoints", pruning)
        build = asyncio.create_task(main.build_agent("local_user"))
        await asyncio.wait_for(started.wait(), timeout=5)
        build.cancel()
        with pytest.raises(asyncio.CancelledError):
            await build
        connection.close.assert_awaited_once()

    asyncio.run(scenario())


def test_hybrid_union_preserves_sources_and_never_generates(monkeypatch: pytest.MonkeyPatch) -> None:
    from campus_rag.keyword_retriever import BM25Retriever
    a = TextNode(id_="a", text="quantum", metadata={"source": "a", "url": "https://example.org/a"})
    b = TextNode(id_="b", text="quantum", metadata={"source": "b"})
    index = Mock()
    monkeypatch.setattr(query_engine, "_get_cached_retriever", lambda *args: Mock(retrieve=lambda q: [NodeWithScore(node=a, score=999)]))
    monkeypatch.setattr(query_engine, "_get_bm25_cached", lambda _: BM25Retriever(nodes=[a, b]))
    monkeypatch.setattr(config, "require_llm", Mock(side_effect=AssertionError("nested LLM")))
    result = query_engine.retrieve_nodes("quantum", public_index=index, rerank=False)
    assert [n.node.node_id for n in result] == ["a", "b"]
    assert result[0].metadata["url"] == "https://example.org/a"
    assert result[0].score == pytest.approx(2 / 61)
    assert query_engine.retrieve_nodes(" ", public_index=index) == []


def test_bm25_empty_oov_and_singleton() -> None:
    from campus_rag.keyword_retriever import BM25Retriever
    node = TextNode(text="quantum", metadata={"source": "one"})
    bm25 = BM25Retriever(nodes=[node, TextNode(text=" !!! ")])
    assert bm25.retrieve("") == []
    assert bm25.retrieve("missing") == []
    assert bm25.retrieve("quantum", top_k=0) == []
    assert bm25.retrieve("quantum")[0].node is node


def test_keyword_cache_tracks_equal_size_replace_and_clear(rag: index_manager.RAGSystem) -> None:
    user = uuid4().hex
    rag.add_user_documents(user, [Document(text="oldword", metadata={"source": "a"})])
    index = rag.get_user_index(user)
    assert query_engine._get_bm25_cached(index).retrieve("oldword")
    rag.replace_documents("user_" + user, [Document(text="newword", metadata={"source": "a"})])
    assert not query_engine._get_bm25_cached(index).retrieve("oldword")
    assert query_engine._get_bm25_cached(index).retrieve("newword")
    rag.clear_user_index(user)
    assert not query_engine._get_bm25_cached(index).retrieve("newword")
    assert index.vector_store.get_nodes(node_ids=None) == []


@pytest.mark.parametrize("scores", [[0.9], [0.9, float("nan")], [0.9, float("inf")]])
def test_bad_reranker_preserves_all_original_scores(monkeypatch: pytest.MonkeyPatch, scores: list) -> None:
    nodes = [NodeWithScore(node=TextNode(text="a"), score=0.1), NodeWithScore(node=TextNode(text="b"), score=0.2)]
    monkeypatch.setattr(query_engine, "_get_reranker", lambda: Mock(compute_score=lambda *args, **kwargs: scores))
    monkeypatch.setattr(query_engine, "_reranker_retry_at", 0.0)
    result = query_engine.rerank_nodes("q", nodes)
    assert result == [nodes[1], nodes[0]]
    assert [n.score for n in nodes] == [0.1, 0.2]


def test_agent_search_tools_use_pure_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    import main
    notices = Mock(return_value="notice fragment")
    personal = Mock(return_value="personal fragment")
    monkeypatch.setattr(main, "search_notices", notices)
    monkeypatch.setattr(main, "search_user_data", personal)
    monkeypatch.setattr(config, "require_llm", Mock(side_effect=AssertionError("nested LLM")))
    assert main.search_campus_notices.invoke({"query": "q"}) == "notice fragment"
    assert main._make_search_my_data("local_user").invoke({"query": "q"}) == "personal fragment"
    personal.assert_called_once_with("q", "local_user")


def test_failed_write_invalidates_keyword_snapshot(rag: index_manager.RAGSystem, monkeypatch: pytest.MonkeyPatch) -> None:
    user = uuid4().hex
    rag.add_user_documents(user, [Document(text="oldword", metadata={"source": "a"})])
    index = rag.get_user_index(user)
    snapshot = query_engine._get_bm25_cached(index)
    with monkeypatch.context() as patcher:
        patcher.setattr(MockEmbedding, "get_text_embedding_batch", Mock(side_effect=OSError("offline")))
        with pytest.raises(OSError):
            rag.replace_documents("user_" + user, [Document(text="newword", metadata={"source": "a"})])
    current = query_engine._get_bm25_cached(index)
    assert current is not snapshot
    assert current.retrieve("oldword")
    assert not current.retrieve("newword")


def test_keyword_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from collections import OrderedDict
    monkeypatch.setattr(query_engine, "_bm25_cache", OrderedDict())
    for _ in range(100):
        index = Mock()
        index.vector_store.get_nodes.return_value = []
        query_engine._get_bm25_cached(index)
    assert len(query_engine._bm25_cache) == query_engine._MAX_RETRIEVERS


@pytest.mark.parametrize("results", [
    [{"index": -1, "score": 0.5}],
    [{"index": 0, "score": 0.5}, {"index": 0, "score": 0.8}],
    [{"index": 0, "score": 0.5}],
    [{"index": "0", "score": 0.5}],
])
def test_rerank_api_rejects_invalid_indices(results: list) -> None:
    reranker = object.__new__(query_engine._APIReranker)
    reranker._client = Mock()
    reranker._client.post.return_value.json.return_value = {"results": results}
    reranker._url, reranker._headers, reranker._model = "unused", {}, "test"
    with pytest.raises(ValueError):
        reranker.compute_score([["q", "a"], ["q", "b"]])
