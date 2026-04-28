from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.recharge_order import RechargeOrder
from app.models.user import PointsTransaction, User


@dataclass(frozen=True)
class RechargePackage:
    id: str
    title: str
    points: int
    amount_cny: int
    badge: str = ""
    description: str = ""


RECHARGE_PACKAGES: tuple[RechargePackage, ...] = (
    RechargePackage(
        id="starter-100",
        title="标准包",
        points=100,
        amount_cny=10,
        badge="原价",
        description="适合首次充值",
    ),
    RechargePackage(
        id="value-500",
        title="进阶包",
        points=500,
        amount_cny=48,
        badge="推荐",
        description="比标准单价省 2 元",
    ),
    RechargePackage(
        id="pro-1000",
        title="高阶包",
        points=1000,
        amount_cny=90,
        badge="最划算",
        description="比标准单价省 10 元",
    ),
)

MIN_CUSTOM_RECHARGE_POINTS = 10


def fmt_amount_cny(amount_cny: int) -> str:
    return f"{int(amount_cny)}.00"


def custom_points_step() -> int:
    return max(1, int(settings.points_per_cny or 1))


def serialize_recharge_package(pkg: RechargePackage) -> dict[str, Any]:
    payload = asdict(pkg)
    payload["price_per_100_points"] = round((pkg.amount_cny / pkg.points) * 100, 2)
    return payload


def get_recharge_packages_payload() -> list[dict[str, Any]]:
    return [serialize_recharge_package(pkg) for pkg in RECHARGE_PACKAGES]


def resolve_recharge_plan(package_id: str | None, custom_points: int | None) -> tuple[int, int, str | None]:
    if package_id and custom_points is not None:
        raise HTTPException(400, "套餐充值和自定义充值只能二选一")
    if not package_id and custom_points is None:
        raise HTTPException(400, "请选择充值套餐或输入自定义积分")

    if package_id:
        pkg = next((item for item in RECHARGE_PACKAGES if item.id == package_id), None)
        if not pkg:
            raise HTTPException(400, "充值套餐不存在")
        return pkg.points, pkg.amount_cny, pkg.id

    points = int(custom_points or 0)
    step = custom_points_step()
    if points < MIN_CUSTOM_RECHARGE_POINTS:
        raise HTTPException(400, f"自定义充值最少 {MIN_CUSTOM_RECHARGE_POINTS} 积分")
    if points % step != 0:
        raise HTTPException(400, f"自定义积分需按 {step} 积分递增")
    return points, points // step, None


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
    if via == "notify":
        order.notify_raw = json.dumps(raw, ensure_ascii=False)
    else:
        order.query_raw = json.dumps(raw, ensure_ascii=False)
