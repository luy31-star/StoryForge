"""小说结构化记忆规范化落表（与 novel_memories.payload_json 同步，便于查询与可视化）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NovelMemoryNormOutline(Base):
    """大纲与世界观摘要：每小说一行，随记忆版本替换。"""

    __tablename__ = "novel_memory_norm_outline"

    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    main_plot: Mapped[str] = mapped_column(LONGTEXT, default="")
    timeline_archive_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    # 全局硬约束：禁止事项/设定防火墙（JSON 字符串数组）
    forbidden_constraints_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class NovelMemoryNormSkill(Base):
    __tablename__ = "novel_memory_norm_skills"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(512), default="")
    detail_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    influence_score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NovelMemoryNormItem(Base):
    """物品 / 库存条目。"""

    __tablename__ = "novel_memory_norm_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(LONGTEXT, default="")
    detail_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    influence_score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NovelMemoryNormPet(Base):
    __tablename__ = "novel_memory_norm_pets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(512), default="")
    detail_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    influence_score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NovelMemoryNormCharacter(Base):
    __tablename__ = "novel_memory_norm_characters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(512), default="")
    role: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(512), default="")
    traits_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    detail_json: Mapped[str] = mapped_column(LONGTEXT, default="{}")
    influence_score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NovelMemoryNormRelation(Base):
    __tablename__ = "novel_memory_norm_relations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    src: Mapped[str] = mapped_column(String(512), default="")
    dst: Mapped[str] = mapped_column(String(512), default="")
    relation: Mapped[str] = mapped_column(LONGTEXT, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class NovelMemoryNormPlot(Base):
    """未完结线（open_plots）。"""

    __tablename__ = "novel_memory_norm_plots"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    body: Mapped[str] = mapped_column(LONGTEXT, default="")
    plot_type: Mapped[str] = mapped_column(String(32), default="Transient")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str] = mapped_column(LONGTEXT, default="")
    resolve_when: Mapped[str] = mapped_column(LONGTEXT, default="")
    introduced_chapter: Mapped[int] = mapped_column(Integer, default=0)
    last_touched_chapter: Mapped[int] = mapped_column(Integer, default=0)


class NovelMemoryNormChapter(Base):
    """章节级概括（canonical 时间线）。"""

    __tablename__ = "novel_memory_norm_chapters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    novel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    memory_version: Mapped[int] = mapped_column(Integer, default=0)
    chapter_no: Mapped[int] = mapped_column(Integer, default=0)
    chapter_title: Mapped[str] = mapped_column(String(512), default="")
    key_facts_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    causal_results_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    open_plots_added_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    open_plots_resolved_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
    # 情绪锚点与章末悬念（用于下一章衔接）
    emotional_state: Mapped[str] = mapped_column(LONGTEXT, default="")
    unresolved_hooks_json: Mapped[str] = mapped_column(LONGTEXT, default="[]")
