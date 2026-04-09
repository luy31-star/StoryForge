from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserTask(Base):
    __tablename__ = "user_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)

    kind: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    title: Mapped[str] = mapped_column(String(256), default="")

    batch_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(
        String(128), index=True, nullable=True
    )

    novel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("novels.id"), index=True, nullable=True
    )
    volume_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("novel_volumes.id"), index=True, nullable=True
    )

    progress: Mapped[int] = mapped_column(Integer, default=0)
    last_message: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def meta(self) -> dict[str, Any]:
        try:
            v = json.loads(self.meta_json or "{}")
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

