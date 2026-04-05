from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    llm_provider: Mapped[str] = mapped_column(String(32), default="ai302")
    llm_model: Mapped[str] = mapped_column(String(255), default="")

    # 兼容旧开关（仍保留，供未细分场景回退）
    novel_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    # 细粒度开关：小说主流程按功能拆分
    novel_generate_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_volume_plan_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_memory_refresh_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_inspiration_web_search: Mapped[bool] = mapped_column(Boolean, default=True)

    invite_only_registration: Mapped[bool] = mapped_column(Boolean, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
