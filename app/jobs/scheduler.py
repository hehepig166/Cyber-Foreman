from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.collectors.system_collector import collect_host_and_processes
from app.config import Settings
from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session
from app.jobs.retention import cleanup_old_samples

logger = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    last_collection_error: Optional[str] = None
    last_gpu_error: Optional[str] = None
    samples_written: int = 0


class MonitorScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.scheduler = BackgroundScheduler()
        self.state = RuntimeState()
        self._lock = Lock()

    def start(self) -> None:
        self.scheduler.add_job(
            self.collect_and_persist,
            trigger=IntervalTrigger(seconds=self.settings.sample_interval_seconds),
            id="collect_metrics",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.cleanup_retention,
            trigger=IntervalTrigger(minutes=5),
            id="cleanup_retention",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        # Trigger first sample quickly to show data in UI.
        self.collect_and_persist()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def collect_and_persist(self) -> None:
        try:
            host_metrics, process_metrics, gpu_status = collect_host_and_processes(self.settings.process_top_n)

            with get_session() as session:
                session.add(
                    HostSample(
                        timestamp=host_metrics.timestamp,
                        cpu_usage=host_metrics.cpu_usage,
                        mem_usage=host_metrics.mem_usage,
                        load_1m=host_metrics.load_1m,
                        load_5m=host_metrics.load_5m,
                        load_15m=host_metrics.load_15m,
                        gpu_util=host_metrics.gpu_util,
                        gpu_mem_used_mb=host_metrics.gpu_mem_used_mb,
                        gpu_mem_total_mb=host_metrics.gpu_mem_total_mb,
                    )
                )
                session.add_all(
                    [
                        ProcessSample(
                            timestamp=p.timestamp,
                            pid=p.pid,
                            name=p.name,
                            user_name=p.user_name,
                            cpu_percent=p.cpu_percent,
                            rss_mb=p.rss_mb,
                            cmdline=p.cmdline,
                        )
                        for p in process_metrics
                    ]
                )
                session.add_all(
                    [
                        GpuDeviceSample(
                            timestamp=d.timestamp,
                            gpu_uuid=d.gpu_uuid,
                            gpu_index=d.gpu_index,
                            gpu_name=d.gpu_name,
                            gpu_util=d.gpu_util,
                            gpu_mem_used_mb=d.gpu_mem_used_mb,
                            gpu_mem_total_mb=d.gpu_mem_total_mb,
                            process_count=d.process_count,
                        )
                        for d in gpu_status.device_samples
                    ]
                )
                session.add_all(
                    [
                        GpuProcessSample(
                            timestamp=g.timestamp,
                            gpu_uuid=g.gpu_uuid,
                            gpu_index=g.gpu_index,
                            pid=g.pid,
                            process_name=g.process_name,
                            user_name=g.user_name,
                            cmdline=g.cmdline,
                            used_gpu_memory_mb=g.used_gpu_memory_mb,
                        )
                        for g in gpu_status.process_samples
                    ]
                )
            with self._lock:
                self.state.samples_written += 1
                self.state.last_collection_error = None
                self.state.last_gpu_error = gpu_status.error
        except Exception as exc:
            logger.exception("collect_and_persist failed")
            with self._lock:
                self.state.last_collection_error = str(exc)

    def cleanup_retention(self) -> None:
        try:
            cleanup_old_samples(self.settings.retention_days)
        except Exception:
            logger.exception("cleanup_retention failed")

    def get_runtime_state(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(
                last_collection_error=self.state.last_collection_error,
                last_gpu_error=self.state.last_gpu_error,
                samples_written=self.state.samples_written,
            )

