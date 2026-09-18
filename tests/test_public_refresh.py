"""采集后刷新只走公共安全入口，在读取完整快照前不修改索引。"""

from pathlib import Path
from unittest.mock import Mock

import pytest

import campus_rag
from scripts.sync_web_sources import rebuild_public_index


def test_refresh_passes_complete_documents_to_public_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """保留来源和正文，避免重建调用底层删除集合。"""
    (tmp_path / "a.txt").write_text("\ufeff来源：https://example.edu/a\n正文A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("正文B", encoding="utf-8")
    replace = Mock()
    monkeypatch.setattr(campus_rag, "replace_public_documents", replace)
    monkeypatch.setattr(campus_rag, "RAGSystem", Mock(side_effect=AssertionError("must not delete or rebuild a collection")))
    assert rebuild_public_index(tmp_path) == 2
    docs = replace.call_args.args[0]
    assert [doc.metadata["source"] for doc in docs] == ["a.txt", "b.txt"]
    assert docs[0].text.startswith("来源：")
    assert docs[1].text == "正文B"
    replace.assert_called_once()


@pytest.mark.parametrize("invalid", ["missing", "empty", "blank", "unreadable"])
def test_invalid_snapshot_cannot_start_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str) -> None:
    """存在其他好文档也不能掩盖损坏或空白的文件。"""
    target = tmp_path / "missing" if invalid == "missing" else tmp_path
    if invalid in {"blank", "unreadable"}:
        (tmp_path / "a.txt").write_text("好文档", encoding="utf-8")
        (tmp_path / "b.txt").write_bytes(b"  \n" if invalid == "blank" else b"\xff\xfe\xff")
    replace = Mock()
    monkeypatch.setattr(campus_rag, "replace_public_documents", replace)
    with pytest.raises((ValueError, UnicodeError)):
        rebuild_public_index(target)
    replace.assert_not_called()


def test_index_failure_is_propagated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """安全入口失败不能被脚本伪装成成功数量。"""
    (tmp_path / "a.txt").write_text("通知", encoding="utf-8")
    monkeypatch.setattr(campus_rag, "replace_public_documents", Mock(side_effect=RuntimeError("embedding unavailable")))
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        rebuild_public_index(tmp_path)
