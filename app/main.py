from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api.metrics import router as metrics_router
from app.config import Settings, load_settings
from app.db import init_database
from app.jobs.scheduler import MonitorScheduler

settings: Settings = load_settings()
web_dir = Path(__file__).resolve().parent.parent / "web"


def configure_logging() -> None:
    log_path = settings.log_file_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database(settings.db_path)
    monitor_scheduler = MonitorScheduler(settings=settings)
    monitor_scheduler.start()
    app.state.monitor_scheduler = monitor_scheduler
    app.state.settings = settings
    try:
        yield
    finally:
        monitor_scheduler.shutdown()


app = FastAPI(title="Lightweight Host Monitor", lifespan=lifespan)
app.include_router(metrics_router)
app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(web_dir / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    uvicorn.run("app.main:app", host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    run()

