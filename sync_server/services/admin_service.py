"""Admin service: notice CRUD."""

import sync_server.database as db

_admin_svc = None


def get_admin_service() -> "AdminService":
    global _admin_svc
    if _admin_svc is None:
        _admin_svc = AdminService()
    return _admin_svc


class AdminService:

    @staticmethod
    def list_notices() -> list[dict]:
        docs = db.get_documents()
        result = []
        for doc in docs:
            content = doc["content"]
            result.append({
                "source": doc["source"],
                "preview": content[:200] + "..." if len(content) > 200 else content,
                "chunks": 1,  # raw doc count, no longer chunked by ChromaDB
            })
        return result

    @staticmethod
    def add_notice(content: str, source: str = "") -> dict:
        if not source:
            from datetime import datetime
            source = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        version = db.upsert_document(source, content)
        return {"source": source, "version": version}

    @staticmethod
    def get_notice(source: str) -> dict | None:
        content = db.get_document_content(source)
        if content is None:
            return None
        return {"source": source, "content": content}

    @staticmethod
    def update_notice(source: str, content: str) -> dict:
        version = db.upsert_document(source, content)
        return {"source": source, "version": version}

    @staticmethod
    def delete_notice(source: str) -> int:
        return db.delete_document(source)

    @staticmethod
    def get_stats() -> dict:
        docs = db.get_documents()
        return {
            "document_count": len(docs),
            "version": db.current_version(),
        }
