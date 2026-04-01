"""积分充值（占位）与管理员模型计价。"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_admin, get_current_user
from app.models.user import ModelPrice, PointsTransaction, User

router = APIRouter(prefix="/api/billing", tags=["billing"])
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


class ModelPriceOut(BaseModel):
    id: str
    model_id: str
    price_cny_per_million_tokens: float
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
            enabled=bool(r.enabled),
            display_name=r.display_name or r.model_id,
        )
        for r in rows
    ]


class ModelPriceCreate(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=128)
    price_cny_per_million_tokens: float = Field(default=1.0, ge=0)
    enabled: bool = True
    display_name: str = ""


class ModelPricePatch(BaseModel):
    price_cny_per_million_tokens: float | None = None
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
        enabled=bool(row.enabled),
        display_name=row.display_name or row.model_id,
    )
