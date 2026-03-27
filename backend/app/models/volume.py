from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NovelVolume(Base):
    __tablename__ = "novel_volumes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(String(36), ForeignKey("novels.id"), index=True)
    volume_no: Mapped[int] = mapped_column(Integer, index=True)  # 1..N
    title: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    from_chapter: Mapped[int] = mapped_column(Integer, index=True)
    to_chapter: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default="draft"
    )  # draft | planned | locked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chapter_plans = relationship(
        "NovelChapterPlan", back_populates="volume", cascade="all, delete-orphan"
    )


class NovelChapterPlan(Base):
    __tablename__ = "novel_chapter_plans"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(String(36), ForeignKey("novels.id"), index=True)
    volume_id: Mapped[str] = mapped_column(String(36), ForeignKey("novel_volumes.id"), index=True)
    chapter_no: Mapped[int] = mapped_column(Integer, index=True)
    chapter_title: Mapped[str] = mapped_column(String(512), default="")
    beats_json: Mapped[str] = mapped_column(Text, default="{}")  # JSON object
    open_plots_intent_added_json: Mapped[str] = mapped_column(Text, default="[]")
    open_plots_intent_resolved_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(
        String(32), default="planned"
    )  # planned | locked | revised
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    volume = relationship("NovelVolume", back_populates="chapter_plans")

