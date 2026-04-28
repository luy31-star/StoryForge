from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NovelRetrievalDocument(Base):
    __tablename__ = "novel_retrieval_documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(64), default="chapter")
    source_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    summary: Mapped[str] = mapped_column(LONGTEXT, default="")
    metadata_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    checksum: Mapped[str] = mapped_column(String(128), default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chunks = relationship(
        "NovelRetrievalChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class NovelRetrievalChunk(Base):
    __tablename__ = "novel_retrieval_chunks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novel_retrieval_documents.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_no: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(LONGTEXT, default="")
    content_hash: Mapped[str] = mapped_column(String(128), default="", index=True)
    vector_backend: Mapped[str] = mapped_column(String(32), default="qdrant")
    qdrant_point_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    metadata_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    document = relationship("NovelRetrievalDocument", back_populates="chunks")


class NovelRetrievalQueryLog(Base):
    __tablename__ = "novel_retrieval_query_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    query_text: Mapped[str] = mapped_column(LONGTEXT, default="")
    query_type: Mapped[str] = mapped_column(String(64), default="chapter_context")
    top_k: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
