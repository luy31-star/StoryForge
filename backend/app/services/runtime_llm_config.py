from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.app_config import AppConfig


DEFAULT_CONFIG_ID = "global"


@dataclass
class RuntimeLLMConfig:
    provider: str  # ai302 | custom
    model: str  # "" means default per provider


@dataclass
class RuntimeWebSearchConfig:
    novel_web_search: bool
    novel_generate_web_search: bool
    novel_volume_plan_web_search: bool
    novel_memory_refresh_web_search: bool
    novel_inspiration_web_search: bool


def _ensure_row(db: Session) -> AppConfig:
    row = db.get(AppConfig, DEFAULT_CONFIG_ID)
    if row:
        return row

    row = AppConfig(
        id=DEFAULT_CONFIG_ID,
        llm_provider=(settings.llm_provider or "ai302").strip().lower(),
        llm_model=(settings.llm_model or "").strip(),
        novel_web_search=bool(settings.ai302_novel_web_search),
        novel_generate_web_search=bool(settings.ai302_novel_web_search),
        novel_volume_plan_web_search=bool(settings.ai302_novel_web_search),
        novel_memory_refresh_web_search=bool(settings.ai302_novel_web_search),
        novel_inspiration_web_search=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_runtime_llm_config(db: Session) -> RuntimeLLMConfig:
    row = _ensure_row(db)
    provider = (row.llm_provider or "ai302").strip().lower()
    if provider not in ("ai302", "custom"):
        provider = "ai302"
    return RuntimeLLMConfig(provider=provider, model=(row.llm_model or "").strip())


def get_runtime_web_search_config(db: Session) -> RuntimeWebSearchConfig:
    row = _ensure_row(db)
    return RuntimeWebSearchConfig(
        novel_web_search=bool(row.novel_web_search),
        novel_generate_web_search=bool(row.novel_generate_web_search),
        novel_volume_plan_web_search=bool(row.novel_volume_plan_web_search),
        novel_memory_refresh_web_search=bool(row.novel_memory_refresh_web_search),
        novel_inspiration_web_search=bool(row.novel_inspiration_web_search),
    )


def set_runtime_llm_config(
    *,
    db: Session,
    provider: str,
    model: str,
    novel_web_search: bool | None = None,
    novel_generate_web_search: bool | None = None,
    novel_volume_plan_web_search: bool | None = None,
    novel_memory_refresh_web_search: bool | None = None,
    novel_inspiration_web_search: bool | None = None,
) -> AppConfig:
    row = _ensure_row(db)

    p = (provider or "").strip().lower()
    if p not in ("ai302", "custom"):
        raise ValueError("llm_provider 只支持 ai302 或 custom")

    row.llm_provider = p
    row.llm_model = (model or "").strip()

    if novel_web_search is not None:
        row.novel_web_search = bool(novel_web_search)
    if novel_generate_web_search is not None:
        row.novel_generate_web_search = bool(novel_generate_web_search)
    if novel_volume_plan_web_search is not None:
        row.novel_volume_plan_web_search = bool(novel_volume_plan_web_search)
    if novel_memory_refresh_web_search is not None:
        row.novel_memory_refresh_web_search = bool(novel_memory_refresh_web_search)
    if novel_inspiration_web_search is not None:
        row.novel_inspiration_web_search = bool(novel_inspiration_web_search)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row
