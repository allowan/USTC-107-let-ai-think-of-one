from pathlib import Path
from dotenv import load_dotenv

# 无论从哪里导入本包，都先加载 campus_rag/.env
_base = Path(__file__).resolve().parent
load_dotenv(_base / ".env")

from .query import search_notices
