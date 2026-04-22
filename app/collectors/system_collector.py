from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import psutil

try:
    import pynvml

    HAS_NVML = True
except Exception:
    pynvml = None
    HAS_NVML = False


@dataclass
class HostMetrics:
    timestamp: datetime
    cpu_usage: float
    mem_usage: float
    load_1m: Optional[float]
    load_5m: Optional[float]
    load_15m: Optional[float]
    gpu_util: Optional[float]
    gpu_mem_used_mb: Optional[float]
    gpu_mem_total_mb: Optional[float]


@dataclass
class ProcessMetrics:
    timestamp: datetime
    pid: int
    name: str
    user_name: Optional[str]
    cpu_percent: float
    rss_mb: float
    cmdline: Optional[str]


@dataclass
class GpuProcessMetrics:
    timestamp: datetime
    gpu_uuid: str
    gpu_index: int
    pid: int
    process_name: Optional[str]
    user_name: Optional[str]
    cmdline: Optional[str]
    used_gpu_memory_mb: float


@dataclass
class GpuDeviceMetrics:
    timestamp: datetime
    gpu_uuid: str
    gpu_index: int
    gpu_name: Optional[str]
    gpu_util: float
    gpu_mem_used_mb: float
    gpu_mem_total_mb: float
    process_count: int


@dataclass
class GpuStatus:
    gpu_util: Optional[float]
    gpu_mem_used_mb: Optional[float]
    gpu_mem_total_mb: Optional[float]
    device_samples: list[GpuDeviceMetrics]
    process_samples: list[GpuProcessMetrics]
    is_available: bool
    error: Optional[str]


_nvml_initialized = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _initialize_nvml() -> None:
    global _nvml_initialized
    if not HAS_NVML or _nvml_initialized:
        return
    pynvml.nvmlInit()
    _nvml_initialized = True


def collect_gpu_status(timestamp: Optional[datetime] = None) -> GpuStatus:
    if not HAS_NVML:
        return GpuStatus(None, None, None, [], [], False, "NVML Python binding is not installed.")

    try:
        _initialize_nvml()
        count = pynvml.nvmlDeviceGetCount()
        if count == 0:
            return GpuStatus(None, None, None, [], [], False, "No NVIDIA GPU devices found.")

        total_util = 0.0
        total_used_mem_mb = 0.0
        total_mem_mb = 0.0
        all_device_samples: list[GpuDeviceMetrics] = []
        all_gpu_processes: list[GpuProcessMetrics] = []

        sample_timestamp = timestamp or _utcnow()
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            uuid = pynvml.nvmlDeviceGetUUID(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(uuid, bytes):
                uuid = uuid.decode("utf-8", errors="ignore")
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")

            total_util += float(util.gpu)
            total_used_mem_mb += float(mem.used) / (1024 * 1024)
            total_mem_mb += float(mem.total) / (1024 * 1024)

            try:
                compute_processes = pynvml.nvmlDeviceGetComputeRunningProcesses_v3(handle)
            except Exception:
                compute_processes = []
            try:
                graphics_processes = pynvml.nvmlDeviceGetGraphicsRunningProcesses_v3(handle)
            except Exception:
                graphics_processes = []

            process_ids = {proc.pid for proc in [*compute_processes, *graphics_processes]}
            all_device_samples.append(
                GpuDeviceMetrics(
                    timestamp=sample_timestamp,
                    gpu_uuid=uuid,
                    gpu_index=index,
                    gpu_name=name,
                    gpu_util=float(util.gpu),
                    gpu_mem_used_mb=float(mem.used) / (1024 * 1024),
                    gpu_mem_total_mb=float(mem.total) / (1024 * 1024),
                    process_count=len(process_ids),
                )
            )

            for proc in [*compute_processes, *graphics_processes]:
                process_name: Optional[str] = None
                user_name: Optional[str] = None
                cmdline: Optional[str] = None
                try:
                    ps_process = psutil.Process(proc.pid)
                    process_name = ps_process.name()
                    user_name = ps_process.username()
                    raw_cmdline = ps_process.cmdline()
                    cmdline = " ".join(raw_cmdline) if raw_cmdline else None
                except Exception:
                    process_name = None
                    user_name = None
                    cmdline = None
                used_gpu_memory_mb = max(0.0, float(proc.usedGpuMemory) / (1024 * 1024))
                all_gpu_processes.append(
                    GpuProcessMetrics(
                        timestamp=sample_timestamp,
                        gpu_uuid=uuid,
                        gpu_index=index,
                        pid=proc.pid,
                        process_name=process_name,
                        user_name=user_name,
                        cmdline=cmdline,
                        used_gpu_memory_mb=used_gpu_memory_mb,
                    )
                )

        average_util = total_util / count
        return GpuStatus(
            gpu_util=average_util,
            gpu_mem_used_mb=total_used_mem_mb,
            gpu_mem_total_mb=total_mem_mb,
            device_samples=all_device_samples,
            process_samples=all_gpu_processes,
            is_available=True,
            error=None,
        )
    except Exception as exc:
        return GpuStatus(None, None, None, [], [], False, str(exc))


def collect_host_and_processes(process_top_n: int) -> tuple[HostMetrics, list[ProcessMetrics], GpuStatus]:
    timestamp = _utcnow()
    cpu_usage = float(psutil.cpu_percent(interval=None))
    mem_usage = float(psutil.virtual_memory().percent)

    load_1m: Optional[float]
    load_5m: Optional[float]
    load_15m: Optional[float]
    try:
        load_1m, load_5m, load_15m = psutil.getloadavg()
    except Exception:
        load_1m = None
        load_5m = None
        load_15m = None

    gpu_status = collect_gpu_status(timestamp=timestamp)

    host_metrics = HostMetrics(
        timestamp=timestamp,
        cpu_usage=cpu_usage,
        mem_usage=mem_usage,
        load_1m=load_1m,
        load_5m=load_5m,
        load_15m=load_15m,
        gpu_util=gpu_status.gpu_util,
        gpu_mem_used_mb=gpu_status.gpu_mem_used_mb,
        gpu_mem_total_mb=gpu_status.gpu_mem_total_mb,
    )

    process_samples: list[ProcessMetrics] = []
    for proc in psutil.process_iter(attrs=["pid", "name", "username", "memory_info", "cmdline"]):
        try:
            cpu_percent = float(proc.cpu_percent(interval=None))
            memory_info = proc.info.get("memory_info")
            rss_mb = float(memory_info.rss) / (1024 * 1024) if memory_info else 0.0
            cmdline = proc.info.get("cmdline")
            cmdline_str = " ".join(cmdline) if cmdline else None
            process_samples.append(
                ProcessMetrics(
                    timestamp=timestamp,
                    pid=int(proc.info["pid"]),
                    name=str(proc.info.get("name") or "unknown"),
                    user_name=proc.info.get("username"),
                    cpu_percent=cpu_percent,
                    rss_mb=rss_mb,
                    cmdline=cmdline_str,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    process_samples.sort(key=lambda x: x.cpu_percent, reverse=True)
    return host_metrics, process_samples[:process_top_n], gpu_status

