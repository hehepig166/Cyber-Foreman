from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

import app.jobs.scheduler as scheduler_module
from app.collectors.system_collector import GpuDeviceMetrics, GpuProcessMetrics, GpuStatus, HostMetrics, ProcessMetrics
from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session
from app.jobs.scheduler import MonitorScheduler


def test_collect_and_persist_writes_samples(initialized_db, test_settings, monkeypatch) -> None:
    _ = initialized_db
    now = datetime.now(timezone.utc)
    host = HostMetrics(
        timestamp=now,
        cpu_usage=20.0,
        mem_usage=40.0,
        load_1m=1.0,
        load_5m=1.2,
        load_15m=1.5,
        gpu_util=70.0,
        gpu_mem_used_mb=2000.0,
        gpu_mem_total_mb=4000.0,
    )
    processes = [
        ProcessMetrics(timestamp=now, pid=10, name="proc", user_name="root", cpu_percent=88.0, rss_mb=256.0, cmdline="python run.py")
    ]
    gpu_status = GpuStatus(
        gpu_util=70.0,
        gpu_mem_used_mb=2000.0,
        gpu_mem_total_mb=4000.0,
        device_samples=[
            GpuDeviceMetrics(
                timestamp=now,
                gpu_uuid="gpu0",
                gpu_index=0,
                gpu_name="NVIDIA H100",
                gpu_util=71.0,
                gpu_mem_used_mb=2010.0,
                gpu_mem_total_mb=4000.0,
                process_count=1,
            )
        ],
        process_samples=[
            GpuProcessMetrics(
                timestamp=now,
                gpu_uuid="gpu0",
                gpu_index=0,
                pid=10,
                process_name="proc",
                user_name="root",
                cmdline="python train.py --epochs 10",
                used_gpu_memory_mb=512.0,
            )
        ],
        is_available=True,
        error=None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "collect_host_and_processes",
        lambda process_top_n: (host, processes, gpu_status),  # noqa: ARG005
    )

    scheduler = MonitorScheduler(test_settings)
    scheduler.collect_and_persist()

    with get_session() as session:
        assert session.execute(select(HostSample)).scalar_one_or_none() is not None
        assert session.execute(select(ProcessSample)).scalar_one_or_none() is not None
        gpu_process = session.execute(select(GpuProcessSample)).scalar_one_or_none()
        assert gpu_process is not None
        assert gpu_process.user_name == "root"
        assert gpu_process.cmdline == "python train.py --epochs 10"
        device = session.execute(select(GpuDeviceSample)).scalar_one_or_none()
        assert device is not None
        assert device.gpu_name == "NVIDIA H100"
        assert device.process_count == 1
    assert scheduler.get_runtime_state().samples_written == 1


def test_collect_and_persist_records_error(test_settings, monkeypatch) -> None:
    monkeypatch.setattr(
        scheduler_module,
        "collect_host_and_processes",
        lambda process_top_n: (_ for _ in ()).throw(RuntimeError("boom")),  # noqa: ARG005
    )
    scheduler = MonitorScheduler(test_settings)
    scheduler.collect_and_persist()
    assert "boom" in (scheduler.get_runtime_state().last_collection_error or "")
