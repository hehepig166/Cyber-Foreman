from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import app.db as db_module
from app.db import HostSample, get_session


def test_get_session_requires_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_module, "_SessionLocal", None)
    with pytest.raises(RuntimeError):
        with get_session():
            pass


def test_insert_and_query_host_sample(initialized_db) -> None:
    _ = initialized_db
    timestamp = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(
            HostSample(
                timestamp=timestamp,
                cpu_usage=10.0,
                mem_usage=20.0,
                load_1m=1.0,
                load_5m=1.2,
                load_15m=1.4,
                gpu_util=30.0,
                gpu_mem_used_mb=1024.0,
                gpu_mem_total_mb=4096.0,
            )
        )

    with get_session() as session:
        saved = session.execute(select(HostSample)).scalar_one()
        assert saved.cpu_usage == 10.0
        assert saved.mem_usage == 20.0
        assert saved.timestamp.replace(tzinfo=timezone.utc) == timestamp
