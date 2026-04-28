"""积分充值（占位）与管理员模型计价。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_admin, get_current_user
from app.models.recharge_order import RechargeOrder
from app.models.user import ModelPrice, PointsTransaction, User
from app.services.alipay_client import AlipayClient
from app.services.recharge_service import (
    MIN_CUSTOM_RECHARGE_POINTS,
    apply_recharge_paid,
    custom_points_step,
    fmt_amount_cny,
    get_recharge_packages_payload,
    resolve_recharge_plan,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])
# 以下 admin_router 路由均通过 Depends(get_current_admin) 校验管理员身份
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _setting_token(value: str) -> str:
    return (value or "").strip().split()[0] if (value or "").strip() else ""


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
    package_id: str | None = None
    form_html: str


class RechargePackageOut(BaseModel):
    id: str
    title: str
    points: int
    amount_cny: int
    badge: str
    description: str
    price_per_100_points: float


class RechargeConfigOut(BaseModel):
    min_custom_points: int
    custom_points_step: int
    base_points_per_cny: int
    packages: list[RechargePackageOut]


@router.get("/recharge/config", response_model=RechargeConfigOut)
def get_recharge_config() -> RechargeConfigOut:
    return RechargeConfigOut(
        min_custom_points=MIN_CUSTOM_RECHARGE_POINTS,
        custom_points_step=custom_points_step(),
        base_points_per_cny=int(settings.points_per_cny or 10),
        packages=[RechargePackageOut(**item) for item in get_recharge_packages_payload()],
    )


class AlipayRechargeCreateBody(BaseModel):
    package_id: str | None = Field(None, max_length=64)
    custom_points: int | None = Field(None, ge=1, le=100_000)


def _append_return_order(url: str, out_trade_no: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["sf_order"] = out_trade_no
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _resolve_return_url(request: Request, out_trade_no: str) -> str:
    configured = (settings.alipay_return_url or "").strip()
    base = configured or f"{str(request.base_url).rstrip('/')}/recharge"
    return _append_return_order(base, out_trade_no)


@router.post("/recharge/alipay-form", response_model=AlipayRechargeCreateOut)
def create_alipay_recharge_form(
    body: AlipayRechargeCreateBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlipayRechargeCreateOut:
    if not settings.alipay_notify_url:
        raise HTTPException(500, "支付未配置，请联系管理员")

    points, amount_cny, package_id = resolve_recharge_plan(body.package_id, body.custom_points)

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
    logger.info(
        "alipay recharge order created | out_trade_no=%s user_id=%s amount_cny=%s points=%s",
        out_trade_no,
        user.id,
        amount_cny,
        points,
    )

    subject = f"StoryForge 积分充值 {points} 积分"
    form_html = AlipayClient().page_pay_form(
        out_trade_no=out_trade_no,
        total_amount=fmt_amount_cny(amount_cny),
        subject=subject,
        notify_url=settings.alipay_notify_url,
        return_url=_resolve_return_url(request, out_trade_no),
    )
    return AlipayRechargeCreateOut(
        out_trade_no=out_trade_no,
        amount_cny=amount_cny,
        points=points,
        package_id=package_id,
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


def _serialize_recharge_order(row: RechargeOrder) -> RechargeOrderOut:
    return RechargeOrderOut(
        out_trade_no=row.out_trade_no,
        amount_cny=int(row.amount_cny or 0),
        points=int(row.points or 0),
        status=row.status,
        trade_status=row.trade_status,
        created_at=row.created_at,
        paid_at=row.paid_at,
    )


@router.get("/recharge/orders/{out_trade_no}", response_model=RechargeOrderOut)
def get_recharge_order(
    out_trade_no: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RechargeOrderOut:
    row = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == out_trade_no).first()
    if not row or row.user_id != user.id:
        raise HTTPException(404, "订单不存在")
    return _serialize_recharge_order(row)


@router.post("/recharge/orders/{out_trade_no}/refresh", response_model=RechargeOrderOut)
def refresh_recharge_order(
    out_trade_no: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RechargeOrderOut:
    order = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == out_trade_no).first()
    if not order or order.user_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status in ("paid", "closed"):
        return _serialize_recharge_order(order)

    q = AlipayClient().trade_query_sync(order.out_trade_no)
    if q.code and q.code != "10000":
        logger.warning(
            "alipay trade query non-success | out_trade_no=%s code=%s msg=%s sub_code=%s sub_msg=%s",
            order.out_trade_no,
            q.code,
            q.msg,
            q.sub_code,
            q.sub_msg,
        )
    order.query_raw = json.dumps(q.raw, ensure_ascii=False)
    order.reconciled_at = datetime.utcnow()
    order.trade_status = q.trade_status or order.trade_status
    order.alipay_trade_no = q.alipay_trade_no or order.alipay_trade_no

    if q.total_amount and q.total_amount != fmt_amount_cny(int(order.amount_cny or 0)):
        logger.warning(
            "alipay refresh amount mismatch | out_trade_no=%s expected=%s actual=%s",
            order.out_trade_no,
            fmt_amount_cny(int(order.amount_cny or 0)),
            q.total_amount,
        )
        db.commit()
        raise HTTPException(400, "订单金额校验失败")

    if q.trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        apply_recharge_paid(db, order, q.trade_status, q.alipay_trade_no, q.raw, via="query")
        logger.info(
            "alipay recharge credited by refresh | out_trade_no=%s trade_no=%s status=%s points=%s",
            order.out_trade_no,
            q.alipay_trade_no,
            q.trade_status,
            order.points,
        )
    elif q.trade_status in ("TRADE_CLOSED",):
        order.status = "closed"
    elif order.status == "created":
        order.status = "pending"

    db.commit()
    db.refresh(order)
    return _serialize_recharge_order(order)


@router.post("/recharge/alipay-notify")
async def alipay_notify(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    if not params:
        logger.warning("alipay notify rejected | reason=empty_form")
        return PlainTextResponse("failure")

    client = AlipayClient()
    if not client.verify(params):
        logger.warning(
            "alipay notify rejected | reason=verify_failed out_trade_no=%s trade_no=%s",
            params.get("out_trade_no") or "",
            params.get("trade_no") or "",
        )
        return PlainTextResponse("failure")
    app_id = params.get("app_id") or ""
    expected_app_id = _setting_token(settings.alipay_app_id)
    if app_id and app_id != expected_app_id:
        logger.warning(
            "alipay notify rejected | reason=app_id_mismatch out_trade_no=%s got=%s expected=%s",
            params.get("out_trade_no") or "",
            app_id,
            expected_app_id,
        )
        return PlainTextResponse("failure")
    expected_seller_id = _setting_token(settings.alipay_seller_id)
    if expected_seller_id:
        seller_id = params.get("seller_id") or ""
        if seller_id != expected_seller_id:
            logger.warning(
                "alipay notify rejected | reason=seller_id_mismatch out_trade_no=%s got=%s expected=%s",
                params.get("out_trade_no") or "",
                seller_id,
                expected_seller_id,
            )
            return PlainTextResponse("failure")

    out_trade_no = params.get("out_trade_no") or ""
    trade_status = params.get("trade_status") or ""
    total_amount = params.get("total_amount") or ""
    alipay_trade_no = params.get("trade_no") or ""

    order = db.query(RechargeOrder).filter(RechargeOrder.out_trade_no == out_trade_no).first()
    if not order:
        logger.warning("alipay notify rejected | reason=order_not_found out_trade_no=%s", out_trade_no)
        return PlainTextResponse("failure")

    if total_amount and total_amount != fmt_amount_cny(int(order.amount_cny or 0)):
        logger.warning(
            "alipay notify rejected | reason=amount_mismatch out_trade_no=%s expected=%s actual=%s",
            out_trade_no,
            fmt_amount_cny(int(order.amount_cny or 0)),
            total_amount,
        )
        return PlainTextResponse("failure")

    order.notify_raw = json.dumps(params, ensure_ascii=False)
    order.notified_at = datetime.utcnow()
    order.trade_status = trade_status
    order.alipay_trade_no = alipay_trade_no or order.alipay_trade_no

    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        apply_recharge_paid(db, order, trade_status, alipay_trade_no, params, via="notify")
        db.commit()
        logger.info(
            "alipay recharge credited by notify | out_trade_no=%s trade_no=%s status=%s points=%s",
            out_trade_no,
            alipay_trade_no,
            trade_status,
            order.points,
        )
        return PlainTextResponse("success")

    if trade_status in ("TRADE_CLOSED",):
        order.status = "closed"
        db.commit()
        return PlainTextResponse("success")

    db.commit()
    logger.info(
        "alipay notify accepted without credit | out_trade_no=%s trade_no=%s status=%s",
        out_trade_no,
        alipay_trade_no,
        trade_status,
    )
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
    if q.code and q.code != "10000":
        logger.warning(
            "admin alipay reconcile non-success | out_trade_no=%s code=%s msg=%s sub_code=%s sub_msg=%s",
            order.out_trade_no,
            q.code,
            q.msg,
            q.sub_code,
            q.sub_msg,
        )
    order.query_raw = json.dumps(q.raw, ensure_ascii=False)
    order.reconciled_at = datetime.utcnow()
    order.trade_status = q.trade_status or order.trade_status
    order.alipay_trade_no = q.alipay_trade_no or order.alipay_trade_no

    if q.total_amount and q.total_amount != fmt_amount_cny(int(order.amount_cny or 0)):
        logger.warning(
            "admin alipay reconcile amount mismatch | out_trade_no=%s expected=%s actual=%s",
            order.out_trade_no,
            fmt_amount_cny(int(order.amount_cny or 0)),
            q.total_amount,
        )
        db.commit()
        raise HTTPException(400, "金额不匹配，已记录查询结果")

    if q.trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        apply_recharge_paid(db, order, q.trade_status, q.alipay_trade_no, q.raw, via="query")
        logger.info(
            "alipay recharge credited by admin reconcile | out_trade_no=%s trade_no=%s status=%s points=%s",
            order.out_trade_no,
            q.alipay_trade_no,
            q.trade_status,
            order.points,
        )
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
    p = func.coalesce(
        ModelPrice.prompt_price_cny_per_million_tokens,
        ModelPrice.price_cny_per_million_tokens,
        0.0,
    )
    c = func.coalesce(
        ModelPrice.completion_price_cny_per_million_tokens,
        ModelPrice.price_cny_per_million_tokens,
        0.0,
    )
    rows = (
        db.query(ModelPrice)
        .filter(ModelPrice.enabled.is_(True))
        .order_by((p + c).asc(), ModelPrice.model_id.asc())
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
