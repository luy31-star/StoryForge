"""注册 / 登录 / 当前用户。"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.core.rate_limit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    points_balance: int
    is_admin: bool


@router.post("/register", response_model=TokenOut)
@limiter.limit("10/minute")
def register(
    request: Request,
    db: Session = Depends(get_db),
    data: RegisterBody = Body(...),
) -> TokenOut:
    uname = data.username.strip()
    if not uname:
        raise HTTPException(400, "用户名不能为空")
    exists = db.query(User).filter(User.username == uname).first()
    if exists:
        raise HTTPException(400, "用户名已存在")

    n_users = db.query(func.count(User.id)).scalar() or 0
    # 首个注册用户为管理员（后续可通过数据库调整）
    is_admin = n_users == 0

    points = max(0, int(settings.register_initial_points))
    user = User(
        username=uname,
        hashed_password=hash_password(data.password),
        points_balance=points,
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id})
    return TokenOut(access_token=token)


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(
    request: Request,
    db: Session = Depends(get_db),
    data: LoginBody = Body(...),
) -> TokenOut:
    uname = (data.username or "").strip()
    user = db.query(User).filter(User.username == uname).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token({"sub": user.id})
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> UserOut:
    """需 Header: Authorization: Bearer <token>"""
    return UserOut(
        id=current.id,
        username=current.username,
        points_balance=int(current.points_balance or 0),
        is_admin=bool(current.is_admin),
    )
