from __future__ import annotations

from pathlib import Path

from app.config import load_settings


def test_load_settings_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "server:",
                "  host: 0.0.0.0",
                "  port: 8021",
                "database:",
                "  path: data/local.db",
                "collection:",
                "  sample_interval_seconds: 3",
                "  process_top_n: 25",
                "retention:",
                "  days: null",
                "logging:",
                "  file_path: logs/custom.log",
                "  level: debug",
                "  max_bytes: 2048",
                "  backup_count: 3",
                "feishu:",
                "  enabled: true",
                "  report_interval_seconds: 1800",
                "  webhook_env_var: FEISHU_HOOK",
                "  timeout_seconds: 9",
                "  timezone: Asia/Shanghai",
                "",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path)
    assert settings.server_host == "0.0.0.0"
    assert settings.server_port == 8021
    assert settings.sample_interval_seconds == 3
    assert settings.process_top_n == 25
    assert settings.retention_days is None
    assert settings.log_level == "DEBUG"
    assert settings.log_max_bytes == 2048
    assert settings.log_backup_count == 3
    assert settings.feishu_enabled is True
    assert settings.feishu_report_interval_seconds == 1800
    assert settings.feishu_webhook_env_var == "FEISHU_HOOK"
    assert settings.feishu_timeout_seconds == 9
    assert settings.feishu_timezone == "Asia/Shanghai"
    assert settings.db_path == (Path(__file__).resolve().parent.parent / "data/local.db")
    assert settings.log_file_path == (Path(__file__).resolve().parent.parent / "logs/custom.log")


def test_load_settings_defaults_when_file_missing(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.yaml")
    assert settings.server_host == "0.0.0.0"
    assert settings.server_port == 8000
    assert settings.sample_interval_seconds == 5
    assert settings.retention_days == 30
    assert settings.process_top_n == 50
    assert settings.feishu_enabled is False
    assert settings.feishu_report_interval_seconds == 3600
    assert settings.feishu_webhook_env_var == "FEISHU_BOT_WEBHOOK"
    assert settings.feishu_timeout_seconds == 5
    assert settings.feishu_timezone == "Asia/Shanghai"
