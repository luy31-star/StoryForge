from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.novel_workflow_runtime import (
    NovelWorkflowEvent,
    NovelWorkflowRun,
    NovelWorkflowStep,
)


def create_workflow_run(
    db: Session,
    *,
    novel_id: str,
    run_type: str,
    trigger_source: str = "manual",
    batch_id: str = "",
    input_payload: dict[str, Any] | None = None,
    cursor_payload: dict[str, Any] | None = None,
) -> NovelWorkflowRun:
    run = NovelWorkflowRun(
        novel_id=novel_id,
        run_type=run_type,
        trigger_source=trigger_source,
        status="queued",
        batch_id=batch_id,
        input_json=json.dumps(input_payload or {}, ensure_ascii=False),
        cursor_json=json.dumps(cursor_payload or {}, ensure_ascii=False),
    )
    db.add(run)
    db.flush()
    return run


def get_workflow_run_by_batch_id(
    db: Session,
    *,
    batch_id: str,
) -> NovelWorkflowRun | None:
    if not batch_id:
        return None
    return (
        db.query(NovelWorkflowRun)
        .filter(NovelWorkflowRun.batch_id == batch_id)
        .order_by(NovelWorkflowRun.created_at.desc())
        .first()
    )


def touch_workflow_run_status(
    db: Session,
    run: NovelWorkflowRun,
    *,
    status: str,
    current_step: str | None = None,
    cursor_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
    error_payload: dict[str, Any] | None = None,
) -> NovelWorkflowRun:
    run.status = status
    if current_step is not None:
        run.current_step = current_step
    if cursor_payload is not None:
        run.cursor_json = json.dumps(cursor_payload, ensure_ascii=False)
    if output_payload is not None:
        run.output_json = json.dumps(output_payload, ensure_ascii=False)
    if error_payload is not None:
        run.error_json = json.dumps(error_payload, ensure_ascii=False)
    now = datetime.utcnow()
    if status == "running" and run.started_at is None:
        run.started_at = now
    if status in {"done", "failed", "cancelled", "blocked", "skipped"}:
        run.finished_at = now
    db.add(run)
    db.flush()
    return run


def upsert_workflow_step(
    db: Session,
    *,
    run: NovelWorkflowRun,
    step_type: str,
    sequence_no: int,
    status: str,
    payload: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
    error_payload: dict[str, Any] | None = None,
) -> NovelWorkflowStep:
    step = (
        db.query(NovelWorkflowStep)
        .filter(
            NovelWorkflowStep.run_id == run.id,
            NovelWorkflowStep.step_type == step_type,
            NovelWorkflowStep.sequence_no == sequence_no,
        )
        .first()
    )
    now = datetime.utcnow()
    if step is None:
        step = NovelWorkflowStep(
            run_id=run.id,
            novel_id=run.novel_id,
            step_type=step_type,
            sequence_no=sequence_no,
            attempt_count=0,
        )
    step.status = status
    step.attempt_count = int(step.attempt_count or 0) + 1 if status == "running" else int(step.attempt_count or 0)
    if payload is not None:
        step.payload_json = json.dumps(payload, ensure_ascii=False)
    if result_payload is not None:
        step.result_json = json.dumps(result_payload, ensure_ascii=False)
    if error_payload is not None:
        step.error_json = json.dumps(error_payload, ensure_ascii=False)
    if status == "running" and step.started_at is None:
        step.started_at = now
    if status in {"done", "failed", "cancelled", "skipped"}:
        step.finished_at = now
    db.add(step)
    db.flush()
    return step


def append_workflow_event(
    db: Session,
    *,
    run: NovelWorkflowRun,
    event_type: str,
    message: str,
    level: str = "info",
    step: NovelWorkflowStep | None = None,
    meta: dict[str, Any] | None = None,
) -> NovelWorkflowEvent:
    event = NovelWorkflowEvent(
        run_id=run.id,
        novel_id=run.novel_id,
        step_id=step.id if step else None,
        level=level,
        event_type=event_type,
        message=message,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
    )
    db.add(event)
    db.flush()
    return event
