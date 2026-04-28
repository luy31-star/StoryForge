from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.core.db_migrate import (
    ensure_app_config_columns,
    ensure_app_config_row,
    ensure_model_price_split_columns,
    ensure_novel_memory_norm_extended_columns,
    ensure_story_bible_columns,
    ensure_item_skill_lifecycle_columns,
    ensure_novel_entity_state_machine_columns,
    ensure_novel_target_chapters,
    ensure_user_config_columns,
    ensure_user_email_column,
    ensure_user_isolation_columns,
    ensure_user_status_columns,
    ensure_volume_outline_columns,
    ensure_writing_style_id_column,
    relax_novel_memory_norm_columns,
)
from app.core.database import SessionLocal
from app.services.qdrant_store import ensure_novel_qdrant_collection
from app.services.runtime_llm_config import ensure_app_config_llm_model_filled
import app.models.app_config  # noqa: F401 — ensure metadata registers
import app.models.user  # noqa: F401 — users / billing 表
import app.models.recharge_order  # noqa: F401 — recharge orders
import app.models.invite_code  # noqa: F401 — invite codes
import app.models.novel  # noqa: F401 — 确保 metadata 建表
import app.models.novel_memory_norm  # noqa: F401 — 规范化记忆表
import app.models.novel_story_bible  # noqa: F401 — Story Bible
import app.models.novel_retrieval  # noqa: F401 — RAG 检索表
import app.models.novel_workflow_runtime  # noqa: F401 — 工作流状态机
import app.models.novel_memory_runtime  # noqa: F401 — 记忆更新审计
import app.models.novel_judge  # noqa: F401 — Judge 结果
import app.models.volume  # noqa: F401 — 确保 volumes/plan 建表
import app.models.project  # noqa: F401 — projects.user_id
import app.models.workflow  # noqa: F401 — workflows.user_id
import app.models.task  # noqa: F401 — user_tasks
import app.models.writing_style  # noqa: F401 — writing_styles
from app.middleware.request_log import RequestLoggingMiddleware
from app.core.rate_limit import setup_rate_limiting
from slowapi.middleware import SlowAPIMiddleware
from app.routers import agents, auth, billing, llm, media, novel, volume, websocket, workflow, admin_dashboard, tasks, writing_style

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
app.add_middleware(SlowAPIMiddleware)

setup_rate_limiting(app)

app.include_router(auth.router)
app.include_router(billing.router)
app.include_router(billing.admin_router)
app.include_router(admin_dashboard.router)
app.include_router(workflow.router)
app.include_router(agents.router)
app.include_router(llm.router)
app.include_router(media.router)
app.include_router(novel.router)
app.include_router(volume.router)
app.include_router(tasks.router)
app.include_router(writing_style.router)
app.include_router(websocket.router)


@app.on_event("startup")
def on_startup() -> None:
    # 数据库连接重试逻辑
    max_retries = 5
    retry_interval = 5
    last_exc = None
    for i in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except Exception as e:
            last_exc = e
            logger.warning(f"Database connection failed (attempt {i+1}/{max_retries}), retrying in {retry_interval}s... err={e}")
            time.sleep(retry_interval)
    else:
        logger.error("Failed to connect to database after several attempts.")
        if last_exc:
            err_s = str(last_exc)
            if "Unknown database" in err_s or "1049" in err_s:
                logger.error(
                    "数据库不存在（常见于 MySQL）：请在实例上先执行 CREATE DATABASE，"
                    "库名须与 DATABASE_URL 路径中的库名一致，并授予连接用户该库的权限；"
                    "Docker 官方 mysql 镜像可通过 MYSQL_DATABASE 自动建库，云数据库/RDS 通常需手动创建。"
                )
            raise last_exc

    ensure_user_isolation_columns(engine)
    ensure_user_config_columns(engine)
    ensure_user_email_column(engine)
    ensure_user_status_columns(engine)
    ensure_novel_target_chapters(engine)
    ensure_writing_style_id_column(engine)
    ensure_novel_memory_norm_extended_columns(engine)
    ensure_story_bible_columns(engine)
    ensure_item_skill_lifecycle_columns(engine)
    ensure_novel_entity_state_machine_columns(engine)
    ensure_volume_outline_columns(engine)
    relax_novel_memory_norm_columns(engine)
    ensure_model_price_split_columns(engine)
    ensure_app_config_columns(engine)
    ensure_app_config_row(engine)
    ensure_novel_qdrant_collection()
    db = SessionLocal()
    try:
        ensure_app_config_llm_model_filled(db)
    except Exception:
        logger.exception("ensure_app_config_llm_model_filled failed")
    finally:
        db.close()
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
