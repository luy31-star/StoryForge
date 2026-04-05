from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_admin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    creator = relationship("User", foreign_keys=[created_by_admin_id])
    used_by = relationship("User", foreign_keys=[used_by_user_id])

