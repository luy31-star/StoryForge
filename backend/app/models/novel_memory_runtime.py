from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NovelMemoryUpdateRun(Base):
    __tablename__ = "novel_memory_update_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    batch_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    trigger_source: Mapped[str] = mapped_column(String(64), default="manual")
    source: Mapped[str] = mapped_column(String(64), default="manual_refresh")
    chapter_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chapter_no: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    current_stage: Mapped[str] = mapped_column(String(64), default="queued")
    base_memory_version: Mapped[int] = mapped_column(Integer, default=0)
    target_memory_version: Mapped[int] = mapped_column(Integer, default=0)
    delta_status: Mapped[str] = mapped_column(String(32), default="pending")
    validation_status: Mapped[str] = mapped_column(String(32), default="pending")
    norm_status: Mapped[str] = mapped_column(String(32), default="pending")
    snapshot_status: Mapped[str] = mapped_column(String(32), default="pending")
    story_bible_status: Mapped[str] = mapped_column(String(32), default="pending")
    rag_status: Mapped[str] = mapped_column(String(32), default="pending")
    request_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    source_summary_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    diff_summary_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    warnings_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    errors_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    result_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    error_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
