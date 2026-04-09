from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.novel import NovelGenerationLog
from app.models.task import UserTask
from app.models.user import User
from app.services.task_cancel import request_cancel_batch
from app.services.user_task_service import TERMINAL_STATUSES, request_cancel_user_task
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _latest_log_for_batch(db: Session, batch_id: str) -> dict[str, Any] | None:
    if not batch_id:
        return None
    r = (
        db.query(NovelGenerationLog)
        .filter(NovelGenerationLog.batch_id == batch_id)
        .order_by(NovelGenerationLog.created_at.desc())
        .first()
    )
    if not r:
        return None
    try:
        meta = json.loads(r.meta_json or "{}")
    except Exception:
        meta = {}
    return {
        "event": r.event,
        "message": r.message,
        "level": r.level,
        "chapter_no": r.chapter_no,
        "meta": meta if isinstance(meta, dict) else {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("")
def list_my_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 50,
) -> dict[str, Any]:
    lim = max(1, min(int(limit or 50), 200))
    rows = (
        db.query(UserTask)
        .filter(UserTask.user_id == user.id)
        .order_by(UserTask.created_at.desc())
        .limit(lim)
        .all()
    )
    out: list[dict[str, Any]] = []
    for t in rows:
        last_log = _latest_log_for_batch(db, t.batch_id or "")
        out.append(
            {
                "id": t.id,
                "kind": t.kind,
                "status": t.status,
                "title": t.title,
                "batch_id": t.batch_id,
                "celery_task_id": t.celery_task_id,
                "novel_id": t.novel_id,
                "volume_id": t.volume_id,
                "progress": t.progress,
                "last_message": t.last_message,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "cancel_requested_at": t.cancel_requested_at.isoformat()
                if t.cancel_requested_at
                else None,
                "latest_log": last_log,
            }
        )
    return {"items": out}


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    t = db.get(UserTask, task_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    if t.status in TERMINAL_STATUSES:
        return {"status": "ok", "task_id": t.id, "task_status": t.status}

    request_cancel_user_task(db, task=t)

    if t.batch_id:
        request_cancel_batch(t.batch_id)

    if t.celery_task_id:
        try:
            celery_app.control.revoke(str(t.celery_task_id), terminate=True)
        except Exception:
            pass

    return {"status": "ok", "task_id": t.id, "task_status": t.status}

