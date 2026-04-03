from __future__ import annotations

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.deps import get_current_admin
from app.models.user import User, TokenUsage
from app.models.novel import Novel, Chapter

router = APIRouter(prefix="/api/admin", tags=["admin-dashboard"])


class DashboardStatsOut(BaseModel):
    total_tokens: int
    total_chapters: int
    total_novels: int
    total_users: int


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


class UserAdminOut(BaseModel):
    id: str
    username: str
    created_at: datetime
    points_balance: int
    total_tokens_used: int


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
                created_at=u.created_at,
                points_balance=u.points_balance,
                total_tokens_used=tokens,
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
