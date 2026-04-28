from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.novel import NovelGenerationLog
from app.models.task import UserTask
from app.models.user import User
from app.services.novel_generation_common import append_generation_log
from app.services.task_cancel import request_cancel_batch
from app.services.user_task_service import TERMINAL_STATUSES
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
    offset: int = 0,
) -> dict[str, Any]:
    stale_cancel_cutoff = datetime.utcnow() - timedelta(seconds=30)
    stale_cancel_rows = (
        db.query(UserTask)
        .filter(
            UserTask.user_id == user.id,
            UserTask.status == "cancel_requested",
            UserTask.cancel_requested_at.isnot(None),
            UserTask.cancel_requested_at < stale_cancel_cutoff,
        )
        .all()
    )
    if stale_cancel_rows:
        now = datetime.utcnow()
        for row in stale_cancel_rows:
            row.status = "cancelled"
            row.finished_at = row.finished_at or row.cancel_requested_at or now
            if not (row.last_message or "").strip():
                row.last_message = "用户已结束任务"
        db.commit()

    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))

    q = db.query(UserTask).filter(UserTask.user_id == user.id)
    total = q.count()

    rows = q.order_by(UserTask.created_at.desc()).offset(off).limit(lim).all()

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
    return {"items": out, "total": total, "limit": lim, "offset": off}


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    t = db.get(UserTask, task_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "任务不存在")

    if t.status not in TERMINAL_STATUSES:
        raise HTTPException(400, "运行中的任务不可删除，请先取消任务")

    db.delete(t)
    db.commit()
    return {"status": "ok", "task_id": task_id}


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

    now = datetime.utcnow()
    t.cancel_requested_at = now
    if t.batch_id:
        request_cancel_batch(t.batch_id)

    if t.celery_task_id:
        try:
            celery_app.control.revoke(str(t.celery_task_id), terminate=True)
        except Exception:
            pass

    t.status = "cancelled"
    t.finished_at = now
    t.last_message = "用户已结束任务"
    if t.novel_id and t.batch_id:
        try:
            append_generation_log(
                db,
                novel_id=t.novel_id,
                batch_id=t.batch_id,
                event="user_task_cancelled",
                level="warning",
                message="用户已从「我的任务」结束该任务",
            )
        except Exception:
            # 日志写入失败不应影响任务终态写回
            pass
    db.commit()
    db.refresh(t)

    return {"status": "ok", "task_id": t.id, "task_status": t.status}

