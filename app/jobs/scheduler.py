from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timezone
from threading import Lock
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import desc, select

from app.collectors.system_collector import collect_host_and_processes
from app.config import Settings
from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session
from app.jobs.retention import cleanup_old_samples
from app.notifications.feishu import send_text_message

logger = logging.getLogger(__name__)


def _mask_webhook_url(webhook_url: str) -> str:
    if not webhook_url:
        return ""
    if len(webhook_url) <= 16:
        return f"{webhook_url[:4]}***"
    return f"{webhook_url[:16]}...{webhook_url[-6:]}"


def _gpu_util_emoji(util: float | None) -> str:
    if util is None:
        return "⚪"
    normalized_util = max(0.0, round(util, 2))
    if normalized_util == 0.0:
        return "🌑"
    if normalized_util < 20:
        return "🌘"
    if normalized_util < 60:
        return "🌗"
    if normalized_util < 80:
        return "🌖"
    return "🌕"


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
        if self.settings.feishu_enabled:
            self.scheduler.add_job(
                self.report_gpu_to_feishu,
                trigger=IntervalTrigger(seconds=self.settings.feishu_report_interval_seconds),
                id="report_gpu_to_feishu",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "Feishu report job enabled: interval=%ss env_var=%s timeout=%ss",
                self.settings.feishu_report_interval_seconds,
                self.settings.feishu_webhook_env_var,
                self.settings.feishu_timeout_seconds,
            )
        else:
            logger.info("Feishu report job disabled by config.")
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

    def build_gpu_report_text(self) -> str:
        with get_session() as session:
            latest_host = session.execute(
                select(HostSample).order_by(desc(HostSample.timestamp)).limit(1)
            ).scalar_one_or_none()
            if latest_host is None:
                return "GPU 小时巡检：暂无样本。"
            latest_ts = latest_host.timestamp
            rows = session.execute(
                select(GpuDeviceSample)
                .where(GpuDeviceSample.timestamp == latest_ts)
                .order_by(GpuDeviceSample.gpu_index.asc())
            ).scalars()
            samples = {row.gpu_index: row for row in rows}

        local_time = latest_ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        total_mem_used = latest_host.gpu_mem_used_mb or 0.0
        total_mem = latest_host.gpu_mem_total_mb or 0.0
        total_mem_pct = (total_mem_used / total_mem * 100) if total_mem > 0 else 0.0
        total_mem_used_gb = total_mem_used / 1024
        total_mem_gb = total_mem / 1024

        lines = [
            f"GPU 定时巡检 | {local_time}",
            "----------------------------------------",
            "总体: "
            f"GPU {latest_host.gpu_util if latest_host.gpu_util is not None else '-'}% | "
            f"显存 {total_mem_used_gb:.2f}/{total_mem_gb:.2f} GB ({total_mem_pct:.1f}%)",
            "",
            "每卡详情:",
        ]
        for gpu_index in range(8):
            sample = samples.get(gpu_index)
            if sample is None:
                lines.append(f"⚪ GPU{gpu_index}: 计算 --.-% | 显存 --/-- GB (--.-%)")
                continue
            mem_pct = 0.0
            if sample.gpu_mem_total_mb > 0:
                mem_pct = sample.gpu_mem_used_mb / sample.gpu_mem_total_mb * 100
            used_gb = sample.gpu_mem_used_mb / 1024
            total_gb = sample.gpu_mem_total_mb / 1024
            level_emoji = _gpu_util_emoji(sample.gpu_util)
            lines.append(
                "{emoji} GPU{idx}: 计算 {util:>5.1f}% | 显存 {used:>6.2f}/{total:<6.2f} GB ({mem_pct:>5.1f}%) | 进程 {proc_count}".format(
                    emoji=level_emoji,
                    idx=gpu_index,
                    util=sample.gpu_util,
                    used=used_gb,
                    total=total_gb,
                    mem_pct=mem_pct,
                    proc_count=sample.process_count,
                )
            )
        return "\n".join(lines)

    def report_gpu_to_feishu(self) -> None:
        logger.info(
            "Feishu report trigger fired. env_var=%s",
            self.settings.feishu_webhook_env_var,
        )
        webhook_url = os.getenv(self.settings.feishu_webhook_env_var, "").strip()
        if not webhook_url:
            logger.warning(
                "Feishu report skipped: env var %s is empty.",
                self.settings.feishu_webhook_env_var,
            )
            return
        try:
            report_text = self.build_gpu_report_text()
            logger.info(
                "Feishu report sending: webhook=%s text_length=%s",
                _mask_webhook_url(webhook_url),
                len(report_text),
            )
            send_text_message(webhook_url, report_text, timeout_seconds=self.settings.feishu_timeout_seconds)
            logger.info("Feishu report sent successfully.")
        except Exception as exc:
            logger.exception("Feishu report failed: %s", exc)

    def get_runtime_state(self) -> RuntimeState:
        with self._lock:
            return RuntimeState(
                last_collection_error=self.state.last_collection_error,
                last_gpu_error=self.state.last_gpu_error,
                samples_written=self.state.samples_written,
            )

