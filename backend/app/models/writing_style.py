from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Any

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from .user import User


class WritingStyle(Base):
    """文风管理模型。"""

    __tablename__ = "writing_styles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    reference_author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # 词库分析: {"tags": ["口语化", ...], "rules": ["控制文艺修饰词密度", ...], "forbidden": ["绝绝子", ...]}
    lexicon: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # 语句结构: {"sentence_length": 15, "complexity": "单句为主", "line_break": "21字一行", "punctuation": "引号冒号驱动", "rules": [...]}
    structure: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # 语气要求: {"primary": ["感性抒情", "理性客观"], "description": "...", "rules": [...]}
    tone: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # 修辞指令: {"types": {"排比": "高", "反问": "高", ...}, "rules": [...]}
    rhetoric: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    # 负面提示词 (禁止生成的文本案例)
    negative_prompts: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    # 代表段落 (Few-shot 示例)
    snippets: Mapped[List[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship("User", backref="writing_styles")
