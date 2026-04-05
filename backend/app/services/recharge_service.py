from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.recharge_order import RechargeOrder
from app.models.user import PointsTransaction, User


def fmt_amount_cny(amount_cny: int) -> str:
    return f"{int(amount_cny)}.00"


def apply_recharge_paid(
    db: Session,
    order: RechargeOrder,
    trade_status: str,
    alipay_trade_no: str,
    raw: dict,
    via: str,
) -> None:
    if order.credited_at is not None:
        return

    user = db.get(User, order.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")

    user.points_balance = int(user.points_balance or 0) + int(order.points or 0)
    db.add(
        PointsTransaction(
            id=str(uuid.uuid4()),
            user_id=user.id,
            amount_points=int(order.points or 0),
            transaction_type="recharge",
            note=f"alipay out_trade_no={order.out_trade_no} trade_no={alipay_trade_no} via={via}",
        )
    )
    order.status = "paid"
    order.trade_status = trade_status
    order.alipay_trade_no = alipay_trade_no or order.alipay_trade_no
    order.paid_at = order.paid_at or datetime.utcnow()
    order.credited_at = datetime.utcnow()
    order.query_raw = json.dumps(raw, ensure_ascii=False)

