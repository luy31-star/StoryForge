"""多用户、积分与模型计价。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novels = relationship("Novel", back_populates="owner")

    # 用户个性化 LLM 配置
    llm_model: Mapped[str] = mapped_column(String(255), default="")
    novel_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_generate_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_volume_plan_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_memory_refresh_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    novel_inspiration_web_search: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelPrice(Base):
    """每百万 token 的人民币单价（用户侧按积分扣：见 billing_service）。"""

    __tablename__ = "model_prices"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    model_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # 兼容性字段：如果 prompt/completion 未设置，则使用此字段
    price_cny_per_million_tokens: Mapped[float] = mapped_column(Float, default=1.0)
    # 输入单价
    prompt_price_cny_per_million_tokens: Mapped[float] = mapped_column(Float, default=1.0)
    # 输出单价
    completion_price_cny_per_million_tokens: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TokenUsage(Base):
    __tablename__ = "token_usages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_points: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="token_usages")


class PointsTransaction(Base):
    __tablename__ = "points_transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    amount_points: Mapped[int] = mapped_column(Integer)
    transaction_type: Mapped[str] = mapped_column(
        String(32)
    )  # recharge | consumption | admin_adjust
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="points_transactions")
