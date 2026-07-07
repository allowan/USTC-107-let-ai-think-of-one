from pathlib import Path
from dotenv import load_dotenv

# 无论从哪里导入本包，都先加载 campus_rag/.env
_base = Path(__file__).resolve().parent
load_dotenv(_base / ".env")

from .query import search_notices, search_user_data, search_all, add_user_data, add_user_files
from .auth import authenticate, register_user, list_users, get_user_admin_status, delete_user
from .ingest import add_public_activity, add_user_activity
from .query_engine import get_rag_response, get_rag_response_hybrid, rerank_nodes
from .index_manager import RAGSystem
