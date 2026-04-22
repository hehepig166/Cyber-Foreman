from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import delete

from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session, utcnow


def cleanup_old_samples(retention_days: Optional[int]) -> None:
    if retention_days is None:
        return
    cutoff = utcnow() - timedelta(days=retention_days)
    with get_session() as session:
        session.execute(delete(HostSample).where(HostSample.timestamp < cutoff))
        session.execute(delete(ProcessSample).where(ProcessSample.timestamp < cutoff))
        session.execute(delete(GpuProcessSample).where(GpuProcessSample.timestamp < cutoff))
        session.execute(delete(GpuDeviceSample).where(GpuDeviceSample.timestamp < cutoff))

