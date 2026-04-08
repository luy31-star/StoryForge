"""积分：按 token 扣费（1 元 = points_per_cny 积分）。"""

from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import ModelPrice, PointsTransaction, TokenUsage, User

logger = logging.getLogger(__name__)


def tokens_to_points(db: Session, model_id: str, prompt_tokens: int, completion_tokens: int) -> int:
    """
    扣费积分 = (输入 token / 1e6 * 输入单价 + 输出 token / 1e6 * 输出单价) * points_per_cny
    向上取整到整数积分。
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0

    row = (
        db.query(ModelPrice)
        .filter(ModelPrice.model_id == model_id, ModelPrice.enabled.is_(True))
        .first()
    )
    if row:
        p_price = float(row.prompt_price_cny_per_million_tokens or row.price_cny_per_million_tokens or 0)
        c_price = float(row.completion_price_cny_per_million_tokens or row.price_cny_per_million_tokens or 0)
    else:
        # 未配置时按 1 元/百万 token 计
        p_price = 1.0
        c_price = 1.0

    cost_cny = (prompt_tokens / 1_000_000.0) * p_price + (completion_tokens / 1_000_000.0) * c_price
    raw_points = cost_cny * settings.points_per_cny
    return max(1, int(math.ceil(raw_points))) if raw_points > 0 else 0


def extract_usage_from_response(data: Any) -> dict[str, int] | None:
    if not isinstance(data, dict):
        return None
    u = data.get("usage")
    if not isinstance(u, dict):
        return None
    pt = int(u.get("prompt_tokens") or 0)
    ct = int(u.get("completion_tokens") or 0)
    tt = int(u.get("total_tokens") or (pt + ct))
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}


def consume_points_for_llm(
    db: Session,
    *,
    user_id: str,
    model_id: str,
    usage: dict[str, int] | None,
) -> int:
    """
    根据 usage 扣积分并记账。返回本次扣除的积分（0 表示未扣或无法解析用量）。
    """
    if not usage:
        return 0
    total = int(usage.get("total_tokens") or 0)
    if total <= 0:
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        total = pt + ct
    if total <= 0:
        return 0

    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    cost = tokens_to_points(db, model_id, pt, ct)
    if cost <= 0:
        return 0

    user = db.get(User, user_id)
    if not user:
        logger.warning("billing: user missing | user_id=%s", user_id)
        return 0

    if user.points_balance < cost:
        raise RuntimeError(
            f"积分不足：需要 {cost}，当前 {user.points_balance}"
        )

    user.points_balance -= cost
    db.add(
        TokenUsage(
            user_id=user_id,
            model_id=model_id,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=total,
            cost_points=cost,
        )
    )
    db.add(
        PointsTransaction(
            user_id=user_id,
            amount_points=-cost,
            transaction_type="consumption",
            note=f"LLM {model_id} tokens={total}",
        )
    )
    db.flush()
    return cost


def assert_sufficient_balance(db: Session, user_id: str, min_points: int = 1) -> None:
    user = db.get(User, user_id)
    if not user:
        raise RuntimeError("用户不存在")
    if user.points_balance < min_points:
        raise RuntimeError(
            f"积分不足：至少需要 {min_points} 积分，当前 {user.points_balance}"
        )


def consume_points_fixed(
    db: Session,
    *,
    user_id: str,
    cost_points: int,
    note: str,
) -> int:
    cost = int(cost_points or 0)
    if cost <= 0:
        return 0

    user = db.get(User, user_id)
    if not user:
        logger.warning("billing: user missing | user_id=%s", user_id)
        return 0

    if user.points_balance < cost:
        raise RuntimeError(f"积分不足：需要 {cost}，当前 {user.points_balance}")

    user.points_balance -= cost
    db.add(
        PointsTransaction(
            user_id=user_id,
            amount_points=-cost,
            transaction_type="consumption",
            note=note,
        )
    )
    db.flush()
    return cost


def estimate_points_for_tts(text: str) -> int:
    n = len((text or "").strip())
    if n <= 0:
        return 0
    return max(1, int(math.ceil(n / 500.0)))


def estimate_points_for_video_submit() -> int:
    return 10
