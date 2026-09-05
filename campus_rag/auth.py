# auth.py
# 本地单用户形态：无登录、无 JWT，get_user() 恒返回 "local_user"。
# 本模块只保留话题、工具偏好、追踪事件三张业务表的 CRUD。
import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

# 锚定项目根目录的绝对路径：相对路径 "./users.db" 依赖启动 CWD，
# 从其他目录启动会静默新建空库导致话题"凭空消失"。
DATABASE_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'users.db'}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


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


class TrackedEvent(Base):
    """用户主动追踪的校园事件（今日面板顶部固定展示，便于到期提醒）。"""
    __tablename__ = "tracked_events"
    username = Column(String, primary_key=True)
    source = Column(String, primary_key=True)
    title = Column(String)
    category = Column(String)
    date_kind = Column(String)   # 'deadline' | 'start'
    date_value = Column(String)  # ISO 日期
    url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


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


# ── TrackedEvent CRUD（今日面板用）───────────────────────────────────

def track_event(
    username: str, source: str, title: str | None, category: str | None,
    date_kind: str, date_value: str | None, url: str | None,
) -> dict:
    """标记某条校园事件为用户追踪（重复标记即更新，幂等）。"""
    db = SessionLocal()
    existing = db.query(TrackedEvent).filter_by(
        username=username, source=source
    ).first()
    if existing is None:
        existing = TrackedEvent(
            username=username, source=source, title=title, category=category,
            date_kind=date_kind, date_value=date_value, url=url,
        )
        db.add(existing)
    else:
        existing.title = title
        existing.category = category
        existing.date_kind = date_kind
        existing.date_value = date_value
        existing.url = url
    db.commit()
    db.refresh(existing)
    result = {
        "source": existing.source, "title": existing.title,
        "category": existing.category, "date_kind": existing.date_kind,
        "date_value": existing.date_value, "url": existing.url,
        "created_at": existing.created_at.isoformat() if existing.created_at else None,
    }
    db.close()
    return result


def untrack_event(username: str, source: str) -> bool:
    """取消追踪某事件，返回是否确实删除了一条。"""
    db = SessionLocal()
    row = db.query(TrackedEvent).filter_by(
        username=username, source=source
    ).first()
    if row is None:
        db.close()
        return False
    db.delete(row)
    db.commit()
    db.close()
    return True


def list_tracked_events(username: str) -> list[dict]:
    """列出用户追踪的全部事件（按创建时间倒序）。"""
    db = SessionLocal()
    rows = db.query(TrackedEvent).filter_by(username=username).order_by(
        TrackedEvent.created_at.desc()
    ).all()
    result = [
        {
            "source": r.source, "title": r.title, "category": r.category,
            "date_kind": r.date_kind, "date_value": r.date_value, "url": r.url,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    db.close()
    return result
