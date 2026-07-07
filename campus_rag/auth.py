# auth.py
import bcrypt
from sqlalchemy import create_engine, Column, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./users.db"
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


def get_user_admin_status(username: str) -> bool:
    """查询用户是否为管理员（仅需用户名，无需密码）。"""
    db = SessionLocal()
    user = db.query(User).filter_by(username=username).first()
    db.close()
    return user.is_admin if user else False


def delete_user(username: str) -> bool:
    """删除用户，admin 账户受保护不可删除。返回 True 表示删除成功。"""
    if username == "admin":
        return False
    db = SessionLocal()
    user = db.query(User).filter_by(username=username).first()
    if not user:
        db.close()
        return False
    db.delete(user)
    db.commit()
    db.close()
    return True
