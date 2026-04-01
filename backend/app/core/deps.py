"""FastAPI 依赖：当前用户与资源访问。"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.novel import Chapter, Novel
from app.models.user import User
from app.models.workflow import Workflow

security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="未登录或缺少 token")
    from app.core.security import decode_token

    payload = decode_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="无效 token")
    user_id = str(payload["sub"])
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_novel_access(db: Session, novel_id: str, user: User) -> Novel:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(status_code=404, detail="小说不存在")
    if user.is_admin:
        return n
    if n.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该小说")
    return n


def require_workflow_access(db: Session, workflow_id: str, user: User) -> Workflow:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if user.is_admin:
        return wf
    if wf.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该工作流")
    return wf


def require_chapter_access(db: Session, chapter_id: str, user: User) -> Chapter:
    ch = db.get(Chapter, chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="章节不存在")
    novel = db.get(Novel, ch.novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    if user.is_admin:
        return ch
    if novel.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该章节")
    return ch
