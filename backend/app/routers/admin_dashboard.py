from __future__ import annotations

from datetime import datetime, timedelta
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.invite_code import InviteCode
from app.models.user import User, TokenUsage, PointsTransaction
from app.models.novel import Novel, Chapter
from app.services.app_config_service import get_app_config

# 本模块路由均通过 Depends(get_current_admin) 校验管理员身份
router = APIRouter(prefix="/api/admin", tags=["admin-dashboard"])


class DashboardStatsOut(BaseModel):
    total_tokens: int
    total_chapters: int
    total_novels: int
    total_users: int


class PointsAdjustBody(BaseModel):
    amount_points: int
    note: str = ""


class UserFreezeBody(BaseModel):
    reason: str = ""


class InviteCodeCreateBody(BaseModel):
    expires_in_days: int | None = Field(default=7, ge=1, le=3650)
    note: str = ""


class InviteCodeOut(BaseModel):
    id: str
    code: str
    is_frozen: bool
    expires_at: datetime | None = None
    used_at: datetime | None = None
    used_by_user_id: str | None = None
    used_by_username: str | None = None
    note: str
    created_at: datetime
    created_by_admin_id: str
    created_by_admin_username: str | None = None


class InviteCodeListOut(BaseModel):
    items: list[InviteCodeOut]
    total: int
    page: int
    page_size: int


class RegistrationModeBody(BaseModel):
    invite_only: bool


class RegistrationModeOut(BaseModel):
    invite_only: bool


@router.get("/dashboard/stats", response_model=DashboardStatsOut)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> DashboardStatsOut:
    total_tokens = db.query(func.sum(TokenUsage.total_tokens)).scalar() or 0
    total_chapters = db.query(func.count(Chapter.id)).filter(Chapter.status == "approved").scalar() or 0
    total_novels = db.query(func.count(Novel.id)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0

    return DashboardStatsOut(
        total_tokens=total_tokens,
        total_chapters=total_chapters,
        total_novels=total_novels,
        total_users=total_users,
    )


@router.post("/users/{user_id}/adjust-points")
def adjust_user_points(
    user_id: str,
    data: PointsAdjustBody,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """管理员手动调整用户积分。"""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    
    # 调整积分
    user.points_balance += data.amount_points
    
    # 记录流水
    tx = PointsTransaction(
        user_id=user.id,
        amount_points=data.amount_points,
        transaction_type="admin_adjust",
        note=data.note or f"管理员 {admin.username} 手动调整"
    )
    db.add(tx)
    db.commit()
    return {"status": "ok", "new_balance": user.points_balance}


@router.post("/users/{user_id}/freeze")
def freeze_user(
    user_id: str,
    data: UserFreezeBody,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id:
        raise HTTPException(400, "不能冻结当前管理员自己")
    user.is_frozen = True
    user.frozen_reason = data.reason.strip()
    user.frozen_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "is_frozen": True}


@router.post("/users/{user_id}/unfreeze")
def unfreeze_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    user.is_frozen = False
    user.frozen_reason = ""
    user.frozen_at = None
    db.commit()
    return {"status": "ok", "is_frozen": False}


class UserAdminOut(BaseModel):
    id: str
    username: str
    email: str
    created_at: datetime
    points_balance: int
    total_tokens_used: int
    is_admin: bool
    is_frozen: bool
    frozen_reason: str


@router.get("/users", response_model=list[UserAdminOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> list[UserAdminOut]:
    users = db.query(User).order_by(User.created_at.desc()).all()
    out = []
    for u in users:
        tokens = db.query(func.sum(TokenUsage.total_tokens)).filter(TokenUsage.user_id == u.id).scalar() or 0
        out.append(
            UserAdminOut(
                id=u.id,
                username=u.username,
                email=u.email,
                created_at=u.created_at,
                points_balance=u.points_balance,
                total_tokens_used=tokens,
                is_admin=bool(u.is_admin),
                is_frozen=bool(u.is_frozen),
                frozen_reason=u.frozen_reason or "",
            )
        )
    return out


class DailyTokenUsageOut(BaseModel):
    date: str
    total_tokens: int


@router.get("/users/{user_id}/token-usage/daily", response_model=list[DailyTokenUsageOut])
def get_user_daily_token_usage(
    user_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> list[DailyTokenUsageOut]:
    # Query token usage for the past N days, grouped by date
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # We need to format created_at as YYYY-MM-DD for grouping
    # Since DB might be SQLite or Postgres, we do simple string extraction if SQLite, or use func.date for Postgres.
    # A safe cross-db way is to fetch all rows and group in python, given it's a small app
    usages = db.query(TokenUsage.created_at, TokenUsage.total_tokens).filter(
        TokenUsage.user_id == user_id,
        TokenUsage.created_at >= cutoff
    ).all()
    
    daily_map: dict[str, int] = {}
    for created_at, tokens in usages:
        date_str = created_at.strftime("%Y-%m-%d")
        daily_map[date_str] = daily_map.get(date_str, 0) + tokens
        
    out = []
    # Fill in zeros for missing days
    for i in range(days):
        d = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        out.append(DailyTokenUsageOut(date=d, total_tokens=daily_map.get(d, 0)))
        
    out.sort(key=lambda x: x.date, reverse=True)
    return out


@router.get("/registration-mode", response_model=RegistrationModeOut)
def admin_get_registration_mode(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> RegistrationModeOut:
    cfg = get_app_config(db)
    return RegistrationModeOut(invite_only=bool(getattr(cfg, "invite_only_registration", True)))


@router.post("/registration-mode", response_model=RegistrationModeOut)
def admin_set_registration_mode(
    data: RegistrationModeBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> RegistrationModeOut:
    cfg = get_app_config(db)
    cfg.invite_only_registration = bool(data.invite_only)
    db.commit()
    db.refresh(cfg)
    return RegistrationModeOut(invite_only=bool(cfg.invite_only_registration))


@router.get("/invite-codes", response_model=InviteCodeListOut)
def list_invite_codes(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> InviteCodeListOut:
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    page_size = min(100, page_size)

    total = db.query(func.count(InviteCode.id)).scalar() or 0
    offset = (page - 1) * page_size
    rows = (
        db.query(InviteCode)
        .order_by(InviteCode.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    items: list[InviteCodeOut] = []
    for row in rows:
        creator = db.get(User, row.created_by_admin_id) if row.created_by_admin_id else None
        used_by = db.get(User, row.used_by_user_id) if row.used_by_user_id else None
        items.append(
            InviteCodeOut(
                id=row.id,
                code=row.code,
                is_frozen=bool(row.is_frozen),
                expires_at=row.expires_at,
                used_at=row.used_at,
                used_by_user_id=row.used_by_user_id,
                used_by_username=used_by.username if used_by else None,
                note=row.note or "",
                created_at=row.created_at,
                created_by_admin_id=row.created_by_admin_id,
                created_by_admin_username=creator.username if creator else None,
            )
        )
    return InviteCodeListOut(items=items, total=int(total), page=int(page), page_size=int(page_size))


@router.post("/invite-codes", response_model=InviteCodeOut)
def create_invite_code(
    data: InviteCodeCreateBody,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> InviteCodeOut:
    expires_at = None
    if data.expires_in_days is not None:
        expires_at = datetime.utcnow() + timedelta(days=int(data.expires_in_days))

    code = ""
    for _ in range(10):
        code = secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()[:10]
        if not db.query(InviteCode).filter(InviteCode.code == code).first():
            break
    if not code:
        raise HTTPException(500, "生成邀请码失败，请重试")

    row = InviteCode(
        code=code,
        created_by_admin_id=admin.id,
        expires_at=expires_at,
        note=data.note.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return InviteCodeOut(
        id=row.id,
        code=row.code,
        is_frozen=bool(row.is_frozen),
        expires_at=row.expires_at,
        used_at=row.used_at,
        used_by_user_id=row.used_by_user_id,
        used_by_username=None,
        note=row.note or "",
        created_at=row.created_at,
        created_by_admin_id=row.created_by_admin_id,
        created_by_admin_username=admin.username,
    )


@router.post("/invite-codes/{invite_id}/freeze")
def freeze_invite_code(
    invite_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    row = db.get(InviteCode, invite_id)
    if not row:
        raise HTTPException(404, "邀请码不存在")
    row.is_frozen = True
    db.commit()
    return {"status": "ok", "is_frozen": True}


@router.post("/invite-codes/{invite_id}/unfreeze")
def unfreeze_invite_code(
    invite_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    row = db.get(InviteCode, invite_id)
    if not row:
        raise HTTPException(404, "邀请码不存在")
    row.is_frozen = False
    db.commit()
    return {"status": "ok", "is_frozen": False}


@router.delete("/invite-codes/{invite_id}")
def delete_invite_code(
    invite_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    row = db.get(InviteCode, invite_id)
    if not row:
        raise HTTPException(404, "邀请码不存在")
    if row.used_by_user_id:
        raise HTTPException(400, "已被使用的邀请码不允许删除")
    db.delete(row)
    db.commit()
    return {"success": True}
