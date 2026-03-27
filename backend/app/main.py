from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.core.db_migrate import (
    ensure_app_config_columns,
    ensure_app_config_row,
    ensure_novel_memory_norm_extended_columns,
    ensure_novel_target_chapters,
)
import app.models.app_config  # noqa: F401 — ensure metadata registers
import app.models.novel  # noqa: F401 — 确保 metadata 建表
import app.models.novel_memory_norm  # noqa: F401 — 规范化记忆表
import app.models.volume  # noqa: F401 — 确保 volumes/plan 建表
from app.middleware.request_log import RequestLoggingMiddleware
from app.routers import agents, llm, media, novel, volume, websocket, workflow

logger = logging.getLogger(__name__)
logging.getLogger("vocalflow.request").setLevel(logging.INFO)
logging.getLogger("app.routers.novel").setLevel(logging.INFO)
logging.getLogger("app.routers.volume").setLevel(logging.INFO)
logging.getLogger("app.services.novel_llm_service").setLevel(logging.INFO)
logging.getLogger("app.services.ai302_client").setLevel(logging.INFO)
logging.getLogger("app.tasks.novel_tasks").setLevel(logging.INFO)

app = FastAPI(title=settings.app_name, version="0.1.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 最后注册，作为最外层：记录含 CORS 在内的整段耗时
app.add_middleware(RequestLoggingMiddleware)

app.include_router(workflow.router)
app.include_router(agents.router)
app.include_router(llm.router)
app.include_router(media.router)
app.include_router(novel.router)
app.include_router(volume.router)
app.include_router(websocket.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_novel_target_chapters(engine)
    ensure_novel_memory_norm_extended_columns(engine)
    ensure_app_config_columns(engine)
    ensure_app_config_row(engine)
    if settings.oss_region and settings.oss_bucket:
        logger.info(
            "OSS: region=%s bucket=%s endpoint=%s",
            settings.oss_region,
            settings.oss_bucket,
            settings.oss_endpoint or "(derive from region)",
        )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
