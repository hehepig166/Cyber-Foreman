from __future__ import annotations

from types import SimpleNamespace

import app.collectors.system_collector as collector
from app.collectors.system_collector import GpuStatus, collect_host_and_processes


class FakeProcess:
    def __init__(self, pid: int, name: str, username: str, rss: int, cmdline: list[str], cpu: float):
        self.info = {
            "pid": pid,
            "name": name,
            "username": username,
            "memory_info": SimpleNamespace(rss=rss),
            "cmdline": cmdline,
        }
        self._cpu = cpu

    def cpu_percent(self, interval=None) -> float:  # noqa: ANN001
        return self._cpu


def test_collect_gpu_status_when_nvml_missing(monkeypatch) -> None:
    monkeypatch.setattr(collector, "HAS_NVML", False)
    result = collector.collect_gpu_status()
    assert result.is_available is False
    assert result.error is not None


def test_collect_host_and_processes_sorted_and_limited(monkeypatch) -> None:
    fake_gpu_status = GpuStatus(
        gpu_util=80.0,
        gpu_mem_used_mb=1000.0,
        gpu_mem_total_mb=2000.0,
        device_samples=[],
        process_samples=[],
        is_available=True,
        error=None,
    )
    monkeypatch.setattr(collector, "collect_gpu_status", lambda timestamp=None: fake_gpu_status)  # noqa: ARG005
    monkeypatch.setattr(collector.psutil, "cpu_percent", lambda interval=None: 42.0)
    monkeypatch.setattr(collector.psutil, "virtual_memory", lambda: SimpleNamespace(percent=73.0))
    monkeypatch.setattr(collector.psutil, "getloadavg", lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(
        collector.psutil,
        "process_iter",
        lambda attrs=None: [  # noqa: ARG005
            FakeProcess(1, "p1", "u1", 100 * 1024 * 1024, ["cmd1"], 12.0),
            FakeProcess(2, "p2", "u2", 120 * 1024 * 1024, ["cmd2"], 99.0),
            FakeProcess(3, "p3", "u3", 110 * 1024 * 1024, ["cmd3"], 50.0),
        ],
    )

    host, processes, gpu_status = collect_host_and_processes(process_top_n=2)
    assert host.cpu_usage == 42.0
    assert host.mem_usage == 73.0
    assert host.gpu_util == 80.0
    assert len(processes) == 2
    assert [p.pid for p in processes] == [2, 3]
    assert gpu_status.is_available is True


def test_collect_host_and_processes_uses_single_timestamp_for_gpu(monkeypatch) -> None:
    captured = {"ts": None}

    def fake_collect_gpu_status(timestamp=None):  # noqa: ANN001
        captured["ts"] = timestamp
        return GpuStatus(
            gpu_util=10.0,
            gpu_mem_used_mb=100.0,
            gpu_mem_total_mb=1000.0,
            device_samples=[],
            process_samples=[],
            is_available=True,
            error=None,
        )

    monkeypatch.setattr(collector, "collect_gpu_status", fake_collect_gpu_status)
    monkeypatch.setattr(collector.psutil, "cpu_percent", lambda interval=None: 1.0)
    monkeypatch.setattr(collector.psutil, "virtual_memory", lambda: SimpleNamespace(percent=2.0))
    monkeypatch.setattr(collector.psutil, "getloadavg", lambda: (0.1, 0.2, 0.3))
    monkeypatch.setattr(collector.psutil, "process_iter", lambda attrs=None: [])  # noqa: ARG005

    host, _, _ = collect_host_and_processes(process_top_n=5)
    assert captured["ts"] == host.timestamp
