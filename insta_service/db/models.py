import logging
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Text, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

log = logging.getLogger(__name__)

from insta_service.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    first_seen_hashtag = Column(String)
    crawled_at = Column(DateTime, default=datetime.utcnow)
    is_analyzed = Column(Boolean, default=False)
    is_dm_sent = Column(Boolean, default=False)

    hashtags = relationship("UserHashtag", back_populates="user")
    profile = relationship("UserProfile", uselist=False, back_populates="user")
    dm_history = relationship("DmHistory", back_populates="user")


class UserHashtag(Base):
    __tablename__ = "user_hashtags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    hashtag = Column(String, nullable=False, index=True)
    crawled_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="hashtags")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    followers_count = Column(Integer)
    following_count = Column(Integer)
    posts_count = Column(Integer)
    display_name = Column(String)
    bio = Column(Text)
    is_private = Column(Boolean)
    is_verified = Column(Boolean)
    profile_pic_url = Column(Text)
    last_post_date = Column(DateTime)
    analyzed_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="profile")


class InstagramAccount(Base):
    __tablename__ = "instagram_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_encrypted = Column(String, nullable=False)
    account_type = Column(String, default="crawl")  # crawl / dm / both
    proxy_id = Column(Integer, ForeignKey("proxies.id"), nullable=True)
    chrome_profile_path = Column(String)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime)
    daily_dm_limit = Column(Integer, default=30)
    dm_sent_today = Column(Integer, default=0)
    status = Column(String, default="active")  # active / limited / banned
    created_at = Column(DateTime, default=datetime.utcnow)

    proxy = relationship("Proxy", back_populates="accounts")
    dm_history = relationship("DmHistory", back_populates="sender_account")


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String)
    password = Column(String)
    is_active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime)
    response_time_ms = Column(Integer)

    accounts = relationship("InstagramAccount", back_populates="proxy")


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hashtag = Column(String, nullable=False)
    target_count = Column(Integer)
    collected_count = Column(Integer, default=0)
    status = Column(String, default="pending", index=True)  # pending/running/completed/failed/cancelled
    account_id = Column(Integer, ForeignKey("instagram_accounts.id"), nullable=True)
    scheduled_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class DmTemplate(Base):
    __tablename__ = "dm_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    message_body = Column(Text, nullable=False)
    image_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DmHistory(Base):
    __tablename__ = "dm_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    sender_account_id = Column(Integer, ForeignKey("instagram_accounts.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("dm_templates.id"), nullable=True)
    message_text = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending", index=True)  # pending/sent/failed/blocked
    error_message = Column(Text)

    user = relationship("User", back_populates="dm_history")
    sender_account = relationship("InstagramAccount", back_populates="dm_history")


class Blacklist(Base):
    __tablename__ = "blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class LicenseInfo(Base):
    __tablename__ = "license_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    license_key = Column(String, unique=True, nullable=False)
    company_name = Column(String)
    plan = Column(String, default="basic")
    activated_at = Column(DateTime)
    expires_at = Column(DateTime)
    max_crawl_accounts = Column(Integer, default=1)
    max_dm_accounts = Column(Integer, default=1)
    max_daily_dm = Column(Integer, default=50)
    max_hashtags = Column(Integer, default=5)
    can_schedule = Column(Boolean, default=False)
    can_analyze = Column(Boolean, default=False)
    can_export = Column(Boolean, default=False)
    last_heartbeat = Column(DateTime)


def init_db():
    """테이블이 없으면 생성하고, 기존 테이블에 누락된 컬럼이 있으면 추가한다."""
    Base.metadata.create_all(engine)
    _migrate_license_info()
    _migrate_dm_templates()
    _migrate_crawl_jobs()
    _migrate_user_profiles()


def _add_columns_if_missing(table: str, columns: dict[str, str]):
    """테이블에 누락된 컬럼을 ALTER TABLE로 추가한다."""
    import sqlite3
    from insta_service.config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}

        for col, col_type in columns.items():
            if col not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                log.debug(f"마이그레이션: {table}.{col} 컬럼 추가")

        conn.commit()
    except Exception as e:
        log.error(f"마이그레이션 실패 ({table}): {e}")
    finally:
        conn.close()


def _migrate_license_info():
    _add_columns_if_missing("license_info", {
        "plan": 'VARCHAR DEFAULT "basic"',
        "max_crawl_accounts": "INTEGER DEFAULT 1",
        "max_dm_accounts": "INTEGER DEFAULT 1",
        "max_hashtags": "INTEGER DEFAULT 5",
        "can_schedule": "BOOLEAN DEFAULT 0",
        "can_analyze": "BOOLEAN DEFAULT 0",
        "can_export": "BOOLEAN DEFAULT 0",
        "last_heartbeat": "DATETIME",
    })


def _migrate_crawl_jobs():
    _add_columns_if_missing("crawl_jobs", {"error_message": "TEXT"})


def _migrate_user_profiles():
    _add_columns_if_missing("user_profiles", {"display_name": "VARCHAR"})


def _migrate_dm_templates():
    _add_columns_if_missing("dm_templates", {"image_path": "VARCHAR"})
