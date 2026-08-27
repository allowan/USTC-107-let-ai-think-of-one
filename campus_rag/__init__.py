import os

# Force offline mode for HuggingFace (models cached locally via HF mirror).
# Must be set before any library imports to prevent network access.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from .query import search_notices, search_user_data, add_user_data, add_user_files, list_user_data, delete_user_data
from .query import search_notices_answer, search_user_data_answer
from .query import update_user_data, add_public_documents, delete_public_data, replace_public_documents
from .query import reset_caches
from .auth import authenticate, register_user, list_users
from .auth import create_topic, list_topics, delete_topic, get_topic, rename_topic
from .auth import get_user_tool_prefs, set_user_tool_prefs
from .query_engine import get_rag_response, rerank_nodes, get_rag_response_hybrid
from .index_manager import RAGSystem
