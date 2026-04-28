from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.novel_memory_runtime import NovelMemoryUpdateRun
from app.services.novel_memory_diff_service import (
    build_memory_diff,
    build_memory_source_summary,
)


def _json_dumps(value: Any, fallback: str = "{}") -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def _json_loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return fallback


def create_memory_update_run(
    db: Session,
    *,
    novel_id: str,
    batch_id: str = "",
    trigger_source: str,
    source: str,
    chapter_id: str | None = None,
    chapter_no: int | None = None,
    base_memory_version: int = 0,
    request_payload: dict[str, Any] | None = None,
) -> NovelMemoryUpdateRun:
    run = NovelMemoryUpdateRun(
        novel_id=novel_id,
        batch_id=batch_id,
        trigger_source=trigger_source,
        source=source,
        chapter_id=chapter_id,
        chapter_no=chapter_no,
        status="queued",
        current_stage="queued",
        base_memory_version=base_memory_version,
        request_json=_json_dumps(request_payload or {}),
    )
    db.add(run)
    db.flush()
    return run


def touch_memory_update_run(
    db: Session,
    run: NovelMemoryUpdateRun,
    *,
    status: str | None = None,
    current_stage: str | None = None,
    target_memory_version: int | None = None,
    delta_status: str | None = None,
    validation_status: str | None = None,
    norm_status: str | None = None,
    snapshot_status: str | None = None,
    story_bible_status: str | None = None,
    rag_status: str | None = None,
    diff_summary: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    result_payload: dict[str, Any] | None = None,
    error_payload: dict[str, Any] | None = None,
) -> NovelMemoryUpdateRun:
    now = datetime.utcnow()
    if run.started_at is None and (status == "running" or current_stage not in (None, "queued")):
        run.started_at = now
    if status is not None:
        run.status = status
        if status in {"ok", "warning", "blocked", "failed", "cancelled", "skipped"}:
            run.finished_at = now
    if current_stage is not None:
        run.current_stage = current_stage
    if target_memory_version is not None:
        run.target_memory_version = int(target_memory_version or 0)
    if delta_status is not None:
        run.delta_status = delta_status
    if validation_status is not None:
        run.validation_status = validation_status
    if norm_status is not None:
        run.norm_status = norm_status
    if snapshot_status is not None:
        run.snapshot_status = snapshot_status
    if story_bible_status is not None:
        run.story_bible_status = story_bible_status
    if rag_status is not None:
        run.rag_status = rag_status
    if diff_summary is not None:
        run.diff_summary_json = _json_dumps(diff_summary, fallback="{}")
        run.source_summary_json = _json_dumps(build_memory_source_summary(diff_summary), fallback="{}")
    if warnings is not None:
        run.warnings_json = _json_dumps(warnings, fallback="[]")
    if errors is not None:
        run.errors_json = _json_dumps(errors, fallback="[]")
    if result_payload is not None:
        run.result_json = _json_dumps(result_payload, fallback="{}")
    if error_payload is not None:
        run.error_json = _json_dumps(error_payload, fallback="{}")
    db.add(run)
    db.flush()
    return run


def build_memory_update_run_from_result(
    db: Session,
    run: NovelMemoryUpdateRun,
    *,
    previous_payload_json: str,
    result: dict[str, Any],
) -> NovelMemoryUpdateRun:
    candidate_json = str(result.get("candidate_json") or result.get("payload_json") or previous_payload_json or "{}")
    diff_summary = build_memory_diff(previous_payload_json, candidate_json)
    result_status = str(result.get("status") or ("ok" if result.get("ok") else "failed"))
    errors = [str(item).strip() for item in (result.get("errors") or result.get("blocking_errors") or []) if str(item).strip()]
    warnings = [str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()]
    stage_status = result.get("stage_status") if isinstance(result.get("stage_status"), dict) else {}
    return touch_memory_update_run(
        db,
        run,
        status=result_status,
        current_stage="source_applied" if result_status in {"ok", "warning"} else result_status,
        target_memory_version=int(result.get("version") or 0),
        delta_status=str(stage_status.get("delta") or ("ok" if result.get("delta") else "failed")),
        validation_status=str(
            stage_status.get("validation")
            or ("blocked" if result_status == "blocked" else ("ok" if result.get("ok") else "failed"))
        ),
        norm_status=str(stage_status.get("norm") or ("ok" if result_status in {"ok", "warning"} else "skipped")),
        snapshot_status=str(stage_status.get("snapshot") or ("ok" if result_status in {"ok", "warning"} else "skipped")),
        diff_summary=diff_summary,
        warnings=warnings,
        errors=errors,
        result_payload={
            "status": result_status,
            "version": result.get("version"),
            "stats": result.get("stats") or {},
            "auto_pass_notes": result.get("auto_pass_notes") or [],
        },
        error_payload={
            "error": result.get("error"),
            "batch": result.get("batch"),
        }
        if result.get("error") or result.get("batch")
        else {},
    )


def set_memory_update_run_assets_status(
    db: Session,
    run: NovelMemoryUpdateRun,
    *,
    sync_meta: dict[str, Any] | None = None,
    failed: bool = False,
    error_message: str | None = None,
) -> NovelMemoryUpdateRun:
    if failed:
        return touch_memory_update_run(
            db,
            run,
            current_stage="assets_failed",
            story_bible_status="failed",
            rag_status="failed",
            status="warning" if run.status == "ok" else run.status,
            error_payload={
                **_json_loads(run.error_json, {}),
                "assets_error": error_message or "Story Bible / RAG 同步失败",
            },
        )
    sync_meta = sync_meta or {}
    story_bible_status = "ok" if sync_meta.get("story_bible_version") else "skipped"
    rag_meta = sync_meta.get("retrieval")
    rag_status = "ok" if rag_meta else "skipped"
    return touch_memory_update_run(
        db,
        run,
        current_stage="assets_done",
        story_bible_status=story_bible_status,
        rag_status=rag_status,
        result_payload={
            **_json_loads(run.result_json, {}),
            "assets": sync_meta,
        },
    )


def serialize_memory_update_run(run: NovelMemoryUpdateRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "batch_id": run.batch_id,
        "trigger_source": run.trigger_source,
        "source": run.source,
        "chapter_id": run.chapter_id,
        "chapter_no": run.chapter_no,
        "status": run.status,
        "current_stage": run.current_stage,
        "base_memory_version": run.base_memory_version,
        "target_memory_version": run.target_memory_version,
        "delta_status": run.delta_status,
        "validation_status": run.validation_status,
        "norm_status": run.norm_status,
        "snapshot_status": run.snapshot_status,
        "story_bible_status": run.story_bible_status,
        "rag_status": run.rag_status,
        "request": _json_loads(run.request_json, {}),
        "source_summary": _json_loads(run.source_summary_json, {}),
        "diff_summary": _json_loads(run.diff_summary_json, {}),
        "warnings": _json_loads(run.warnings_json, []),
        "errors": _json_loads(run.errors_json, []),
        "result": _json_loads(run.result_json, {}),
        "error": _json_loads(run.error_json, {}),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
