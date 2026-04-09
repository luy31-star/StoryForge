from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.app_config import AppConfig
from app.models.user import ModelPrice, User


DEFAULT_CONFIG_ID = "global"


@dataclass
class RuntimeLLMConfig:
    provider: str  # 固定为 ai302（仅 302.AI 中转）
    model: str  # 已解析：模型计价中已启用项；无则为空（调用 chat 前须配置）


@dataclass
class RuntimeWebSearchConfig:
    novel_web_search: bool
    novel_generate_web_search: bool
    novel_volume_plan_web_search: bool
    novel_memory_refresh_web_search: bool
    novel_inspiration_web_search: bool


def cheapest_enabled_model_id(db: Session) -> str | None:
    """
    管理后台「模型计价」中，选择最便宜的已启用模型：
    - 以 (prompt_price + completion_price) 作为排序依据
    - 若 prompt/completion 为空则回退到兼容字段 price_cny_per_million_tokens
    """
    p = func.coalesce(
        ModelPrice.prompt_price_cny_per_million_tokens,
        ModelPrice.price_cny_per_million_tokens,
        0.0,
    )
    c = func.coalesce(
        ModelPrice.completion_price_cny_per_million_tokens,
        ModelPrice.price_cny_per_million_tokens,
        0.0,
    )
    r = (
        db.query(ModelPrice)
        .filter(ModelPrice.enabled.is_(True))
        .order_by((p + c).asc(), ModelPrice.model_id.asc())
        .first()
    )
    return r.model_id if r else None


def resolve_effective_llm_model(db: Session, stored: str) -> str:
    """
    解析全站实际使用的模型 ID：
    - 若 stored 非空且在已启用计价中存在，则用之；
    - 否则使用“最便宜”的已启用计价模型；
    - 若尚无可用计价，返回空字符串（调用 LLM 时由路由层报错）。
    """
    s = (stored or "").strip()
    if s:
        ok = (
            db.query(ModelPrice)
            .filter(ModelPrice.model_id == s, ModelPrice.enabled.is_(True))
            .first()
        )
        if ok:
            return s
    m = cheapest_enabled_model_id(db)
    if m:
        return m
    return ""


def ensure_app_config_llm_model_filled(db: Session) -> None:
    """启动或迁移：仅当 app_config.llm_model 已填写但不在已启用计价中时，规范为 resolve 后的值。不在此把空值自动写成首项，以便前端区分「尚未在设置里保存」。"""
    row = db.get(AppConfig, DEFAULT_CONFIG_ID)
    if not row:
        return
    stored = (row.llm_model or "").strip()
    if not stored:
        return
    eff = resolve_effective_llm_model(db, stored)
    if stored != eff:
        row.llm_model = eff
        db.add(row)
        db.commit()


def has_explicit_stored_llm_model(db: Session, user_id: str | None = None) -> bool:
    """是否非空（用户曾在设置中保存过模型 ID，或全局已保存）。"""
    if user_id:
        u = db.get(User, user_id)
        if u and (u.llm_model or "").strip():
            return True
    
    row = _ensure_row(db)
    return bool((row.llm_model or "").strip())


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


def get_runtime_llm_config(db: Session, user_id: str | None = None) -> RuntimeLLMConfig:
    stored_model = ""
    if user_id:
        u = db.get(User, user_id)
        if u:
            stored_model = (u.llm_model or "").strip()
    
    if not stored_model:
        row = _ensure_row(db)
        stored_model = (row.llm_model or "").strip()
        
    eff = resolve_effective_llm_model(db, stored_model)
    return RuntimeLLMConfig(provider="ai302", model=eff)


def get_runtime_web_search_config(db: Session, user_id: str | None = None) -> RuntimeWebSearchConfig:
    if user_id:
        u = db.get(User, user_id)
        if u:
            return RuntimeWebSearchConfig(
                novel_web_search=bool(u.novel_web_search),
                novel_generate_web_search=bool(u.novel_generate_web_search),
                novel_volume_plan_web_search=bool(u.novel_volume_plan_web_search),
                novel_memory_refresh_web_search=bool(u.novel_memory_refresh_web_search),
                novel_inspiration_web_search=bool(u.novel_inspiration_web_search),
            )
            
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
    user_id: str | None = None,
    provider: str,
    model: str,
    novel_web_search: bool | None = None,
    novel_generate_web_search: bool | None = None,
    novel_volume_plan_web_search: bool | None = None,
    novel_memory_refresh_web_search: bool | None = None,
    novel_inspiration_web_search: bool | None = None,
) -> AppConfig | User:
    m = (model or "").strip()
    if not m:
        m = cheapest_enabled_model_id(db) or ""
    if not m:
        raise ValueError("请先在管理后台「模型计价」中至少添加一个已启用的模型")

    ok = (
        db.query(ModelPrice)
        .filter(ModelPrice.model_id == m, ModelPrice.enabled.is_(True))
        .first()
    )
    if not ok:
        raise ValueError("所选模型未启用或不存在，请在模型计价中检查")

    if user_id:
        u = db.get(User, user_id)
        if u:
            u.llm_model = m
            if novel_web_search is not None:
                u.novel_web_search = bool(novel_web_search)
            if novel_generate_web_search is not None:
                u.novel_generate_web_search = bool(novel_generate_web_search)
            if novel_volume_plan_web_search is not None:
                u.novel_volume_plan_web_search = bool(novel_volume_plan_web_search)
            if novel_memory_refresh_web_search is not None:
                u.novel_memory_refresh_web_search = bool(novel_memory_refresh_web_search)
            if novel_inspiration_web_search is not None:
                u.novel_inspiration_web_search = bool(novel_inspiration_web_search)
            db.add(u)
            db.commit()
            db.refresh(u)
            return u

    row = _ensure_row(db)
    row.llm_provider = "ai302"
    row.llm_model = m

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
