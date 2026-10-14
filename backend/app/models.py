from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from .core import settings, uid, now

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default='admin')

class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default='organizer')
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

class Article(Base):
    __tablename__ = 'articles'
    __table_args__ = (UniqueConstraint('dataset_id', 'original_id', 'content_hash'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id'), index=True)
    original_id: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(Text, default='')
    text: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(255), default='')
    url: Mapped[str] = mapped_column(Text, default='')
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    original: Mapped[dict] = mapped_column(JSONB)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

class Source(Base):
    __tablename__ = 'sources'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    url: Mapped[str] = mapped_column(Text)
    feed_url: Mapped[str] = mapped_column(Text, default='')
    publisher_type: Mapped[str] = mapped_column(String(30), default='media')
    agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

class Run(Base):
    __tablename__ = 'processing_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id'), index=True)
    mode: Mapped[str] = mapped_column(String(20))
    control_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    snapshot: Mapped[list] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    decisions: Mapped[list] = mapped_column(JSONB, default=list)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey('processing_runs.id'), index=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean)
    data: Mapped[dict] = mapped_column(JSONB)

class ArticleEvent(Base):
    __tablename__ = 'article_event_links'
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id'), primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey('articles.id'), primary_key=True)

class Claim(Base):
    __tablename__ = 'claims'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey('events.id'), index=True)
    article_id: Mapped[str] = mapped_column(ForeignKey('articles.id'), index=True)
    text: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)

class Digest(Base):
    __tablename__ = 'digests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey('processing_runs.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default='draft')
    data: Mapped[dict] = mapped_column(JSONB)
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(80), default='В очереди')
    progress: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ModelCall(Base):
    __tablename__ = 'model_calls'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(30), default='1.0')
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Schedule(Base):
    __tablename__ = 'schedules'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    hour: Mapped[int] = mapped_column(Integer, default=9)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default='live')
    next_run: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Subscriber(Base):
    __tablename__ = 'test_subscribers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255), default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Audit(Base):
    __tablename__ = 'audit_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)
