# auth.py
import uuid
from datetime import datetime
from pathlib import Path
import bcrypt
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

# 锚定项目根目录的绝对路径：相对路径 "./users.db" 依赖启动 CWD，
# 从其他目录启动会静默新建空库导致话题"凭空消失"。
DATABASE_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'users.db'}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    hashed_password = Column(String)
    is_admin = Column(Boolean, default=False)


class Topic(Base):
    __tablename__ = "topics"
    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    username = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserToolPref(Base):
    __tablename__ = "user_tool_prefs"
    username = Column(String, primary_key=True)
    tool_name = Column(String, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)


Base.metadata.create_all(bind=engine)


def create_default_admin():
    db = SessionLocal()
    if not db.query(User).filter_by(username="admin").first():
        db.add(User(
            username="admin",
            hashed_password=_hash_password("admin123"),
            is_admin=True,
        ))
        db.commit()
    db.close()


create_default_admin()


def authenticate(username: str, password: str) -> tuple:
    """返回 (是否成功, 是否为管理员)"""
    db = SessionLocal()
    user = db.query(User).filter_by(username=username).first()
    db.close()
    if not user:
        return False, False
    if _verify_password(password, user.hashed_password):
        return True, user.is_admin
    return False, False


def register_user(username: str, password: str, is_admin: bool = False) -> bool:
    db = SessionLocal()
    if db.query(User).filter_by(username=username).first():
        db.close()
        return False
    db.add(User(
        username=username,
        hashed_password=_hash_password(password),
        is_admin=is_admin,
    ))
    db.commit()
    db.close()
    return True


def list_users() -> list:
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return [(u.username, u.is_admin) for u in users]


# ── Topic CRUD ────────────────────────────────────────────────

def _thread_id(username: str, topic_id: str) -> str:
    return f"user-{username}-topic-{topic_id}"


def create_topic(username: str, name: str) -> dict:
    db = SessionLocal()
    tid = uuid.uuid4().hex[:12]
    topic = Topic(id=tid, username=username, name=name)
    db.add(topic)
    db.commit()
    db.close()
    return {"id": tid, "name": name, "thread_id": _thread_id(username, tid)}


def list_topics(username: str) -> list:
    db = SessionLocal()
    topics = db.query(Topic).filter_by(username=username).order_by(Topic.created_at.desc()).all()
    db.close()
    return [{"id": t.id, "name": t.name, "thread_id": _thread_id(username, t.id)} for t in topics]


def delete_topic(username: str, topic_id: str) -> bool:
    db = SessionLocal()
    topic = db.query(Topic).filter_by(id=topic_id, username=username).first()
    if not topic:
        db.close()
        return False
    db.delete(topic)
    db.commit()
    db.close()
    return True


def get_topic(username: str, topic_id: str) -> dict | None:
    db = SessionLocal()
    topic = db.query(Topic).filter_by(id=topic_id, username=username).first()
    db.close()
    if not topic:
        return None
    return {"id": topic.id, "name": topic.name, "thread_id": _thread_id(username, topic.id)}


def rename_topic(username: str, topic_id: str, new_name: str) -> bool:
    db = SessionLocal()
    topic = db.query(Topic).filter_by(id=topic_id, username=username).first()
    if not topic:
        db.close()
        return False
    topic.name = new_name
    db.commit()
    db.close()
    return True


# ── Tool Preferences CRUD ───────────────────────────────────────

def get_user_tool_prefs(username: str) -> dict[str, bool] | None:
    """返回用户工具偏好 {tool_name: enabled}。None 表示未设置（默认全部启用）；
    空 dict 表示用户显式禁用了全部工具。"""
    db = SessionLocal()
    rows = db.query(UserToolPref).filter_by(username=username).all()
    db.close()
    if not rows:
        return None
    return {r.tool_name: r.enabled for r in rows}


def set_user_tool_prefs(username: str, prefs: dict[str, bool]) -> None:
    """替换用户的所有工具偏好设置。"""
    db = SessionLocal()
    db.query(UserToolPref).filter_by(username=username).delete()
    for tool_name, enabled in prefs.items():
        db.add(UserToolPref(username=username, tool_name=tool_name, enabled=bool(enabled)))
    db.commit()
    db.close()
