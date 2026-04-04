"""注册 / 登录 / 当前用户。"""

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
import random
import string

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.core.rate_limit import limiter
from app.services.email_service import send_otp_email
from app.core.redis import OTPHelper
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=2, max_length=64)
    otp: str = Field(..., min_length=6, max_length=6)
    password: str = Field(..., min_length=6, max_length=128)


class LoginBody(BaseModel):
    username_or_email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    points_balance: int
    is_admin: bool


@router.post("/send-otp")
@limiter.limit("5/minute")
async def send_otp(
    request: Request,
    email: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    发送邮箱验证码。
    """
    email = email.strip().lower()
    
    # 1. 尝试获取原子锁，防止并发刷邮件
    if not await OTPHelper.try_lock_send_limit(email):
        raise HTTPException(429, "发送过于频繁，请 60 秒后再试")

    # 2. 生成验证码
    otp = "".join(random.choices(string.digits, k=6))
    
    try:
        # 3. 发送邮件（耗时操作）
        await send_otp_email(email, otp)
        # 4. 存入 Redis
        await OTPHelper.set_otp(email, otp)
        return {"status": "ok", "message": "验证码已发送"}
    except Exception as e:
        # 邮件发送彻底失败时，解除频率锁定，允许用户重试
        await OTPHelper.unlock_send_limit(email)
        logger.error(f"OTP send error for {email}: {str(e)}", exc_info=True)
        raise HTTPException(500, f"邮件发送失败: {str(e)}")


@router.post("/register", response_model=TokenOut)
@limiter.limit("10/minute")
async def register(
    request: Request,
    db: Session = Depends(get_db),
    data: RegisterBody = Body(...),
) -> TokenOut:
    email = data.email.strip().lower()
    username = data.username.strip()
    
    # 1. 验证 OTP
    saved_otp = await OTPHelper.get_otp(email)
    if not saved_otp or saved_otp != data.otp:
        raise HTTPException(400, "验证码错误或已过期")

    # 2. 检查邮箱和用户名是否已存在
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "该邮箱已注册")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(400, "用户名已被占用，换一个吧")

    # 3. 创建用户
    n_users = db.query(func.count(User.id)).scalar() or 0
    is_admin = n_users == 0
    points = max(0, int(settings.register_initial_points))
    
    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(data.password),
        points_balance=points,
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 4. 注册成功后删除 OTP
    await OTPHelper.delete_otp(email)

    token = create_access_token({"sub": user.id})
    return TokenOut(access_token=token)


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(
    request: Request,
    db: Session = Depends(get_db),
    data: LoginBody = Body(...),
) -> TokenOut:
    identifier = (data.username_or_email or "").strip()
    # 支持用户名或邮箱登录
    user = db.query(User).filter(
        or_(User.username == identifier, User.email == identifier)
    ).first()
    
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "账号或密码错误")
        
    token = create_access_token({"sub": user.id})
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current: User = Depends(get_current_user)) -> UserOut:
    """需 Header: Authorization: Bearer <token>"""
    return UserOut(
        id=current.id,
        username=current.username,
        email=current.email,
        points_balance=int(current.points_balance or 0),
        is_admin=bool(current.is_admin),
    )
