from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from .query import search_notices, search_user_data, add_user_data, add_user_files, list_user_data, delete_user_data
from .query import search_notices_answer, search_user_data_answer
from .auth import authenticate, register_user, list_users
from .auth import create_topic, list_topics, delete_topic, get_topic, rename_topic
from .query_engine import get_rag_response, rerank_nodes
from .index_manager import RAGSystem
