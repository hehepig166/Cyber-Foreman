from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session, utcnow
from app.jobs.retention import cleanup_old_samples


def test_cleanup_old_samples_deletes_only_expired(initialized_db) -> None:
    _ = initialized_db
    old_ts = utcnow() - timedelta(days=40)
    new_ts = utcnow() - timedelta(days=5)
    with get_session() as session:
        session.add_all(
            [
                HostSample(timestamp=old_ts, cpu_usage=1.0, mem_usage=1.0, load_1m=None, load_5m=None, load_15m=None, gpu_util=None, gpu_mem_used_mb=None, gpu_mem_total_mb=None),
                HostSample(timestamp=new_ts, cpu_usage=2.0, mem_usage=2.0, load_1m=None, load_5m=None, load_15m=None, gpu_util=None, gpu_mem_used_mb=None, gpu_mem_total_mb=None),
                ProcessSample(timestamp=old_ts, pid=100, name="old", user_name="u", cpu_percent=1.0, rss_mb=10.0, cmdline="old"),
                ProcessSample(timestamp=new_ts, pid=101, name="new", user_name="u", cpu_percent=1.0, rss_mb=10.0, cmdline="new"),
                GpuProcessSample(timestamp=old_ts, gpu_uuid="gpu0", gpu_index=0, pid=100, process_name="old", used_gpu_memory_mb=100.0),
                GpuProcessSample(timestamp=new_ts, gpu_uuid="gpu0", gpu_index=0, pid=101, process_name="new", used_gpu_memory_mb=200.0),
                GpuDeviceSample(
                    timestamp=old_ts,
                    gpu_uuid="gpu0",
                    gpu_index=0,
                    gpu_name="GPU0",
                    gpu_util=30.0,
                    gpu_mem_used_mb=100.0,
                    gpu_mem_total_mb=1000.0,
                    process_count=1,
                ),
                GpuDeviceSample(
                    timestamp=new_ts,
                    gpu_uuid="gpu0",
                    gpu_index=0,
                    gpu_name="GPU0",
                    gpu_util=40.0,
                    gpu_mem_used_mb=200.0,
                    gpu_mem_total_mb=1000.0,
                    process_count=2,
                ),
            ]
        )

    cleanup_old_samples(retention_days=30)

    with get_session() as session:
        assert len(list(session.execute(select(HostSample)).scalars())) == 1
        assert len(list(session.execute(select(ProcessSample)).scalars())) == 1
        assert len(list(session.execute(select(GpuProcessSample)).scalars())) == 1
        assert len(list(session.execute(select(GpuDeviceSample)).scalars())) == 1


def test_cleanup_old_samples_disabled_when_none(initialized_db) -> None:
    _ = initialized_db
    with get_session() as session:
        session.add(
            HostSample(
                timestamp=utcnow() - timedelta(days=60),
                cpu_usage=1.0,
                mem_usage=1.0,
                load_1m=None,
                load_5m=None,
                load_15m=None,
                gpu_util=None,
                gpu_mem_used_mb=None,
                gpu_mem_total_mb=None,
            )
        )

    cleanup_old_samples(retention_days=None)

    with get_session() as session:
        assert session.execute(select(HostSample)).scalar_one_or_none() is not None
