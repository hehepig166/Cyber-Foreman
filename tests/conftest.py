from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import init_database


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        server_host="127.0.0.1",
        server_port=18000,
        db_path=tmp_path / "test.db",
        sample_interval_seconds=5,
        retention_days=30,
        process_top_n=10,
        log_file_path=tmp_path / "logs" / "test.log",
        log_level="INFO",
        log_max_bytes=1024 * 1024,
        log_backup_count=2,
        feishu_enabled=False,
        feishu_report_interval_seconds=3600,
        feishu_webhook_env_var="FEISHU_BOT_WEBHOOK",
        feishu_timeout_seconds=5,
    )


@pytest.fixture
def initialized_db(test_settings: Settings) -> Path:
    init_database(test_settings.db_path)
    return test_settings.db_path
