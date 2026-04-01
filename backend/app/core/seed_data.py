"""启动时种子：默认模型计价等。"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import ModelPrice

logger = logging.getLogger(__name__)


def ensure_default_model_prices(db: Session) -> None:
    """为常用模型 ID 写入默认单价（元/百万 token），已存在则跳过。"""
    defaults: list[tuple[str, str, float]] = []
    for mid, name, cny in (
        (settings.ai302_novel_model, "默认小说模型", 1.0),
        (settings.ai302_chat_model, "默认对话模型", 1.0),
        (settings.ai302_kimi_model, "Kimi", 1.0),
        (settings.ai302_doubao_model, "Doubao", 1.0),
        (settings.custom_llm_model.strip(), "自建代理", 1.0),
    ):
        if not mid:
            continue
        row = db.query(ModelPrice).filter(ModelPrice.model_id == mid).first()
        if row:
            continue
        db.add(
            ModelPrice(
                id=str(uuid.uuid4()),
                model_id=mid,
                price_cny_per_million_tokens=cny,
                enabled=True,
                display_name=name or mid,
            )
        )
        logger.info("seed: model_prices %s", mid)
    db.commit()
