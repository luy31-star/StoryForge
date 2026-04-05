"""积分充值（占位）与管理员模型计价。"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_admin, get_current_user
from app.models.recharge_order import RechargeOrder
from app.models.user import ModelPrice, PointsTransaction, User
from app.services.alipay_client import AlipayClient
from app.services.recharge_service import apply_recharge_paid, fmt_amount_cny

router = APIRouter(prefix="/api/billing", tags=["billing"])
# 以下 admin_router 路由均通过 Depends(get_current_admin) 校验管理员身份
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


class RechargeBody(BaseModel):
    amount_cny: int = Field(..., ge=1, le=100_000, description="模拟充值人民币金额")


class RechargeOut(BaseModel):
    points_added: int
    points_balance: int


@router.post("/recharge", response_model=RechargeOut)
def mock_recharge(
    body: RechargeBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RechargeOut:
    """占位：直接增加积分并记账（无真实支付）。"""
    pts = int(body.amount_cny) * settings.points_per_cny
    if pts <= 0:
        raise HTTPException(400, "充值积分无效")

    u = db.get(User, user.id)
    if not u:
        raise HTTPException(401, "用户不存在")
    u.points_balance = int(u.points_balance or 0) + pts
    db.add(
        PointsTransaction(
            id=str(uuid.uuid4()),
            user_id=u.id,
            amount_points=pts,
            transaction_type="recharge",
            note=f"mock CNY {body.amount_cny}",
        )
    )
    db.commit()
    db.refresh(u)
    return RechargeOut(points_added=pts, points_balance=int(u.points_balance))


class AlipayRechargeCreateOut(BaseModel):
    out_trade_no: str
    amount_cny: int
    points: int
    form_html: str


@router.post("/recharge/alipay-form", response_model=AlipayRechargeCreateOut)
def create_alipay_recharge_form(
    body: RechargeBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlipayRechargeCreateOut:
    if not settings.alipay_notify_url or not settings.alipay_return_url:
        raise HTTPException(500, "支付未配置，请联系管理员")

    amount_cny = int(body.amount_cny)
    points = amount_cny * int(settings.points_per_cny)
    if points <= 0:
        raise HTTPException(400, "充值金额无效")

    out_trade_no = f"sf{int(time.time())}{uuid.uuid4().hex[:10]}"
    order = RechargeOrder(
        user_id=user.id,
        channel="alipay",
        out_trade_no=out_trade_no,
        amount_cny=amount_cny,
        points=points,
        status="created",
    )
    db.add(order)
    db.commit()

    subject = f"StoryForge 积分充值 {amount_cny} 元"
    form_html = AlipayClient().page_pay_form(
        out_trade_no=out_trade_no,
        total_amount=fmt_amount_cny(amount_cny),
        subject=subject,
        notify_url=settings.alipay_notify_url,
        return_url=settings.alipay_return_url,
    )
    return AlipayRechargeCreateOut(
        out_trade_no=out_trade_no,
        amount_cny=amount_cny,
        points=points,
        form_html=form_html,
    )


class RechargeOrderOut(BaseModel):
    out_trade_no: str
    amount_cny: int
    points: int
    status: str
    trade_status: str
    created_at: datetime
    paid_at: datetime | None = None


@router.get("/recharge/orders/{out_trade_no}", response_model=RechargeOrderOut)
def get_recharge_order(
    out_trade_no: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RechargeOrderOut:
    row = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == out_trade_no).first()
    if not row or row.user_id != user.id:
        raise HTTPException(404, "订单不存在")
    return RechargeOrderOut(
        out_trade_no=row.out_trade_no,
        amount_cny=int(row.amount_cny or 0),
        points=int(row.points or 0),
        status=row.status,
        trade_status=row.trade_status,
        created_at=row.created_at,
        paid_at=row.paid_at,
    )


@router.post("/recharge/alipay-notify")
async def alipay_notify(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    if not params:
        return PlainTextResponse("failure")

    client = AlipayClient()
    if not client.verify(params):
        return PlainTextResponse("failure")

    out_trade_no = params.get("out_trade_no") or ""
    trade_status = params.get("trade_status") or ""
    total_amount = params.get("total_amount") or ""
    alipay_trade_no = params.get("trade_no") or ""

    order = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == out_trade_no).first()
    if not order:
        return PlainTextResponse("failure")

    if total_amount and total_amount != fmt_amount_cny(int(order.amount_cny or 0)):
        return PlainTextResponse("failure")

    order.notify_raw = json.dumps(params, ensure_ascii=False)
    order.notified_at = datetime.utcnow()
    order.trade_status = trade_status
    order.alipay_trade_no = alipay_trade_no or order.alipay_trade_no

    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        apply_recharge_paid(db, order, trade_status, alipay_trade_no, params, via="notify")
        db.commit()
        return PlainTextResponse("success")

    if trade_status in ("TRADE_CLOSED",):
        order.status = "closed"
        db.commit()
        return PlainTextResponse("success")

    db.commit()
    return PlainTextResponse("success")


class AdminAlipayReconcileBody(BaseModel):
    out_trade_no: str = Field(..., min_length=8, max_length=64)


@admin_router.post("/recharge/alipay/reconcile-one")
def admin_reconcile_one(
    body: AdminAlipayReconcileBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    client = AlipayClient()
    order = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == body.out_trade_no).first()
    if not order:
        raise HTTPException(404, "订单不存在")

    q = client.trade_query_sync(order.out_trade_no)
    order.query_raw = json.dumps(q.raw, ensure_ascii=False)
    order.reconciled_at = datetime.utcnow()
    order.trade_status = q.trade_status or order.trade_status
    order.alipay_trade_no = q.alipay_trade_no or order.alipay_trade_no

    if q.total_amount and q.total_amount != _fmt_amount(int(order.amount_cny or 0)):
        db.commit()
        raise HTTPException(400, "金额不匹配，已记录查询结果")

    if q.trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        apply_recharge_paid(db, order, q.trade_status, q.alipay_trade_no, q.raw, via="query")
    elif q.trade_status in ("TRADE_CLOSED",):
        order.status = "closed"

    db.commit()
    return {"status": "ok", "order_status": order.status, "trade_status": order.trade_status}


class ModelPriceOut(BaseModel):
    id: str
    model_id: str
    price_cny_per_million_tokens: float
    prompt_price_cny_per_million_tokens: float
    completion_price_cny_per_million_tokens: float
    enabled: bool
    display_name: str


@router.get("/model-prices", response_model=list[ModelPriceOut])
def list_public_model_prices(db: Session = Depends(get_db)) -> list[ModelPriceOut]:
    """对普通用户展示：仅已启用模型（用于前端选模型等）。"""
    rows = (
        db.query(ModelPrice)
        .filter(ModelPrice.enabled.is_(True))
        .order_by(ModelPrice.model_id.asc())
        .all()
    )
    return [
        ModelPriceOut(
            id=r.id,
            model_id=r.model_id,
            price_cny_per_million_tokens=float(r.price_cny_per_million_tokens or 0),
            prompt_price_cny_per_million_tokens=float(r.prompt_price_cny_per_million_tokens or 0),
            completion_price_cny_per_million_tokens=float(r.completion_price_cny_per_million_tokens or 0),
            enabled=bool(r.enabled),
            display_name=r.display_name or r.model_id,
        )
        for r in rows
    ]


class ModelPriceCreate(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=128)
    price_cny_per_million_tokens: float = Field(default=1.0, ge=0)
    prompt_price_cny_per_million_tokens: float = Field(default=1.0, ge=0)
    completion_price_cny_per_million_tokens: float = Field(default=1.0, ge=0)
    enabled: bool = True
    display_name: str = ""


class ModelPricePatch(BaseModel):
    price_cny_per_million_tokens: float | None = None
    prompt_price_cny_per_million_tokens: float | None = None
    completion_price_cny_per_million_tokens: float | None = None
    enabled: bool | None = None
    display_name: str | None = None


@admin_router.get("/model-prices", response_model=list[ModelPriceOut])
def admin_list_model_prices(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> list[ModelPriceOut]:
    rows = db.query(ModelPrice).order_by(ModelPrice.model_id.asc()).all()
    return [
        ModelPriceOut(
            id=r.id,
            model_id=r.model_id,
            price_cny_per_million_tokens=float(r.price_cny_per_million_tokens or 0),
            prompt_price_cny_per_million_tokens=float(r.prompt_price_cny_per_million_tokens or 0),
            completion_price_cny_per_million_tokens=float(r.completion_price_cny_per_million_tokens or 0),
            enabled=bool(r.enabled),
            display_name=r.display_name or r.model_id,
        )
        for r in rows
    ]


@admin_router.post("/model-prices", response_model=ModelPriceOut)
def admin_create_model_price(
    body: ModelPriceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> ModelPriceOut:
    mid = body.model_id.strip()
    if db.query(ModelPrice).filter(ModelPrice.model_id == mid).first():
        raise HTTPException(400, "model_id 已存在")
    row = ModelPrice(
        id=str(uuid.uuid4()),
        model_id=mid,
        price_cny_per_million_tokens=body.price_cny_per_million_tokens,
        prompt_price_cny_per_million_tokens=body.prompt_price_cny_per_million_tokens,
        completion_price_cny_per_million_tokens=body.completion_price_cny_per_million_tokens,
        enabled=body.enabled,
        display_name=body.display_name or mid,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ModelPriceOut(
        id=row.id,
        model_id=row.model_id,
        price_cny_per_million_tokens=float(row.price_cny_per_million_tokens or 0),
        prompt_price_cny_per_million_tokens=float(row.prompt_price_cny_per_million_tokens or 0),
        completion_price_cny_per_million_tokens=float(row.completion_price_cny_per_million_tokens or 0),
        enabled=bool(row.enabled),
        display_name=row.display_name or row.model_id,
    )


@admin_router.patch("/model-prices/{price_id}", response_model=ModelPriceOut)
def admin_patch_model_price(
    price_id: str,
    body: ModelPricePatch,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> ModelPriceOut:
    row = db.get(ModelPrice, price_id)
    if not row:
        raise HTTPException(404, "记录不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return ModelPriceOut(
        id=row.id,
        model_id=row.model_id,
        price_cny_per_million_tokens=float(row.price_cny_per_million_tokens or 0),
        prompt_price_cny_per_million_tokens=float(row.prompt_price_cny_per_million_tokens or 0),
        completion_price_cny_per_million_tokens=float(row.completion_price_cny_per_million_tokens or 0),
        enabled=bool(row.enabled),
        display_name=row.display_name or row.model_id,
    )


@admin_router.delete("/model-prices/{price_id}")
def admin_delete_model_price(
    price_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    row = db.get(ModelPrice, price_id)
    if not row:
        raise HTTPException(404, "记录不存在")
    db.delete(row)
    db.commit()
    return {"success": True}
