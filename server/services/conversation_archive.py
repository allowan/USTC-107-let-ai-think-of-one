"""通过官方 checkpoint API 读取可导出的对话正文，不初始化 Agent。"""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)


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
