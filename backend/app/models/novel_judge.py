from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Float, String
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NovelJudgeRun(Base):
    __tablename__ = "novel_judge_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("novel_chapters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("novel_workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    judge_type: Mapped[str] = mapped_column(String(64), default="chapter_suite")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    model_name: Mapped[str] = mapped_column(String(255), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(LONGTEXT, default="")
    payload_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    issues = relationship(
        "NovelJudgeIssue",
        back_populates="judge_run",
        cascade="all, delete-orphan",
    )


class NovelJudgeIssue(Base):
    __tablename__ = "novel_judge_issues"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    judge_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_judge_runs.id", ondelete="CASCADE"),
        index=True,
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("novel_chapters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    issue_type: Mapped[str] = mapped_column(String(64), default="consistency")
    title: Mapped[str] = mapped_column(String(255), default="")
    evidence_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    suggestion: Mapped[str] = mapped_column(LONGTEXT, default="")
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    judge_run = relationship("NovelJudgeRun", back_populates="issues")
