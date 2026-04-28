from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NovelStoryBibleSnapshot(Base):
    __tablename__ = "novel_story_bible_snapshots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_memory_version: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    stats_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    entities = relationship(
        "NovelStoryBibleEntity",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    facts = relationship(
        "NovelStoryBibleFact",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class NovelStoryBibleEntity(Base):
    __tablename__ = "novel_story_bible_entities"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_story_bible_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(32), default="character", index=True)
    canonical_name: Mapped[str] = mapped_column(String(512), default="", index=True)
    aliases_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    status: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(LONGTEXT, default="")
    tags_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    attributes_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    source_chapter_no: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_chapter_no: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    snapshot = relationship("NovelStoryBibleSnapshot", back_populates="entities")


class NovelStoryBibleFact(Base):
    __tablename__ = "novel_story_bible_facts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_story_bible_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    fact_type: Mapped[str] = mapped_column(String(64), default="timeline", index=True)
    subject_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    object_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    body: Mapped[str] = mapped_column(LONGTEXT, default="")
    evidence_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    chapter_range_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="active")
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    snapshot = relationship("NovelStoryBibleSnapshot", back_populates="facts")
