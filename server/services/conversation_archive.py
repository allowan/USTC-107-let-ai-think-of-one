"""通过官方 checkpoint API 读取可导出的对话正文，不初始化 Agent。"""

import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)
_restore_lock = threading.Lock()


class ConversationArchive:
    """从一致性内存快照读取指定话题的最新可见对话。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path if db_path is not None else (
            Path(__file__).resolve().parents[2] / "data" / "agent_checkpoints.db"
        )

    def read_histories(self, thread_ids: list[str]) -> dict[str, list[dict[str, str]]]:
        """仅返回用户和助手文本；原库不存在时不创建文件。"""
        histories: dict[str, list[dict[str, str]]] = {key: [] for key in thread_ids}
        if not thread_ids or not self.db_path.exists():
            return histories
        try:
            with closing(sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(":memory:")) as snapshot:
                    source.backup(snapshot)
                    # SqliteSaver 可能执行建表准备，仅允许它操作内存副本。
                    if not snapshot.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'"
                    ).fetchone():
                        raise ValueError("对话数据库缺少 checkpoint 表")
                    saver = SqliteSaver(snapshot)
                    for thread_id in histories:
                        checkpoint = saver.get({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
                        if checkpoint is None:
                            continue
                        messages = checkpoint.get("channel_values", {}).get("messages", [])
                        for message in messages:
                            if not isinstance(message, (HumanMessage, AIMessage)):
                                continue
                            content = message.content
                            if isinstance(content, list):
                                content = "".join(
                                    block if isinstance(block, str) else block["text"]
                                    for block in content
                                    if isinstance(block, str) or (
                                        isinstance(block, dict) and block.get("type") == "text"
                                        and isinstance(block.get("text"), str)
                                    )
                                )
                            if content:
                                histories[thread_id].append({
                                    "role": "user" if isinstance(message, HumanMessage) else "assistant",
                                    "content": content,
                                })
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            # 异常内容可能包含正文或序列化数据，不写入日志。
            logger.error("读取对话备份失败，未生成不完整的对话导出")
            raise
        return histories

    def write_history_if_empty(self, thread_id: str, messages: list[dict[str, str]]) -> bool:
        """使用官方 API 为新话题恢复纯文本，已有 checkpoint 时不覆盖。"""
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("恢复话题标识不能为空")
        if not isinstance(messages, list) or any(
            not isinstance(message, dict) or set(message) != {"role", "content"}
            or message["role"] not in ("user", "assistant")
            or not isinstance(message["content"], str)
            for message in messages
        ):
            raise ValueError("恢复对话仅接受用户和助手纯文本")
        visible_messages = [
            HumanMessage(content=message["content"]) if message["role"] == "user"
            else AIMessage(content=message["content"])
            for message in messages
        ]
        try:
            with _restore_lock:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                with SqliteSaver.from_conn_string(str(self.db_path)) as saver:
                    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                    if saver.get(config) is not None:
                        return False
                    checkpoint = empty_checkpoint()
                    checkpoint["channel_values"] = {"messages": visible_messages}
                    checkpoint["channel_versions"] = {"messages": "1"}
                    saver.put(config, checkpoint, {"source": "update", "step": -1, "parents": {}}, {"messages": "1"})
                    return True
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            logger.error("恢复对话失败，未覆盖已有话题内容")
            raise
