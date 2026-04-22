from __future__ import annotations

import app.main as main_module


def test_run_uses_settings_host_port(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app_path: str, host: str, port: int) -> None:
        captured["app_path"] = app_path
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    main_module.run()

    assert captured["app_path"] == "app.main:app"
    assert captured["host"] == main_module.settings.server_host
    assert captured["port"] == main_module.settings.server_port
