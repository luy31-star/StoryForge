from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NovelWorkflowRun(Base):
    __tablename__ = "novel_workflow_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    run_type: Mapped[str] = mapped_column(String(64), default="auto_pipeline")
    trigger_source: Mapped[str] = mapped_column(String(64), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    batch_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    current_step: Mapped[str] = mapped_column(String(128), default="")
    cursor_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    input_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    output_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    error_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    is_resumable: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    steps = relationship(
        "NovelWorkflowStep",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    events = relationship(
        "NovelWorkflowEvent",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class NovelWorkflowStep(Base):
    __tablename__ = "novel_workflow_steps"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_workflow_runs.id", ondelete="CASCADE"),
        index=True,
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    step_type: Mapped[str] = mapped_column(String(128), default="")
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    result_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    error_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    run = relationship("NovelWorkflowRun", back_populates="steps")


class NovelWorkflowEvent(Base):
    __tablename__ = "novel_workflow_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_workflow_runs.id", ondelete="CASCADE"),
        index=True,
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("novel_workflow_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    level: Mapped[str] = mapped_column(String(16), default="info")
    event_type: Mapped[str] = mapped_column(String(64), default="unknown")
    message: Mapped[str] = mapped_column(LONGTEXT, default="")
    meta_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run = relationship("NovelWorkflowRun", back_populates="events")
