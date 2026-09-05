"""Synchronize configured USTC notice columns into the public RAG data directory."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.ustc_crawler import load_columns, sync_column  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "campus_rag" / "ustc_columns.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "campus_rag" / "data")
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()

    total = {
        "discovered": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
    }
    for column in load_columns(args.config):
        try:
            stats = sync_column(column, args.data_dir)
        except Exception as exc:
            # 单个栏目不可达（改版、404、需要登录）不应中断整批同步，
            # 否则一次网络抖动就会让其余栏目的语料全部抓不到。
            stats = {
                "discovered": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "skipped": 0,
                "failed": 1,
                "errors": [f"{column['url']}: {type(exc).__name__}: {exc}"],
            }
        print(f"{column['name']}=" + json.dumps(stats, ensure_ascii=False, sort_keys=True))
        for key in total:
            total[key] += stats[key]
    print("summary=" + json.dumps(total, ensure_ascii=False, sort_keys=True))

    if args.reindex and total["failed"] == 0:
        from scripts.sync_web_sources import rebuild_public_index
        print(f"public_index_count={rebuild_public_index(args.data_dir)}")
    return 1 if total["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
