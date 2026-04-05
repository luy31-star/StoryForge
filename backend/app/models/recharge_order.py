from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RechargeOrder(Base):
    __tablename__ = "recharge_orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="alipay")

    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    amount_cny: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(32), default="created")
    trade_status: Mapped[str] = mapped_column(String(32), default="")
    alipay_trade_no: Mapped[str] = mapped_column(String(64), default="")

    notify_raw: Mapped[str] = mapped_column(Text, default="")
    query_raw: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user = relationship("User", backref="recharge_orders")

