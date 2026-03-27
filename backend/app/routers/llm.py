from __future__ import annotations

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.runtime_llm_config import (
    get_runtime_llm_config,
    get_runtime_web_search_config,
    set_runtime_llm_config,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])


class LLMConfigOut(BaseModel):
    provider: str
    model: str
    novel_web_search: bool
    novel_generate_web_search: bool
    novel_volume_plan_web_search: bool
    novel_memory_refresh_web_search: bool
    novel_inspiration_web_search: bool


class LLMConfigIn(BaseModel):
    provider: str = Field(..., description="ai302 | custom")
    model: str = Field(default="", description="留空表示使用该 provider 的默认模型")
    novel_web_search: bool | None = Field(
        default=None,
        description="小说通用生成/记忆刷新 是否启用 302 web-search",
    )
    novel_generate_web_search: bool | None = Field(
        default=None,
        description="小说续写 是否启用 web-search",
    )
    novel_volume_plan_web_search: bool | None = Field(
        default=None,
        description="卷章计划生成 是否启用 web-search",
    )
    novel_memory_refresh_web_search: bool | None = Field(
        default=None,
        description="小说记忆刷新 是否启用 web-search",
    )
    novel_inspiration_web_search: bool | None = Field(
        default=None,
        description="小说灵感对话 是否启用 302 web-search",
    )


@router.get("/config")
def get_llm_config(db: Session = Depends(get_db)) -> LLMConfigOut:
    cfg = get_runtime_llm_config(db)
    w = get_runtime_web_search_config(db)
    return LLMConfigOut(
        provider=cfg.provider,
        model=cfg.model,
        novel_web_search=w.novel_web_search,
        novel_generate_web_search=w.novel_generate_web_search,
        novel_volume_plan_web_search=w.novel_volume_plan_web_search,
        novel_memory_refresh_web_search=w.novel_memory_refresh_web_search,
        novel_inspiration_web_search=w.novel_inspiration_web_search,
    )


@router.post("/config")
def set_llm_config(body: LLMConfigIn, db: Session = Depends(get_db)) -> LLMConfigOut:
    try:
        row = set_runtime_llm_config(
            db=db,
            provider=body.provider,
            model=body.model,
            novel_web_search=body.novel_web_search,
            novel_generate_web_search=body.novel_generate_web_search,
            novel_volume_plan_web_search=body.novel_volume_plan_web_search,
            novel_memory_refresh_web_search=body.novel_memory_refresh_web_search,
            novel_inspiration_web_search=body.novel_inspiration_web_search,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    return LLMConfigOut(
        provider=row.llm_provider,
        model=row.llm_model,
        novel_web_search=bool(row.novel_web_search),
        novel_generate_web_search=bool(row.novel_generate_web_search),
        novel_volume_plan_web_search=bool(row.novel_volume_plan_web_search),
        novel_memory_refresh_web_search=bool(row.novel_memory_refresh_web_search),
        novel_inspiration_web_search=bool(row.novel_inspiration_web_search),
    )

