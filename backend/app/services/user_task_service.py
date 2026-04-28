from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.task import UserTask


TERMINAL_STATUSES = {"done", "failed", "cancelled", "skipped"}


def create_user_task(
    db: Session,
    *,
    user_id: str,
    kind: str,
    title: str,
    status: str = "queued",
    batch_id: str | None = None,
    celery_task_id: str | None = None,
    novel_id: str | None = None,
    volume_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> UserTask:
    row = UserTask(
        user_id=user_id,
        kind=kind,
        status=status,
        title=title,
        batch_id=batch_id,
        celery_task_id=celery_task_id,
        novel_id=novel_id,
        volume_id=volume_id,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
        last_message="",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_user_task_by_batch_id(
    db: Session,
    *,
    batch_id: str,
    status: str | None = None,
    last_message: str | None = None,
    progress: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> UserTask | None:
    if not batch_id:
        return None
    row = (
        db.query(UserTask)
        .filter(UserTask.batch_id == batch_id)
        .order_by(UserTask.created_at.desc())
        .first()
    )
    if not row:
        return None
    # 用户已从前端结束任务后不可被 Worker / 僵尸回收写回 done、failed 等
    if (
        str(row.status or "") == "cancelled"
        and status is not None
        and status != "cancelled"
    ):
        return row
    if status is not None:
        row.status = status
    if last_message is not None:
        row.last_message = last_message
    if progress is not None:
        row.progress = int(progress)
    if started_at is not None:
        if row.started_at is None:
            row.started_at = started_at
    if finished_at is not None:
        if row.finished_at is None:
            row.finished_at = finished_at
    db.commit()
    return row


def request_cancel_user_task(db: Session, *, task: UserTask) -> UserTask:
    now = datetime.utcnow()
    task.cancel_requested_at = now
    if task.status not in TERMINAL_STATUSES:
        task.status = "cancel_requested"
    db.commit()
    db.refresh(task)
    return task
