from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_optional_int(value: Any, default: Optional[int]) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, str) and value.strip().lower() in {"none", "null", "off", ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    server_host: str
    server_port: int
    db_path: Path
    sample_interval_seconds: int
    retention_days: Optional[int]
    process_top_n: int
    log_file_path: Path
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    feishu_enabled: bool
    feishu_report_interval_seconds: int
    feishu_webhook_env_var: str
    feishu_timeout_seconds: int


def load_settings(config_path: Optional[Path] = None) -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    resolved_config_path = config_path or (project_root / "config.yaml")

    raw_config: dict[str, Any] = {}
    if resolved_config_path.exists():
        loaded = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw_config = loaded

    database = raw_config.get("database", {})
    server = raw_config.get("server", {})
    collection = raw_config.get("collection", {})
    retention = raw_config.get("retention", {})
    logging_config = raw_config.get("logging", {})
    feishu_config = raw_config.get("feishu", {})

    db_raw = database.get("path", "data/monitor.db") if isinstance(database, dict) else "data/monitor.db"
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = project_root / db_path

    server_host = "0.0.0.0"
    if isinstance(server, dict):
        server_host = str(server.get("host", server_host))
    server_port = max(1, _as_int(server.get("port", 8000) if isinstance(server, dict) else 8000, 8000))

    sample_interval_seconds = max(
        1,
        _as_int(collection.get("sample_interval_seconds", 5) if isinstance(collection, dict) else 5, 5),
    )
    if isinstance(retention, dict) and "days" in retention:
        retention_days = _as_optional_int(retention.get("days"), None)
    else:
        retention_days = 30
    process_top_n = max(
        1,
        _as_int(collection.get("process_top_n", 50) if isinstance(collection, dict) else 50, 50),
    )
    log_file_raw = "logs/monitor.log"
    if isinstance(logging_config, dict):
        log_file_raw = logging_config.get("file_path", log_file_raw)
    log_file_path = Path(log_file_raw)
    if not log_file_path.is_absolute():
        log_file_path = project_root / log_file_path

    log_level = "INFO"
    if isinstance(logging_config, dict):
        log_level = str(logging_config.get("level", log_level)).upper()

    log_max_bytes = max(
        1024,
        _as_int(logging_config.get("max_bytes", 10 * 1024 * 1024) if isinstance(logging_config, dict) else 10 * 1024 * 1024, 10 * 1024 * 1024),
    )
    log_backup_count = max(
        1,
        _as_int(logging_config.get("backup_count", 5) if isinstance(logging_config, dict) else 5, 5),
    )
    feishu_enabled = False
    if isinstance(feishu_config, dict):
        feishu_enabled = bool(feishu_config.get("enabled", feishu_enabled))
    feishu_report_interval_seconds = max(
        60,
        _as_int(
            feishu_config.get("report_interval_seconds", 3600) if isinstance(feishu_config, dict) else 3600,
            3600,
        ),
    )
    feishu_webhook_env_var = "FEISHU_BOT_WEBHOOK"
    if isinstance(feishu_config, dict):
        feishu_webhook_env_var = str(feishu_config.get("webhook_env_var", feishu_webhook_env_var))
    feishu_timeout_seconds = max(
        1,
        _as_int(feishu_config.get("timeout_seconds", 5) if isinstance(feishu_config, dict) else 5, 5),
    )
    return Settings(
        server_host=server_host,
        server_port=server_port,
        db_path=db_path,
        sample_interval_seconds=sample_interval_seconds,
        retention_days=retention_days,
        process_top_n=process_top_n,
        log_file_path=log_file_path,
        log_level=log_level,
        log_max_bytes=log_max_bytes,
        log_backup_count=log_backup_count,
        feishu_enabled=feishu_enabled,
        feishu_report_interval_seconds=feishu_report_interval_seconds,
        feishu_webhook_env_var=feishu_webhook_env_var,
        feishu_timeout_seconds=feishu_timeout_seconds,
    )

