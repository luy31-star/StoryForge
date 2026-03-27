from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    pass


class Novel(Base):
    """单用户小说；不挂 user_id。"""

    __tablename__ = "novels"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(512))
    intro: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(255), default="")
    # 目标章节数：用于框架生成与分卷（每卷默认 50 章）
    target_chapters: Mapped[int] = mapped_column(Integer, default=300)
    # 兼容历史字段（前端已不再要求用户填写）
    target_word_count: Mapped[int] = mapped_column(Integer, default=100_000)
    # 每日自动撰写并进入「待审」的章节数；0 表示不自动
    daily_auto_chapters: Mapped[int] = mapped_column(Integer, default=0)
    reference_storage_key: Mapped[str] = mapped_column(String(1024), default="")
    reference_public_url: Mapped[str] = mapped_column(String(2048), default="")
    reference_filename: Mapped[str] = mapped_column(String(512), default="")
    framework_json: Mapped[str] = mapped_column(Text, default="")
    framework_markdown: Mapped[str] = mapped_column(Text, default="")
    framework_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(32), default="draft"
    )  # draft | active | completed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chapters = relationship(
        "Chapter", back_populates="novel", cascade="all, delete-orphan"
    )
    memories = relationship(
        "NovelMemory", back_populates="novel", cascade="all, delete-orphan"
    )


class Chapter(Base):
    __tablename__ = "novel_chapters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(String(36), ForeignKey("novels.id"))
    chapter_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    # 大模型修订稿；仅用户「确认覆盖」后写入 content
    pending_content: Mapped[str] = mapped_column(Text, default="")
    pending_revision_prompt: Mapped[str] = mapped_column(Text, default="")
    # draft | pending_review | approved
    status: Mapped[str] = mapped_column(String(32), default="draft")
    source: Mapped[str] = mapped_column(
        String(32), default="manual"
    )  # manual | daily_job | user_prompt
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    novel = relationship("Novel", back_populates="chapters")
    feedbacks = relationship(
        "ChapterFeedback", back_populates="chapter", cascade="all, delete-orphan"
    )


class ChapterFeedback(Base):
    """人工改进意见（可多条）。"""

    __tablename__ = "novel_chapter_feedback"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chapter_id: Mapped[str] = mapped_column(String(36), ForeignKey("novel_chapters.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chapter = relationship("Chapter", back_populates="feedbacks")


class NovelMemory(Base):
    """结构化记忆快照（人物、物品、关系等），按版本追加。"""

    __tablename__ = "novel_memories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(String(36), ForeignKey("novels.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    novel = relationship("Novel", back_populates="memories")


class NovelGenerationLog(Base):
    """章节生成过程日志，便于前端可视化排障。"""

    __tablename__ = "novel_generation_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(String(36), ForeignKey("novels.id"), index=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    event: Mapped[str] = mapped_column(String(64), default="unknown")
    chapter_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
