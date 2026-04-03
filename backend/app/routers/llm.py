from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.runtime_llm_config import (
    get_runtime_llm_config,
    get_runtime_web_search_config,
    has_explicit_stored_llm_model,
    set_runtime_llm_config,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])


class LLMConfigOut(BaseModel):
    provider: str
    model: str
    has_explicit_model: bool = Field(
        description="是否已配置明确的模型（当前用户已保存，或全局已保存）"
    )
    novel_web_search: bool
    novel_generate_web_search: bool
    novel_volume_plan_web_search: bool
    novel_memory_refresh_web_search: bool
    novel_inspiration_web_search: bool


class LLMConfigIn(BaseModel):
    provider: str = Field(default="ai302", description="固定为 ai302，忽略其他值")
    model: str = Field(
        default="",
        description="模型 ID（须为模型计价中已启用项）；留空则保存为计价列表中第一个已启用模型",
    )
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
def get_llm_config(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LLMConfigOut:
    cfg = get_runtime_llm_config(db, user_id=user.id)
    w = get_runtime_web_search_config(db, user_id=user.id)
    return LLMConfigOut(
        provider=cfg.provider,
        model=cfg.model,
        has_explicit_model=has_explicit_stored_llm_model(db, user_id=user.id),
        novel_web_search=w.novel_web_search,
        novel_generate_web_search=w.novel_generate_web_search,
        novel_volume_plan_web_search=w.novel_volume_plan_web_search,
        novel_memory_refresh_web_search=w.novel_memory_refresh_web_search,
        novel_inspiration_web_search=w.novel_inspiration_web_search,
    )


@router.post("/config")
def set_llm_config(
    body: LLMConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LLMConfigOut:
    try:
        row = set_runtime_llm_config(
            db=db,
            user_id=user.id,
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

    eff = get_runtime_llm_config(db, user_id=user.id)
    return LLMConfigOut(
        provider="ai302",
        model=eff.model,
        has_explicit_model=has_explicit_stored_llm_model(db, user_id=user.id),
        novel_web_search=bool(row.novel_web_search),
        novel_generate_web_search=bool(row.novel_generate_web_search),
        novel_volume_plan_web_search=bool(row.novel_volume_plan_web_search),
        novel_memory_refresh_web_search=bool(row.novel_memory_refresh_web_search),
        novel_inspiration_web_search=bool(row.novel_inspiration_web_search),
    )

