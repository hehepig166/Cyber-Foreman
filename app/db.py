from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class HostSample(Base):
    __tablename__ = "host_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    cpu_usage: Mapped[float] = mapped_column(Float, nullable=False)
    mem_usage: Mapped[float] = mapped_column(Float, nullable=False)
    load_1m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    load_5m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    load_15m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gpu_util: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gpu_mem_used_mb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gpu_mem_total_mb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ProcessSample(Base):
    __tablename__ = "process_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False)
    rss_mb: Mapped[float] = mapped_column(Float, nullable=False)
    cmdline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GpuProcessSample(Base):
    __tablename__ = "gpu_process_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    gpu_uuid: Mapped[str] = mapped_column(String(128), nullable=False)
    gpu_index: Mapped[int] = mapped_column(Integer, nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    process_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cmdline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    used_gpu_memory_mb: Mapped[float] = mapped_column(Float, nullable=False)


class GpuDeviceSample(Base):
    __tablename__ = "gpu_device_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    gpu_uuid: Mapped[str] = mapped_column(String(128), nullable=False)
    gpu_index: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    gpu_util: Mapped[float] = mapped_column(Float, nullable=False)
    gpu_mem_used_mb: Mapped[float] = mapped_column(Float, nullable=False)
    gpu_mem_total_mb: Mapped[float] = mapped_column(Float, nullable=False)
    process_count: Mapped[int] = mapped_column(Integer, nullable=False)


class RetentionConfig(Base):
    __tablename__ = "retention_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    retention_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


Index("idx_host_samples_timestamp", HostSample.timestamp)
Index("idx_process_samples_timestamp", ProcessSample.timestamp)
Index("idx_gpu_process_samples_timestamp", GpuProcessSample.timestamp)
Index("idx_gpu_device_samples_timestamp", GpuDeviceSample.timestamp)

_ENGINE = None
_SessionLocal = None


def init_database(db_path: Path) -> None:
    global _ENGINE, _SessionLocal
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ENGINE = create_engine(f"sqlite:///{db_path}", future=True)
    _SessionLocal = sessionmaker(
        bind=_ENGINE,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False,
    )
    Base.metadata.create_all(_ENGINE)
    _apply_sqlite_migrations(_ENGINE)


def _apply_sqlite_migrations(engine) -> None:  # noqa: ANN001
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info('gpu_process_samples')")).fetchall()}
        if "user_name" not in columns:
            conn.execute(text("ALTER TABLE gpu_process_samples ADD COLUMN user_name VARCHAR(200)"))
        if "cmdline" not in columns:
            conn.execute(text("ALTER TABLE gpu_process_samples ADD COLUMN cmdline TEXT"))


@contextmanager
def get_session() -> Iterator:
    if _SessionLocal is None:
        raise RuntimeError("Database is not initialized.")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

