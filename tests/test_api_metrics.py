from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.metrics import router
from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session, utcnow
from app.jobs.scheduler import RuntimeState


class DummyScheduler:
    class _SchedulerInner:
        running = True

    def __init__(self) -> None:
        self.scheduler = self._SchedulerInner()

    def get_runtime_state(self) -> RuntimeState:
        return RuntimeState(last_collection_error=None, last_gpu_error=None, samples_written=3)

    def build_gpu_report_text(self) -> str:
        return "GPU 小时巡检（采样时间: 2026-04-22 03:00:00 UTC）\nGPU0: 计算占用 10.0% | 显存占用 100/1000 MB (10.0%)"


def create_test_app(test_settings) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = test_settings
    app.state.monitor_scheduler = DummyScheduler()
    return app


def seed_metrics_data() -> None:
    now = utcnow()
    with get_session() as session:
        session.add(
            HostSample(
                timestamp=now,
                cpu_usage=11.0,
                mem_usage=22.0,
                load_1m=1.0,
                load_5m=2.0,
                load_15m=3.0,
                gpu_util=44.0,
                gpu_mem_used_mb=1000.0,
                gpu_mem_total_mb=2000.0,
            )
        )
        session.add(
            HostSample(
                timestamp=now - timedelta(minutes=30),
                cpu_usage=12.0,
                mem_usage=23.0,
                load_1m=1.1,
                load_5m=2.1,
                load_15m=3.1,
                gpu_util=45.0,
                gpu_mem_used_mb=1001.0,
                gpu_mem_total_mb=2000.0,
            )
        )
        session.add(
            ProcessSample(
                timestamp=now,
                pid=123,
                name="python",
                user_name="root",
                cpu_percent=88.0,
                rss_mb=512.0,
                cmdline="python app.py",
            )
        )
        session.add(
            GpuProcessSample(
                timestamp=now,
                gpu_uuid="gpu0",
                gpu_index=0,
                pid=123,
                process_name="python",
                user_name="root",
                cmdline="python train.py --model x",
                used_gpu_memory_mb=200.0,
            )
        )
        session.add(
            GpuDeviceSample(
                timestamp=now,
                gpu_uuid="gpu0",
                gpu_index=0,
                gpu_name="GPU0",
                gpu_util=44.0,
                gpu_mem_used_mb=1000.0,
                gpu_mem_total_mb=2000.0,
                process_count=1,
            )
        )


def test_metrics_endpoints(initialized_db, test_settings) -> None:
    _ = initialized_db
    seed_metrics_data()
    client = TestClient(create_test_app(test_settings))

    snapshot = client.get("/api/metrics/snapshot?limit=5")
    assert snapshot.status_code == 200
    assert snapshot.json()["host"]["cpu_usage"] == 11.0
    assert snapshot.json()["gpu_devices"][0]["gpu_index"] == 0

    history = client.get("/api/metrics/history?range_window=1h")
    assert history.status_code == 200
    assert len(history.json()["points"]) >= 2

    current_processes = client.get("/api/metrics/processes/current")
    assert current_processes.status_code == 200
    assert current_processes.json()["processes"][0]["pid"] == 123

    current_gpu = client.get("/api/metrics/gpu-processes/current")
    assert current_gpu.status_code == 200
    assert current_gpu.json()["gpu_processes"][0]["pid"] == 123
    assert current_gpu.json()["gpu_processes"][0]["user_name"] == "root"
    assert current_gpu.json()["gpu_processes"][0]["cmdline"] == "python train.py --model x"

    current_gpu_devices = client.get("/api/metrics/gpu-devices/current")
    assert current_gpu_devices.status_code == 200
    assert current_gpu_devices.json()["gpu_devices"][0]["gpu_name"] == "GPU0"

    status = client.get("/api/metrics/status")
    assert status.status_code == 200
    assert status.json()["samples_written"] == 3

    preview = client.get("/api/metrics/feishu-preview")
    assert preview.status_code == 200
    assert preview.json()["ready"] is True
    assert "GPU0: 计算占用 10.0%" in preview.json()["text"]

    config = client.get("/api/metrics/config")
    assert config.status_code == 200
    assert config.json()["server_port"] == test_settings.server_port


def test_history_invalid_range_returns_400(initialized_db, test_settings) -> None:
    _ = initialized_db
    client = TestClient(create_test_app(test_settings))
    resp = client.get("/api/metrics/history?range_window=abc")
    assert resp.status_code == 400


def test_gpu_devices_current_empty_when_no_samples(initialized_db, test_settings) -> None:
    _ = initialized_db
    client = TestClient(create_test_app(test_settings))
    resp = client.get("/api/metrics/gpu-devices/current")
    assert resp.status_code == 200
    assert resp.json() == {"gpu_devices": []}
