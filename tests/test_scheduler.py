from __future__ import annotations

from dataclasses import replace
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


def test_build_gpu_report_text_and_send(initialized_db, test_settings, monkeypatch) -> None:
    _ = initialized_db
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(
            HostSample(
                timestamp=now,
                cpu_usage=1.0,
                mem_usage=2.0,
                load_1m=0.1,
                load_5m=0.2,
                load_15m=0.3,
                gpu_util=50.0,
                gpu_mem_used_mb=1024.0,
                gpu_mem_total_mb=2048.0,
            )
        )
        session.add(
            GpuDeviceSample(
                timestamp=now,
                gpu_uuid="gpu0",
                gpu_index=0,
                gpu_name="GPU0",
                gpu_util=66.6,
                gpu_mem_used_mb=3000.0,
                gpu_mem_total_mb=10000.0,
                process_count=2,
            )
        )
        session.add(
            GpuDeviceSample(
                timestamp=now,
                gpu_uuid="gpu1",
                gpu_index=1,
                gpu_name="GPU1",
                gpu_util=0.0,
                gpu_mem_used_mb=128.0,
                gpu_mem_total_mb=10000.0,
                process_count=1,
            )
        )

    called: dict[str, str] = {}

    def fake_send(url: str, text: str, timeout_seconds: int) -> None:
        called["url"] = url
        called["text"] = text
        called["timeout"] = str(timeout_seconds)

    monkeypatch.setattr(scheduler_module, "send_text_message", fake_send)
    monkeypatch.setenv("FEISHU_BOT_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/mock")
    scheduler = MonitorScheduler(replace(test_settings, feishu_enabled=True))
    scheduler.report_gpu_to_feishu()

    assert called["url"].endswith("/mock")
    assert "每卡详情:" in called["text"]
    assert "🌖 GPU0:" in called["text"]
    assert "66.6%" in called["text"]
    assert "2.93/9.77" in called["text"]
    assert "GB" in called["text"]
    assert "进程 2" in called["text"]
    assert "🌑 GPU1:" in called["text"]
    assert "⚪ GPU7: 计算 --.-% | 显存 --/-- GB (--.-%)" in called["text"]
    assert "(Asia/Shanghai)" in called["text"]
    assert called["timeout"] == "5"


def test_report_gpu_to_feishu_skip_when_webhook_missing(test_settings, monkeypatch) -> None:
    called = {"count": 0}

    def fake_send(url: str, text: str, timeout_seconds: int) -> None:  # noqa: ARG001
        called["count"] += 1

    monkeypatch.setattr(scheduler_module, "send_text_message", fake_send)
    monkeypatch.delenv("FEISHU_BOT_WEBHOOK", raising=False)
    scheduler = MonitorScheduler(replace(test_settings, feishu_enabled=True))
    scheduler.report_gpu_to_feishu()
    assert called["count"] == 0


def test_build_gpu_report_text_fallback_to_utc_when_timezone_invalid(initialized_db, test_settings) -> None:
    _ = initialized_db
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(
            HostSample(
                timestamp=now,
                cpu_usage=1.0,
                mem_usage=2.0,
                load_1m=0.1,
                load_5m=0.2,
                load_15m=0.3,
                gpu_util=50.0,
                gpu_mem_used_mb=1024.0,
                gpu_mem_total_mb=2048.0,
            )
        )

    scheduler = MonitorScheduler(replace(test_settings, feishu_timezone="Invalid/Timezone"))
    text = scheduler.build_gpu_report_text()
    assert "(UTC)" in text
