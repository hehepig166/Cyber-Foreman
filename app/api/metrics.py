from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import desc, select

from app.db import GpuDeviceSample, GpuProcessSample, HostSample, ProcessSample, get_session, utcnow

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _parse_range(value: str) -> timedelta:
    normalized = value.strip().lower()
    try:
        if normalized.endswith("h"):
            return timedelta(hours=int(normalized[:-1]))
        if normalized.endswith("d"):
            return timedelta(days=int(normalized[:-1]))
        if normalized.endswith("m"):
            return timedelta(minutes=int(normalized[:-1]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid range number.") from exc
    raise HTTPException(status_code=400, detail="Invalid range format. Use forms like 1h, 24h, 7d.")


@router.get("/snapshot")
def get_snapshot(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    with get_session() as session:
        latest_host = session.execute(select(HostSample).order_by(desc(HostSample.timestamp)).limit(1)).scalar_one_or_none()
        if latest_host is None:
            return {"host": None, "processes": [], "gpu_processes": []}

        ts = latest_host.timestamp
        processes = session.execute(
            select(ProcessSample)
            .where(ProcessSample.timestamp == ts)
            .order_by(desc(ProcessSample.cpu_percent))
            .limit(limit)
        ).scalars()
        gpu_processes = session.execute(
            select(GpuProcessSample)
            .where(GpuProcessSample.timestamp == ts)
            .order_by(desc(GpuProcessSample.used_gpu_memory_mb))
            .limit(limit)
        ).scalars()
        gpu_devices = session.execute(
            select(GpuDeviceSample).where(GpuDeviceSample.timestamp == ts).order_by(GpuDeviceSample.gpu_index.asc())
        ).scalars()

        return {
            "host": {
                "timestamp": latest_host.timestamp,
                "cpu_usage": latest_host.cpu_usage,
                "mem_usage": latest_host.mem_usage,
                "load_1m": latest_host.load_1m,
                "load_5m": latest_host.load_5m,
                "load_15m": latest_host.load_15m,
                "gpu_util": latest_host.gpu_util,
                "gpu_mem_used_mb": latest_host.gpu_mem_used_mb,
                "gpu_mem_total_mb": latest_host.gpu_mem_total_mb,
            },
            "processes": [
                {
                    "pid": p.pid,
                    "name": p.name,
                    "user_name": p.user_name,
                    "cpu_percent": p.cpu_percent,
                    "rss_mb": p.rss_mb,
                    "cmdline": p.cmdline,
                }
                for p in processes
            ],
            "gpu_processes": [
                {
                    "gpu_index": g.gpu_index,
                    "gpu_uuid": g.gpu_uuid,
                    "pid": g.pid,
                    "process_name": g.process_name,
                    "user_name": g.user_name,
                    "cmdline": g.cmdline,
                    "used_gpu_memory_mb": g.used_gpu_memory_mb,
                }
                for g in gpu_processes
            ],
            "gpu_devices": [
                {
                    "gpu_index": d.gpu_index,
                    "gpu_uuid": d.gpu_uuid,
                    "gpu_name": d.gpu_name,
                    "gpu_util": d.gpu_util,
                    "gpu_mem_used_mb": d.gpu_mem_used_mb,
                    "gpu_mem_total_mb": d.gpu_mem_total_mb,
                    "process_count": d.process_count,
                }
                for d in gpu_devices
            ],
        }


@router.get("/history")
def get_history(range_window: str = Query(default="1h")) -> dict[str, Any]:
    window = _parse_range(range_window)
    cutoff = utcnow() - window

    with get_session() as session:
        rows = session.execute(
            select(HostSample).where(HostSample.timestamp >= cutoff).order_by(HostSample.timestamp.asc())
        ).scalars()
        points = [
            {
                "timestamp": row.timestamp,
                "cpu_usage": row.cpu_usage,
                "mem_usage": row.mem_usage,
                "gpu_util": row.gpu_util,
                "gpu_mem_used_mb": row.gpu_mem_used_mb,
                "gpu_mem_total_mb": row.gpu_mem_total_mb,
            }
            for row in rows
        ]
        return {"points": points}


@router.get("/processes/current")
def get_current_processes(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    with get_session() as session:
        latest_ts = session.execute(select(HostSample.timestamp).order_by(desc(HostSample.timestamp)).limit(1)).scalar_one_or_none()
        if latest_ts is None:
            return {"processes": []}
        processes = session.execute(
            select(ProcessSample)
            .where(ProcessSample.timestamp == latest_ts)
            .order_by(desc(ProcessSample.cpu_percent))
            .limit(limit)
        ).scalars()
        return {
            "processes": [
                {
                    "timestamp": p.timestamp,
                    "pid": p.pid,
                    "name": p.name,
                    "user_name": p.user_name,
                    "cpu_percent": p.cpu_percent,
                    "rss_mb": p.rss_mb,
                    "cmdline": p.cmdline,
                }
                for p in processes
            ]
        }


@router.get("/gpu-processes/current")
def get_current_gpu_processes(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    with get_session() as session:
        latest_ts = session.execute(select(HostSample.timestamp).order_by(desc(HostSample.timestamp)).limit(1)).scalar_one_or_none()
        if latest_ts is None:
            return {"gpu_processes": []}
        gpu_processes = session.execute(
            select(GpuProcessSample)
            .where(GpuProcessSample.timestamp == latest_ts)
            .order_by(desc(GpuProcessSample.used_gpu_memory_mb))
            .limit(limit)
        ).scalars()
        return {
            "gpu_processes": [
                {
                    "timestamp": g.timestamp,
                    "gpu_index": g.gpu_index,
                    "gpu_uuid": g.gpu_uuid,
                    "pid": g.pid,
                    "process_name": g.process_name,
                    "user_name": g.user_name,
                    "cmdline": g.cmdline,
                    "used_gpu_memory_mb": g.used_gpu_memory_mb,
                }
                for g in gpu_processes
            ]
        }


@router.get("/gpu-devices/current")
def get_current_gpu_devices() -> dict[str, Any]:
    with get_session() as session:
        latest_ts = session.execute(select(HostSample.timestamp).order_by(desc(HostSample.timestamp)).limit(1)).scalar_one_or_none()
        if latest_ts is None:
            return {"gpu_devices": []}
        gpu_devices = session.execute(
            select(GpuDeviceSample).where(GpuDeviceSample.timestamp == latest_ts).order_by(GpuDeviceSample.gpu_index.asc())
        ).scalars()
        return {
            "gpu_devices": [
                {
                    "timestamp": d.timestamp,
                    "gpu_index": d.gpu_index,
                    "gpu_uuid": d.gpu_uuid,
                    "gpu_name": d.gpu_name,
                    "gpu_util": d.gpu_util,
                    "gpu_mem_used_mb": d.gpu_mem_used_mb,
                    "gpu_mem_total_mb": d.gpu_mem_total_mb,
                    "process_count": d.process_count,
                }
                for d in gpu_devices
            ]
        }


@router.get("/status")
def get_status(request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "monitor_scheduler", None)
    if scheduler is None:
        return {"scheduler_running": False, "last_collection_error": "scheduler is not initialized"}
    runtime_state = scheduler.get_runtime_state()
    return {
        "scheduler_running": scheduler.scheduler.running,
        "last_collection_error": runtime_state.last_collection_error,
        "last_gpu_error": runtime_state.last_gpu_error,
        "samples_written": runtime_state.samples_written,
    }


@router.get("/config")
def get_config(request: Request) -> dict[str, Any]:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "server_host": settings.server_host,
        "server_port": settings.server_port,
        "database_path": str(settings.db_path),
        "sample_interval_seconds": settings.sample_interval_seconds,
        "retention_days": settings.retention_days,
        "process_top_n": settings.process_top_n,
        "log_file_path": str(settings.log_file_path),
        "log_level": settings.log_level,
        "log_max_bytes": settings.log_max_bytes,
        "log_backup_count": settings.log_backup_count,
    }

