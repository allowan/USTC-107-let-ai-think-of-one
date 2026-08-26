"""Fetch configured public web pages and optionally rebuild the public RAG index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.search import fetch_page_text  # noqa: E402

DEFAULT_CONFIG = ROOT / "campus_rag" / "web_sources.json"
DEFAULT_DATA_DIR = ROOT / "campus_rag" / "data"


def _safe_output_path(data_dir: Path, filename: str) -> Path:
    if Path(filename).name != filename or not filename.endswith(".txt"):
        raise ValueError(f"非法输出文件名: {filename}")
    path = (data_dir / filename).resolve()
    if path.parent != data_dir.resolve():
        raise ValueError(f"输出路径超出数据目录: {filename}")
    return path


def sync_sources(config_path: Path, data_dir: Path) -> dict[str, int]:
    sources = json.loads(config_path.read_text(encoding="utf-8"))
    data_dir.mkdir(parents=True, exist_ok=True)
    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}

    for source in sources:
        try:
            url = str(source["url"]).strip()
            name = str(source["name"]).strip()
            output = _safe_output_path(data_dir, str(source["output"]).strip())
            body = fetch_page_text(url, max_chars=200_000)
            document = f"标题：{name}\n来源：{url}\n\n{body.strip()}\n"
            previous = output.read_text(encoding="utf-8") if output.exists() else None
            if previous == document:
                stats["unchanged"] += 1
            else:
                output.write_text(document, encoding="utf-8")
                stats["created" if previous is None else "updated"] += 1
            print(f"OK {name} -> {output.name}")
        except Exception as exc:
            stats["failed"] += 1
            print(f"ERROR {source.get('url', '<missing url>')}: {exc}", file=sys.stderr)
    return stats


def rebuild_public_index(data_dir: Path) -> int:
    from campus_rag.index_manager import RAGSystem
    from campus_rag.query import _reset

    rag = RAGSystem()
    try:
        rag.chroma_client.delete_collection("public")
    except Exception:
        pass
    index = rag.create_public_index(str(data_dir))
    _reset()
    return rag.chroma_client.get_collection("public").count()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()

    stats = sync_sources(args.config.resolve(), args.data_dir.resolve())
    print("summary=" + json.dumps(stats, ensure_ascii=False, sort_keys=True))
    if args.reindex and stats["failed"] == 0:
        print(f"public_index_count={rebuild_public_index(args.data_dir.resolve())}")
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
