from __future__ import annotations

import ast
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import redis
from redis.exceptions import RedisError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.novel import Chapter, ChapterFeedback, Novel, NovelGenerationLog, NovelMemory
from app.models.task import UserTask
from app.models.novel_memory_runtime import NovelMemoryUpdateRun
from app.models.volume import NovelChapterPlan, NovelVolume
from app.services.chapter_plan_schema import normalize_beats_to_v2
from app.services.memory_normalize_sync import sync_json_snapshot_from_normalized
from app.services.novel_llm_service import (
    NovelLLMService,
    coerce_novel_outline_base_fields,
    render_volume_arcs_markdown,
)
from app.services.novel_repo import (
    arc_bounds_from_dict,
    chapter_content_metrics,
    format_approved_chapters_summary,
    format_continuity_excerpts,
    format_recent_approved_fulltext_context,
    latest_memory_json,
    next_chapter_no_from_approved,
)
from app.services.memory_readable import memory_payload_to_readable_zh
from app.services.novel_memory_diff_service import build_memory_diff
from app.services.novel_memory_update_service import (
    build_memory_update_run_from_result,
    create_memory_update_run,
    serialize_memory_update_run,
    set_memory_update_run_assets_status,
    touch_memory_update_run,
)
from app.services.novel_chapter_generate_batch import run_generate_chapters_batch_sync
from app.services.novel_generation_common import (
    append_generation_log,
    ensure_chapter_heading,
    has_pending_auto_pipeline_batch,
    has_pending_chapter_generation_batch,
    memory_refresh_confirmation_token,
)
from app.services.novel_retrieval_service import (
    is_novel_rag_enabled,
    is_novel_story_bible_enabled,
    sync_story_bible_and_retrieval,
)
from app.services.novel_workflow_service import (
    append_workflow_event,
    create_workflow_run,
    get_workflow_run_by_batch_id,
    touch_workflow_run_status,
)
from app.services.novel_volume_plan_batch import run_volume_chapter_plan_batch_sync
from app.services.user_task_service import TERMINAL_STATUSES, update_user_task_by_batch_id
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_AUTO_PIPELINE_TASK_NAMES = {
    "novel.auto_pipeline_task",
    "novel.ai_create_and_start_task",
}
_AUTO_PIPELINE_NONTERMINAL_EVENTS = {
    "auto_pipeline_queued",
    "auto_pipeline_start",
    "auto_pipeline_resumed",
    "auto_pipeline_plan_batch",
    "auto_pipeline_chapters",
    "auto_pipeline_resume_enqueued",
    "ai_create_queued",
    "ai_create_brainstorming",
    "ai_create_resume_enqueued",
}
_AUTO_PIPELINE_TERMINAL_EVENTS = {
    "auto_pipeline_done",
    "auto_pipeline_failed",
    "auto_pipeline_skipped",
    "auto_pipeline_enqueue_failed",
    "ai_create_done",
    "ai_create_failed",
}
_AUTO_PIPELINE_STALE_GRACE_SECONDS = 120
_MAX_AUTO_RESUME_COUNT = 5
_AUTO_REQUEUE_PIPELINE_FORBIDDEN: frozenset[str] = frozenset(
    set(_AUTO_PIPELINE_TERMINAL_EVENTS)
    | {
        "auto_pipeline_cancelled",
        "ai_create_brainstorm_parse_failed",
        "chapter_failed",
        "chapter_memory_delta_failed",
    }
)


def _user_task_row_for_batch(db, batch_id: str) -> UserTask | None:
    if not batch_id:
        return None
    return (
        db.query(UserTask)
        .filter(UserTask.batch_id == batch_id)
        .order_by(UserTask.created_at.desc())
        .first()
    )


def _task_set_started(db, *, batch_id: str, message: str = "后台任务已开始") -> None:
    try:
        row = _user_task_row_for_batch(db, batch_id)
        if row and str(row.status or "") in TERMINAL_STATUSES:
            return
        update_user_task_by_batch_id(
            db,
            batch_id=batch_id,
            status="started",
            last_message=message,
            started_at=datetime.utcnow(),
        )
    except Exception:
        logger.exception("update user task started failed | batch_id=%s", batch_id)


def _task_set_terminal(
    db,
    *,
    batch_id: str,
    status: str,
    message: str = "",
) -> None:
    try:
        row = _user_task_row_for_batch(db, batch_id)
        if row and str(row.status or "") == "cancelled" and status in (
            "done",
            "failed",
            "skipped",
        ):
            return
        update_user_task_by_batch_id(
            db,
            batch_id=batch_id,
            status=status,
            last_message=message,
            finished_at=datetime.utcnow(),
        )
    except Exception:
        logger.exception(
            "update user task terminal failed | batch_id=%s status=%s",
            batch_id,
            status,
        )


def _mark_novel_failed_if_missing_framework(db, novel_id: str) -> None:
    n = db.get(Novel, novel_id)
    if n and not (n.framework_markdown or "").strip():
        n.status = "failed"


def _make_generation_progress_logger(
    db,
    *,
    novel_id: str,
    batch_id: str,
    event: str,
):
    def _log(message: str) -> None:
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event=event,
            message=message,
        )
        db.commit()

    return _log


def _novel_mem_delta_zkey(novel_id: str) -> str:
    return f"vocalflow:novel:mem_delta:{novel_id}"


def _novel_mem_delta_lock_key(novel_id: str) -> str:
    return f"vocalflow:lock:novel_mem_delta:{novel_id}"


def _novel_auto_pipeline_lock_key(novel_id: str) -> str:
    return f"vocalflow:lock:novel_auto_pipeline:{novel_id}"


def _redis_for_novel_queue() -> redis.Redis | None:
    try:
        r = redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        return r
    except RedisError:
        logger.warning("novel queue redis unavailable")
        return None


def _novel_llm_for_novel(novel: Novel) -> NovelLLMService:
    """后台任务按书主计费；无 user_id 的历史数据仍不计费。"""
    uid = getattr(novel, "user_id", None)
    if not uid:
        raise RuntimeError("该小说缺少 user_id，无法进行计费的 AI 调用")
    return NovelLLMService(billing_user_id=uid)


_CHAPTER_GEN_TASK_NAME = "novel.generate_chapters_for_novel"
_VOLUME_PLAN_TASK_NAME = "novel.volume_plan_batch_for_volume"


def _batch_id_from_celery_task_args(args: object) -> str | None:
    """Celery inspect 中 args 可能是 list 或 str(repr)。"""
    if isinstance(args, (list, tuple)) and len(args) > 2:
        return str(args[2])
    if isinstance(args, str):
        try:
            parsed = ast.literal_eval(args)
            if isinstance(parsed, (list, tuple)) and len(parsed) > 2:
                return str(parsed[2])
        except (ValueError, SyntaxError):
            pass
    return None


def _inspect_item_name_and_args(
    t: object,
) -> tuple[str, object] | None:
    """active/reserved/scheduled 里单条结构略有差异，scheduled 常在 request 中。"""
    if not isinstance(t, dict):
        return None
    name: str
    if t.get("name"):
        name = str(t.get("name"))
    else:
        req = t.get("request")
        if isinstance(req, dict) and req.get("name"):
            name = str(req.get("name"))
        else:
            return None
    args: object
    if "args" in t and t.get("args") is not None:
        args = t.get("args")
    else:
        req = t.get("request")
        args = req.get("args") if isinstance(req, dict) else None
    return (name, args)


def _iter_inspect_task_dicts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        insp = celery_app.control.inspect(timeout=1.0)
        for bucket in (insp.active() or {}, insp.reserved() or {}, insp.scheduled() or {}):
            for _w, tasks in bucket.items():
                if not isinstance(tasks, list):
                    continue
                for t in tasks:
                    if isinstance(t, dict):
                        out.append(t)
    except Exception:
        return []
    return out


def celery_chapter_batch_held_in_workers(batch_id: str) -> bool | None:
    """
    是否仍有 Worker 的 active/reserved 队列持有该章节目录 batch 任务。

    返回 None 表示无法 inspect（保守策略交给调用方，通常仍用较长宽限）。
    """
    if not batch_id:
        return False
    try:
        for t in _iter_inspect_task_dicts():
            parsed = _inspect_item_name_and_args(t)
            if not parsed:
                continue
            name, args = parsed
            if name != _CHAPTER_GEN_TASK_NAME:
                continue
            bid = _batch_id_from_celery_task_args(args)
            if bid == str(batch_id):
                return True
        return False
    except Exception:
        logger.exception("celery_chapter_batch_held_in_workers failed | batch_id=%s", batch_id)
        return None


def celery_pipeline_batch_held_in_workers(batch_id: str) -> bool | None:
    """Celery 中是否仍有全自动 / 一键建书任务持有该 batch_id。"""
    if not batch_id:
        return False
    names = frozenset(
        (
            "novel.auto_pipeline_task",
            "novel.ai_create_and_start_task",
        )
    )
    try:
        for t in _iter_inspect_task_dicts():
            parsed = _inspect_item_name_and_args(t)
            if not parsed:
                continue
            name, args = parsed
            if name not in names:
                continue
            bid = _batch_id_from_celery_task_args(args)
            if bid == str(batch_id):
                return True
        return False
    except Exception:
        logger.exception(
            "celery_pipeline_batch_held_in_workers failed | batch_id=%s", batch_id
        )
        return None


def celery_volume_plan_batch_held_in_workers(batch_id: str) -> bool | None:
    """同上，针对卷章计划 batch（参数结构一致：novel_id, user_id, batch_id, body）。"""
    if not batch_id:
        return False
    try:
        for t in _iter_inspect_task_dicts():
            parsed = _inspect_item_name_and_args(t)
            if not parsed:
                continue
            name, args = parsed
            if name != _VOLUME_PLAN_TASK_NAME:
                continue
            bid = _batch_id_from_celery_task_args(args)
            if bid == str(batch_id):
                return True
        return False
    except Exception:
        logger.exception("celery_volume_plan_batch_held_in_workers failed | batch_id=%s", batch_id)
        return None


def _has_active_auto_pipeline_task(
    novel_id: str,
    *,
    exclude_task_ids: set[str] | None = None,
) -> bool:
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active = inspect.active() or {}
    except Exception:
        logger.exception("inspect active auto pipeline failed | novel_id=%s", novel_id)
        return False

    ignored = exclude_task_ids or set()
    for tasks in active.values():
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("id") or "") in ignored:
                continue
            if str(task.get("name") or "") not in _AUTO_PIPELINE_TASK_NAMES:
                continue
            args = task.get("args") or []
            current_novel_id = None
            if isinstance(args, (list, tuple)) and args:
                current_novel_id = args[0]
            elif isinstance(args, str) and args:
                current_novel_id = args.split(",")[0].strip(" []'\"")
            if str(current_novel_id or "") == novel_id:
                return True
    return False


def _batch_has_forbidden_for_auto_requeue(
    db: Session, novel_id: str, batch_id: str
) -> bool:
    return (
        db.query(NovelGenerationLog.id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id == batch_id,
            NovelGenerationLog.event.in_(list(_AUTO_REQUEUE_PIPELINE_FORBIDDEN)),
        )
        .first()
    ) is not None


def try_requeue_stale_auto_or_ai_batch(
    db: Session, novel_id: str, batch_id: str
) -> bool:
    """全自动 / 一键建书：Worker 丢失且未出现业务终态时按 user_tasks 再入队。"""
    hb = celery_pipeline_batch_held_in_workers(batch_id)
    if hb is not False:
        return False
    if _batch_has_forbidden_for_auto_requeue(db, novel_id, batch_id):
        return False
    ut = (
        db.query(UserTask)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.batch_id == batch_id,
            UserTask.kind.in_(("auto_generate", "ai_create_and_start")),
        )
        .order_by(UserTask.created_at.desc())
        .first()
    )
    if not ut or str(ut.status or "") in TERMINAL_STATUSES:
        return False
    meta_raw = dict(ut.meta)
    cur = int(meta_raw.get("auto_resume_count") or 0)
    if cur >= _MAX_AUTO_RESUME_COUNT:
        return False
    try:
        if ut.kind == "auto_generate":
            if "target_count" not in meta_raw:
                return False
            task = novel_auto_pipeline_task.delay(
                novel_id,
                str(ut.user_id),
                batch_id,
                int(meta_raw["target_count"]),
                str(meta_raw.get("trigger_source") or "manual"),
                meta_raw.get("scheduled_date"),
            )
        else:
            if "tags" not in meta_raw or "length_type" not in meta_raw:
                return False
            task = novel_ai_create_and_start_task.delay(
                novel_id,
                str(ut.user_id),
                batch_id,
                list(meta_raw.get("tags") or []),
                str(meta_raw.get("notes") or ""),
                str(meta_raw.get("length_type") or "medium"),
                int(meta_raw.get("target_generate_chapters") or 0),
                meta_raw.get("target_chapters"),
            )
        tid = getattr(task, "id", None)
    except Exception:
        logger.exception(
            "try_requeue_stale_auto_or_ai_batch.delay failed | batch_id=%s", batch_id
        )
        return False
    meta_raw["auto_resume_count"] = cur + 1
    if tid:
        meta_raw["celery_task_id"] = str(tid)
    ut.meta_json = json.dumps(meta_raw, ensure_ascii=False)
    is_ai = batch_id.startswith("aicreate-")
    ev = "ai_create_resume_enqueued" if is_ai else "auto_pipeline_resume_enqueued"
    msg = (
        "检测到一键建书任务已丢失，已自动重新入队续跑"
        if is_ai
        else "检测到全自动任务已丢失，已自动重新入队续跑"
    )
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event=ev,
        level="info",
        message=msg,
        meta={"celery_task_id": tid, "auto_resume_count": cur + 1},
    )
    db.commit()
    logger.warning(
        "auto/ai pipeline batch requeued | novel_id=%s batch_id=%s n=%s",
        novel_id,
        batch_id,
        cur + 1,
    )
    return True


def try_requeue_stale_volume_plan_batch(
    db: Session, novel_id: str, batch_id: str, *, held: bool | None
) -> bool:
    if held is not False:
        return False
    if (
        db.query(NovelGenerationLog.id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id == batch_id,
            NovelGenerationLog.event.in_(
                ("volume_plan_done", "volume_plan_failed", "volume_plan_enqueue_failed")
            ),
        )
        .first()
    ):
        return False
    ut = (
        db.query(UserTask)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.batch_id == batch_id,
            UserTask.kind == "volume_plan",
        )
        .order_by(UserTask.created_at.desc())
        .first()
    )
    if not ut or str(ut.status or "") in TERMINAL_STATUSES:
        return False
    meta_raw = dict(ut.meta)
    cur = int(meta_raw.get("auto_resume_count") or 0)
    if cur >= _MAX_AUTO_RESUME_COUNT:
        return False
    if "volume_id" not in meta_raw:
        return False
    body = {k: v for k, v in meta_raw.items() if k != "auto_resume_count"}
    try:
        task = novel_volume_plan_batch_for_volume.delay(
            novel_id,
            str(ut.user_id),
            batch_id,
            body,
        )
        tid = getattr(task, "id", None)
    except Exception:
        logger.exception(
            "try_requeue_stale_volume_plan_batch.delay failed | batch_id=%s", batch_id
        )
        return False
    meta_raw["auto_resume_count"] = cur + 1
    if tid:
        meta_raw["celery_task_id"] = str(tid)
    ut.meta_json = json.dumps(meta_raw, ensure_ascii=False)
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="volume_plan_resume_enqueued",
        level="info",
        message="检测到卷章计划任务已丢失，已自动重新入队续跑",
        meta={"celery_task_id": tid, "auto_resume_count": cur + 1},
    )
    db.commit()
    return True


def recover_stale_auto_pipeline_state(
    db,
    novel_id: str,
    *,
    exclude_batch_id: str | None = None,
    exclude_task_ids: set[str] | None = None,
) -> dict[str, Any]:
    now = datetime.utcnow()
    active = _has_active_auto_pipeline_task(
        novel_id, exclude_task_ids=exclude_task_ids
    )
    r = _redis_for_novel_queue()
    lock_key = _novel_auto_pipeline_lock_key(novel_id)
    lock_exists = bool(r.exists(lock_key)) if r is not None else False

    rows = (
        db.query(NovelGenerationLog.batch_id, NovelGenerationLog.event, NovelGenerationLog.created_at)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event.in_(
                list(_AUTO_PIPELINE_NONTERMINAL_EVENTS | _AUTO_PIPELINE_TERMINAL_EVENTS)
            ),
        )
        .order_by(NovelGenerationLog.created_at.asc())
        .all()
    )

    batches: dict[str, dict[str, Any]] = {}
    for batch_id, event, created_at in rows:
        if not batch_id or batch_id == exclude_batch_id:
            continue
        info = batches.setdefault(
            batch_id,
            {
                "events": set(),
                "last_at": created_at,
            },
        )
        info["events"].add(str(event or ""))
        if created_at and (
            info["last_at"] is None or created_at > info["last_at"]
        ):
            info["last_at"] = created_at

    # 用户可清空生成日志；仍以未终态的 user_tasks 找回在飞中的 auto/建书批次
    utq = db.query(UserTask).filter(
        UserTask.novel_id == novel_id,
        UserTask.kind.in_(("auto_generate", "ai_create_and_start")),
        ~UserTask.status.in_(list(TERMINAL_STATUSES)),
        UserTask.batch_id.isnot(None),
    )
    if exclude_batch_id:
        utq = utq.filter(UserTask.batch_id != exclude_batch_id)
    for ut in utq.all():
        bid = str(ut.batch_id or "")
        if not bid or bid == exclude_batch_id:
            continue
        la = ut.updated_at or ut.started_at or ut.created_at
        syn = (
            "ai_create_queued"
            if ut.kind == "ai_create_and_start"
            else "auto_pipeline_queued"
        )
        if bid not in batches:
            batches[bid] = {"events": {syn}, "last_at": la}
        else:
            batches[bid]["events"].add(syn)
            if la and (
                batches[bid].get("last_at") is None
                or la > batches[bid]["last_at"]
            ):
                batches[bid]["last_at"] = la

    stale_batches: list[str] = []
    grace = timedelta(seconds=_AUTO_PIPELINE_STALE_GRACE_SECONDS)
    for batch_id, info in batches.items():
        events = info["events"]
        if events & _AUTO_PIPELINE_TERMINAL_EVENTS:
            continue
        if not (events & _AUTO_PIPELINE_NONTERMINAL_EVENTS):
            continue
        last_at = info.get("last_at")
        if last_at and (now - last_at) < grace:
            continue
        hb = celery_pipeline_batch_held_in_workers(batch_id)
        if hb is True:
            continue
        stale_batches.append(batch_id)

    recovered_lock = False
    if lock_exists and not active:
        if stale_batches or not batches:
            try:
                if r is not None:
                    r.delete(lock_key)
                    recovered_lock = True
            except Exception:
                logger.exception(
                    "delete stale auto pipeline lock failed | novel_id=%s",
                    novel_id,
                )

    recovered_batches: list[str] = []
    requeued_batches: list[str] = []
    for batch_id in stale_batches:
        if try_requeue_stale_auto_or_ai_batch(db, novel_id, batch_id):
            requeued_batches.append(batch_id)
            continue
        level = "warning"
        if batch_id.startswith("aicreate-"):
            event = "ai_create_failed"
            message = "AI 建书任务疑似因进程重启或异常退出中断，系统已自动回收僵尸批次"
        else:
            event = "auto_pipeline_failed"
            message = "全自动生成任务疑似因进程重启或异常退出中断，系统已自动回收僵尸批次"
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event=event,
            level=level,
            message=message,
            meta={"reason": "stale_recovered"},
        )
        _task_set_terminal(
            db,
            batch_id=batch_id,
            status="failed",
            message=message,
        )
        recovered_batches.append(batch_id)

    if recovered_batches or requeued_batches:
        db.commit()

    return {
        "active": active,
        "lock_exists": lock_exists,
        "recovered_lock": recovered_lock,
        "recovered_batches": recovered_batches,
        "requeued_batches": requeued_batches,
    }


def _append_refresh_log(
    db,
    *,
    novel_id: str,
    batch_id: str,
    event: str,
    message: str,
    level: str = "info",
    meta: dict | None = None,
) -> None:
    db.add(
        NovelGenerationLog(
            novel_id=novel_id,
            batch_id=batch_id,
            level=level,
            event=event,
            chapter_no=None,
            message=message,
            meta_json=json.dumps(meta or {}, ensure_ascii=False),
        )
    )


def _enqueue_memory_derived_assets_sync(
    *,
    novel_id: str,
    run_id: str,
    batch_id: str,
    chapter_no: int | None = None,
) -> str | None:
    try:
        task = novel_sync_memory_derived_assets.delay(
            novel_id,
            run_id,
            batch_id,
            chapter_no,
        )
        return getattr(task, "id", None)
    except Exception:
        logger.exception(
            "enqueue novel.sync_memory_derived_assets failed | novel_id=%s run_id=%s batch_id=%s",
            novel_id,
            run_id,
            batch_id,
        )
        return None


@celery_app.task(name="novel.sync_memory_derived_assets")
def novel_sync_memory_derived_assets(
    novel_id: str,
    run_id: str,
    batch_id: str = "",
    chapter_no: int | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        run = db.get(NovelMemoryUpdateRun, run_id)
        if not run or run.novel_id != novel_id:
            return {"status": "not_found", "run_id": run_id}
        touch_memory_update_run(db, run, current_stage="assets_syncing")
        db.commit()
        sync_meta = sync_story_bible_and_retrieval(db, novel_id)
        set_memory_update_run_assets_status(db, run, sync_meta=sync_meta)
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id or run.batch_id or f"mem-assets-{run.id[:8]}",
            event="memory_assets_synced",
            chapter_no=chapter_no or run.chapter_no,
            message="记忆真源更新后已异步同步 Story Bible / RAG",
            meta={"run_id": run.id, **sync_meta},
        )
        db.commit()
        return {"status": "ok", "run_id": run_id, "sync_meta": sync_meta}
    except Exception as e:
        db.rollback()
        try:
            run = db.get(NovelMemoryUpdateRun, run_id)
            if run:
                set_memory_update_run_assets_status(
                    db,
                    run,
                    failed=True,
                    error_message=str(e),
                )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id or run.batch_id or f"mem-assets-{run.id[:8]}",
                    event="memory_assets_sync_failed",
                    chapter_no=chapter_no or run.chapter_no,
                    level="warning",
                    message="记忆真源已更新，但 Story Bible / RAG 异步同步失败",
                    meta={"run_id": run.id, "error": str(e)},
                )
                db.commit()
        except Exception:
            db.rollback()
        logger.exception(
            "novel.sync_memory_derived_assets failed | novel_id=%s run_id=%s",
            novel_id,
            run_id,
        )
        raise
    finally:
        db.close()


@celery_app.task(name="novel.daily_chapters")
def novel_daily_chapters() -> dict[str, int]:
    """
    每分钟定时：检查当前时间 (HH:MM)，查找设定在这个时间自动生成的小说，并触发全自动 Pipeline。
    仅在没有同书进行中的自动 Pipeline 时入队；last_auto_date 由真正执行任务的 worker 写入。
    """
    db = SessionLocal()
    processed = 0
    
    # 获取北京时间 HH:MM 和日期 YYYY-MM-DD
    from datetime import datetime
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    now_hh_mm = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    
    try:
        # 查询需要自动生成的小说
        novels = (
            db.query(Novel)
            .filter(
                Novel.daily_auto_chapters > 0, 
                Novel.framework_confirmed.is_(True)
            )
            .all()
        )
        for n in novels:
            # 判断是否到了或过了设定的时间，且今天还没执行过
            if n.daily_auto_time <= now_hh_mm and (n.last_auto_date or "") < today_str:
                if has_pending_auto_pipeline_batch(db, n.id) or has_pending_chapter_generation_batch(
                    db, n.id
                ):
                    logger.info(
                        "daily_chapters skipped enqueue due to pending batch | novel_id=%s",
                        n.id,
                    )
                    continue
                batch_id = f"auto-{int(time.time())}-{n.id[:8]}"
                try:
                    novel_auto_pipeline_task.delay(
                        n.id,
                        getattr(n, "user_id", None),
                        batch_id,
                        n.daily_auto_chapters,
                        "schedule",
                        today_str,
                    )
                    processed += 1
                    logger.info(
                        "daily_chapters queued pipeline | novel_id=%s time=%s today=%s",
                        n.id,
                        now_hh_mm,
                        today_str,
                    )
                except Exception:
                    logger.exception("daily_chapters trigger failed | novel_id=%s", n.id)
    finally:
        db.close()


@celery_app.task(name="novel.chapter_polish")
def novel_chapter_polish(
    chapter_id: str,
    user_id: str | None,
    batch_id: str,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        c = db.get(Chapter, chapter_id)
        if not c:
            raise ValueError("章节不存在")
        n = db.get(Novel, c.novel_id)
        if not n:
            raise ValueError("小说不存在")

        # 获取对应的执行卡
        plan = db.query(NovelChapterPlan).filter(
            NovelChapterPlan.novel_id == c.novel_id,
            NovelChapterPlan.chapter_no == c.chapter_no
        ).order_by(NovelChapterPlan.updated_at.desc()).first()
        if not plan:
            raise ValueError(f"未找到第 {c.chapter_no} 章的执行卡，无法润色")
        try:
            beats = json.loads(plan.beats_json or "{}")
        except Exception:
            beats = {}
        beats = normalize_beats_to_v2(beats)

        llm = NovelLLMService(billing_user_id=user_id)

        append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=batch_id,
            event="chapter_polish_started",
            message="后台去AI味润色已开始",
            chapter_no=c.chapter_no,
            meta={"chapter_id": chapter_id},
        )
        db.commit()

        # 优先使用正文，如果没有正文则使用待审阅正文
        chapter_text = (c.content or c.pending_content or "").strip()
        if not chapter_text:
            raise ValueError("章节内容为空，无法润色")

        polished_text = llm.polish_chapter_style_sync(
            n,
            chapter_no=c.chapter_no,
            plan_title=plan.chapter_title or "",
            beats=beats,
            chapter_text=chapter_text,
            db=db,
        )
        _, normalized_pending = ensure_chapter_heading(
            c.chapter_no,
            polished_text,
            title_hint=plan.chapter_title or c.title or "",
        )

        c.pending_content = normalized_pending
        c.pending_revision_prompt = "去AI味润色（手动触发）"
        c.status = "pending_review"

        append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=batch_id,
            event="chapter_polish_done",
            message="去AI味润色已完成，待审阅",
            chapter_no=c.chapter_no,
            meta={"chapter_id": chapter_id},
        )
        db.commit()
        return {"status": "ok", "chapter_id": chapter_id}
    except Exception as e:
        logger.exception("novel.chapter_polish failed | chapter_id=%s", chapter_id)
        try:
            db.rollback()
            c2 = db.get(Chapter, chapter_id)
            if c2:
                # 更新小说状态为 failed (可选，这里不一定需要，因为只是单章润色)
                append_generation_log(
                    db,
                    novel_id=c2.novel_id,
                    batch_id=batch_id,
                    event="chapter_polish_failed",
                    level="error",
                    message=f"去AI味润色失败：{e}",
                    chapter_no=c2.chapter_no,
                    meta={"chapter_id": chapter_id, "error": str(e)},
                )
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="novel.auto_refresh_memories")
def novel_auto_refresh_memories() -> dict[str, int | bool]:
    """
    定时：对已有审定章节的书合并记忆（与 POST /memory/refresh 逻辑一致）。
    默认关闭，需设置 NOVEL_AUTO_REFRESH_MEMORY=true。
    """
    if not settings.novel_auto_refresh_memory:
        return {"skipped": True, "refreshed": 0}
    db = SessionLocal()
    refreshed = 0
    try:
        novels = db.query(Novel).filter(Novel.framework_confirmed.is_(True)).all()
        for n in novels:
            llm = _novel_llm_for_novel(n)
            try:
                chapters = (
                    db.query(Chapter)
                    .filter(Chapter.novel_id == n.id, Chapter.status == "approved")
                    .order_by(Chapter.chapter_no.asc())
                    .all()
                )
                if not chapters:
                    continue
                summary = format_approved_chapters_summary(
                    chapters,
                    settings.novel_chapter_summary_tail_chars,
                    head_chars=settings.novel_chapter_summary_head_chars,
                    mode=settings.novel_chapter_summary_mode,
                    max_chapters=settings.novel_memory_refresh_chapters,
                )
                prev = latest_memory_json(db, n.id)
                result = llm.refresh_memory_from_chapters_sync(
                    n, summary, prev, db=db
                )
                if not result.get("ok"):
                    logger.warning(
                        "auto_refresh_memories skipped invalid candidate | novel_id=%s errors=%s",
                        n.id,
                        result.get("errors") or [],
                    )
                    continue
                # refresh_memory_from_chapters_sync 已在 NovelLLMService 内写入分表并派生快照
                refreshed += 1
            except RuntimeError as e:
                db.rollback()
                if "积分" in str(e) or "不足" in str(e):
                    logger.warning(
                        "auto_refresh_memories skipped novel (billing) | novel_id=%s err=%s",
                        n.id,
                        e,
                    )
                else:
                    logger.exception(
                        "auto_refresh_memories novel runtime error | novel_id=%s", n.id
                    )
                continue
            except Exception:
                db.rollback()
                continue
    finally:
        db.close()
    return {"skipped": False, "refreshed": refreshed}


@celery_app.task(name="novel.refresh_memory_for_novel")
def novel_refresh_memory_for_novel(
    novel_id: str,
    reason: str = "后台：基于已审定章节自动合并",
    batch_id: str = "",
    from_chapter_no: int | None = None,
    to_chapter_no: int | None = None,
    is_full: bool = False,
) -> dict[str, int | str]:
    """
    单本小说后台刷新记忆：用于「审定通过/已审定章节改动」后异步刷新，避免阻塞接口。
    """
    db = SessionLocal()
    bid = batch_id or f"mem-refresh-{novel_id[:8]}-{int(time.time())}"
    try:
        _task_set_started(db, batch_id=bid, message="开始执行刷新记忆流程")
        logger.info(
            "refresh_memory_for_novel consumed | novel_id=%s batch_id=%s reason=%s",
            novel_id,
            bid,
            reason,
        )
        _append_refresh_log(
            db,
            novel_id=novel_id,
            batch_id=bid,
            event="memory_refresh_consumed",
            message="worker 已消费任务，开始执行刷新流程",
            meta={"reason": reason},
        )
        _append_refresh_log(
            db,
            novel_id=novel_id,
            batch_id=bid,
            event="memory_refresh_started",
            message="后台记忆刷新已开始",
            meta={"reason": reason},
        )
        db.commit()
        n = db.get(Novel, novel_id)
        if not n:
            _task_set_terminal(db, batch_id=bid, status="failed", message="小说不存在")
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_not_found",
                level="error",
                message="后台记忆刷新失败：小说不存在",
            )
            db.commit()
            return {"status": "not_found", "novel_id": novel_id}
        
        q = db.query(Chapter).filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        if is_full:
            max_chapters = 99999
        elif from_chapter_no is not None and to_chapter_no is not None:
            q = q.filter(Chapter.chapter_no >= from_chapter_no, Chapter.chapter_no <= to_chapter_no)
            max_chapters = 99999
        else:
            max_chapters = settings.novel_memory_refresh_chapters or 15
            # 优化：只查最近的 max_chapters 个已审定章节
            # 先拿到总数，然后跳过前面的，只取最后 N 个
            # 或者直接取 order_by(desc).limit(N) 然后再倒序回来
            pass
            
        if not is_full and (from_chapter_no is None or to_chapter_no is None):
            chapters = q.order_by(Chapter.chapter_no.desc()).limit(max_chapters).all()
            chapters.reverse() # 恢复正序
        else:
            chapters = q.order_by(Chapter.chapter_no.asc()).all()
        
        logger.info(
            "refresh_memory_for_novel loading approved chapters | novel_id=%s count=%s batch_id=%s",
            novel_id,
            len(chapters),
            bid,
        )
        if not chapters:
            _task_set_terminal(db, batch_id=bid, status="done", message="无需更新：暂无已审定章节")
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_no_approved",
                message="后台记忆刷新跳过：暂无已审定章节",
            )
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_done",
                message="后台记忆刷新完成（无需更新：暂无已审定章节）",
                meta={"version": None},
            )
            db.commit()
            return {"status": "no_approved", "novel_id": novel_id}

        summary = format_approved_chapters_summary(
            chapters,
            settings.novel_chapter_summary_tail_chars,
            head_chars=settings.novel_chapter_summary_head_chars,
            mode=settings.novel_chapter_summary_mode,
            max_chapters=max_chapters,
        )
        prev = latest_memory_json(db, novel_id)
        current_version = (
            db.query(func.max(NovelMemory.version))
            .filter(NovelMemory.novel_id == novel_id)
            .scalar()
            or 0
        )
        memory_run = create_memory_update_run(
            db,
            novel_id=novel_id,
            batch_id=bid,
            trigger_source="memory_refresh_task",
            source="refresh_memory",
            base_memory_version=int(current_version),
            request_payload={
                "reason": reason,
                "from_chapter_no": from_chapter_no,
                "to_chapter_no": to_chapter_no,
                "is_full": is_full,
                "chapter_nos": [int(ch.chapter_no or 0) for ch in chapters],
            },
        )
        touch_memory_update_run(
            db,
            memory_run,
            status="running",
            current_stage="delta_extracting",
            delta_status="running",
            validation_status="pending",
            norm_status="pending",
            snapshot_status="pending",
        )
        db.commit()
        llm = _novel_llm_for_novel(n)
        
        def _progress_callback(batch_num: int, ch_info: str, stats: dict = None):
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_progress",
                message=f"记忆刷新进度：已完成第 {batch_num} 批次 ({ch_info})",
                meta={"batch_num": batch_num, "ch_info": ch_info, "stats": stats or {}},
            )
            db.commit()

        result = llm.refresh_memory_from_chapters_sync(
            n, summary, prev, db=db, replace_timeline=True, progress_callback=_progress_callback
        )
        build_memory_update_run_from_result(
            db,
            memory_run,
            previous_payload_json=prev,
            result=result,
        )
        if not result.get("ok"):
            _task_set_terminal(db, batch_id=bid, status="failed", message=f"失败：{result.get('error', '未知错误')}")
            cand = str(result.get("candidate_json") or "{}")
            diff_summary = build_memory_diff(prev, cand)
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_failed",
                level="error",
                message=f"后台记忆刷新失败：{result.get('error', '未知错误')}",
                meta={
                    "error": result.get("error"),
                    "batch": result.get("batch"),
                    "current_version": current_version,
                    "candidate_json": cand,
                    "candidate_readable_zh": memory_payload_to_readable_zh(cand),
                    "diff_summary": diff_summary,
                    "run_id": memory_run.id,
                },
            )
            db.commit()
            return {"status": "failed", "novel_id": novel_id}
        
        if result.get("blocking_errors"):
            _task_set_terminal(db, batch_id=bid, status="failed", message="校验失败：未覆盖当前记忆")
            cand = str(result.get("candidate_json") or "{}")
            diff_summary = build_memory_diff(prev, cand)
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_validation_failed",
                level="error",
                message="后台记忆刷新被校验拦截，未覆盖当前记忆",
                meta={
                    "errors": result.get("blocking_errors") or [],
                    "warnings": result.get("warnings") or [],
                    "auto_pass_notes": result.get("auto_pass_notes") or [],
                    "batch": result.get("batch"),
                    "current_version": current_version,
                    "candidate_json": cand,
                    "candidate_readable_zh": memory_payload_to_readable_zh(cand),
                    "diff_summary": diff_summary,
                    "run_id": memory_run.id,
                },
            )
            db.commit()
            return {"status": "blocked", "novel_id": novel_id}
        done_ver = (
            db.query(func.max(NovelMemory.version))
            .filter(NovelMemory.novel_id == novel_id)
            .scalar()
            or 0
        )
        assets_task_id: str | None = None
        if is_novel_story_bible_enabled(db, novel_id) or is_novel_rag_enabled(db, novel_id):
            assets_task_id = _enqueue_memory_derived_assets_sync(
                novel_id=novel_id,
                run_id=memory_run.id,
                batch_id=bid,
            )
            if assets_task_id:
                _append_refresh_log(
                    db,
                    novel_id=novel_id,
                    batch_id=bid,
                    event="memory_refresh_assets_queued",
                    message="记忆真源已更新，Story Bible / RAG 已转入异步同步",
                    meta={"run_id": memory_run.id, "task_id": assets_task_id},
                )
            else:
                set_memory_update_run_assets_status(
                    db,
                    memory_run,
                    failed=True,
                    error_message="异步同步任务入队失败",
                )
                _append_refresh_log(
                    db,
                    novel_id=novel_id,
                    batch_id=bid,
                    event="memory_refresh_assets_enqueue_failed",
                    level="warning",
                    message="记忆真源已更新，但 Story Bible / RAG 异步任务入队失败",
                    meta={"run_id": memory_run.id},
                )
        _task_set_terminal(db, batch_id=bid, status="done", message=f"记忆已更新 v{done_ver}")
        _append_refresh_log(
            db,
            novel_id=novel_id,
            batch_id=bid,
            event="memory_refresh_done",
            message=f"后台记忆刷新完成，版本 v{done_ver}",
            meta={
                "version": done_ver,
                "run_id": memory_run.id,
                "warnings": result.get("warnings") or [],
                "auto_pass_notes": result.get("auto_pass_notes") or [],
                "diff_summary": build_memory_diff(prev, str(result.get("candidate_json") or prev)),
                "assets_task_id": assets_task_id,
            },
        )
        if result.get("status") == "warning":
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_warning",
                level="warning",
                message="后台记忆刷新已落库，但存在需要关注的 warning",
                meta={
                    "run_id": memory_run.id,
                    "version": done_ver,
                    "warnings": result.get("warnings") or [],
                    "auto_pass_notes": result.get("auto_pass_notes") or [],
                    "candidate_json": str(result.get("candidate_json") or prev),
                    "candidate_readable_zh": memory_payload_to_readable_zh(
                        str(result.get("candidate_json") or prev)
                    ),
                    "diff_summary": build_memory_diff(prev, str(result.get("candidate_json") or prev)),
                    "confirmation_token": None,
                },
            )
        db.commit()
        logger.info(
            "refresh_memory_for_novel done | novel_id=%s version=%s batch_id=%s",
            novel_id,
            done_ver,
            bid,
        )
        return {"status": "ok", "novel_id": novel_id, "version": done_ver}
    except Exception as e:
        db.rollback()
        try:
            _task_set_terminal(db, batch_id=bid, status="failed", message=f"异常：{e}")
            memory_run = (
                db.query(NovelMemoryUpdateRun)
                .filter(
                    NovelMemoryUpdateRun.novel_id == novel_id,
                    NovelMemoryUpdateRun.batch_id == bid,
                )
                .order_by(NovelMemoryUpdateRun.created_at.desc())
                .first()
            )
            if memory_run:
                touch_memory_update_run(
                    db,
                    memory_run,
                    status="failed",
                    current_stage="failed",
                    delta_status=memory_run.delta_status,
                    validation_status=memory_run.validation_status,
                    norm_status=memory_run.norm_status,
                    snapshot_status=memory_run.snapshot_status,
                    errors=[str(e)],
                    error_payload={"error": str(e)},
                )
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_failed",
                level="error",
                message="后台记忆刷新失败，请查看后端日志",
            )
            db.commit()
        except Exception:
            db.rollback()
        logger.exception("refresh_memory_for_novel failed | novel_id=%s", novel_id)
        raise
    finally:
        db.close()


def _execute_chapter_approve_memory_delta(
    novel_id: str,
    chapter_id: str,
    approve_batch_id: str,
) -> dict[str, Any]:
    """单章审定增量记忆（供队列消费者按章号顺序调用）。"""
    db = SessionLocal()
    try:
        c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if not c or c.novel_id != novel_id:
            logger.warning(
                "chapter_approve_memory_delta: chapter mismatch | novel_id=%s chapter_id=%s",
                novel_id,
                chapter_id,
            )
            return {"status": "not_found", "novel_id": novel_id, "chapter_id": chapter_id}
        if c.status != "approved":
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_skipped",
                chapter_no=c.chapter_no,
                message="后台增量记忆跳过：章节未处于已审定状态",
                meta={"source": "chapter_approve_memory_delta", "status": c.status},
            )
            db.commit()
            return {"status": "skipped", "reason": "not_approved"}
        n = db.get(Novel, novel_id)
        if not n:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_failed",
                chapter_no=c.chapter_no,
                level="error",
                message="后台增量记忆失败：小说不存在",
                meta={"source": "chapter_approve_memory_delta"},
            )
            db.commit()
            return {"status": "novel_not_found"}

        prev_memory = latest_memory_json(db, novel_id)
        current_version = (
            db.query(func.max(NovelMemory.version))
            .filter(NovelMemory.novel_id == novel_id)
            .scalar()
            or 0
        )
        memory_run = create_memory_update_run(
            db,
            novel_id=novel_id,
            batch_id=approve_batch_id,
            trigger_source="chapter_approve_queue",
            source="chapter_incremental",
            chapter_id=chapter_id,
            chapter_no=int(c.chapter_no or 0),
            base_memory_version=int(current_version),
            request_payload={
                "chapter_title": c.title or "",
                "chapter_no": int(c.chapter_no or 0),
            },
        )
        touch_memory_update_run(
            db,
            memory_run,
            status="running",
            current_stage="delta_extracting",
            delta_status="running",
            validation_status="pending",
            norm_status="pending",
            snapshot_status="pending",
        )
        db.commit()
        llm = _novel_llm_for_novel(n)
        incremental_memory_status = "none"
        incremental_memory_version: int | None = None
        try:
            delta_result = llm.propose_memory_update_from_chapter_sync(
                n,
                chapter_no=c.chapter_no,
                chapter_title=c.title or "",
                chapter_text=c.content or "",
                prev_memory=prev_memory,
                db=db,
            )
            build_memory_update_run_from_result(
                db,
                memory_run,
                previous_payload_json=prev_memory,
                result=delta_result,
            )
            if delta_result.get("ok"):
                incremental_memory_status = "applied"
                incremental_memory_version = delta_result.get("version")
                if not incremental_memory_version:
                    incremental_memory_version = (
                        db.query(func.max(NovelMemory.version))
                        .filter(NovelMemory.novel_id == novel_id)
                        .scalar()
                    )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=approve_batch_id,
                    event="chapter_memory_delta_applied",
                    chapter_no=c.chapter_no,
                    message=f"第 {c.chapter_no} 章审定后已增量写入规范化存储 v{incremental_memory_version}",
                    meta={
                        **(delta_result.get("stats") or {}),
                        "memory_version": incremental_memory_version,
                        "source": "chapter_approve_memory_delta",
                        "run_id": memory_run.id,
                    },
                )
            else:
                incremental_memory_status = "failed"
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=approve_batch_id,
                    event="chapter_memory_delta_failed",
                    chapter_no=c.chapter_no,
                    level="error",
                    message=f"第 {c.chapter_no} 章审定后增量写入记忆失败，已保留旧记忆",
                    meta={
                        "errors": delta_result.get("errors") or [],
                        "source": "chapter_approve_memory_delta",
                        "run_id": memory_run.id,
                        "diff_summary": build_memory_diff(
                            prev_memory,
                            str(delta_result.get("candidate_json") or "{}"),
                        ),
                    },
                )
        except Exception:
            incremental_memory_status = "failed"
            logger.exception(
                "chapter_approve_memory_delta failed | chapter_id=%s novel_id=%s chapter_no=%s",
                chapter_id,
                novel_id,
                c.chapter_no,
            )
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_failed",
                chapter_no=c.chapter_no,
                level="error",
                message=f"第 {c.chapter_no} 章审定后增量写入记忆异常，已保留旧记忆",
                meta={"source": "chapter_approve_memory_delta", "run_id": memory_run.id},
            )
            touch_memory_update_run(
                db,
                memory_run,
                status="failed",
                current_stage="failed",
                errors=["章节审定后的增量记忆执行异常"],
            )
        db.commit()
        if (
            incremental_memory_status == "applied"
            and (
                is_novel_story_bible_enabled(db, novel_id)
                or is_novel_rag_enabled(db, novel_id)
            )
        ):
            task_id = _enqueue_memory_derived_assets_sync(
                novel_id=novel_id,
                run_id=memory_run.id,
                batch_id=approve_batch_id,
                chapter_no=int(c.chapter_no or 0),
            )
            try:
                if task_id:
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=approve_batch_id,
                        event="chapter_story_assets_queued",
                        chapter_no=c.chapter_no,
                        message=f"第 {c.chapter_no} 章审定后已转入异步同步 Story Bible / RAG",
                        meta={
                            "task_id": task_id,
                            "source": "chapter_approve_memory_delta",
                            "run_id": memory_run.id,
                        },
                    )
                else:
                    set_memory_update_run_assets_status(
                        db,
                        memory_run,
                        failed=True,
                        error_message="异步同步任务入队失败",
                    )
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=approve_batch_id,
                        event="chapter_story_assets_enqueue_failed",
                        chapter_no=c.chapter_no,
                        level="warning",
                        message=f"第 {c.chapter_no} 章审定后 Story Bible / RAG 异步任务入队失败",
                        meta={"source": "chapter_approve_memory_delta", "run_id": memory_run.id},
                    )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "enqueue story assets after approve delta failed | novel_id=%s chapter_id=%s",
                    novel_id,
                    chapter_id,
                )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=approve_batch_id,
                    event="chapter_story_assets_enqueue_failed",
                    chapter_no=c.chapter_no,
                    level="warning",
                    message=f"第 {c.chapter_no} 章审定后 Story Bible / RAG 异步任务入队失败",
                    meta={"source": "chapter_approve_memory_delta", "run_id": memory_run.id},
                )
                db.commit()

        consolidate_task_id: str | None = None
        n_every = max(0, int(settings.novel_memory_consolidate_every_n_chapters or 0))
        if (
            incremental_memory_status == "applied"
            and n_every > 0
            and c.chapter_no > 0
            and c.chapter_no % n_every == 0
        ):
            try:
                t = novel_consolidate_memory.delay(novel_id)
                consolidate_task_id = getattr(t, "id", None)
            except Exception:
                logger.exception(
                    "enqueue novel.consolidate_memory after approve delta failed | novel_id=%s chapter_no=%s",
                    novel_id,
                    c.chapter_no,
                )

        return {
            "status": "ok",
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "incremental_memory_status": incremental_memory_status,
            "incremental_memory_version": incremental_memory_version,
            "consolidate_memory_task_id": consolidate_task_id,
        }
    finally:
        db.close()


@celery_app.task(name="novel.chapter_approve_memory_delta_serial")
def novel_chapter_approve_memory_delta_serial(novel_id: str) -> dict[str, Any]:
    """
    同一小说下按 chapter_no 升序串行消费审定增量记忆队列（ZPOPMIN + 分布式锁），
    避免多 worker 并发导致记忆顺序错乱。
    """
    r = _redis_for_novel_queue()
    if r is None:
        logger.error(
            "chapter_approve_memory_delta_serial: redis unavailable | novel_id=%s",
            novel_id,
        )
        return {"status": "error", "reason": "no_redis"}

    zkey = _novel_mem_delta_zkey(novel_id)
    lock = r.lock(
        _novel_mem_delta_lock_key(novel_id),
        timeout=900,
        blocking=True,
        blocking_timeout=600,
    )
    acquired = lock.acquire(blocking=True, blocking_timeout=600)
    if not acquired:
        novel_chapter_approve_memory_delta_serial.apply_async(
            args=(novel_id,),
            countdown=3,
        )
        return {"status": "requeued", "novel_id": novel_id}

    processed = 0
    try:
        while True:
            popped = r.zpopmin(zkey, 1)
            if not popped:
                break
            member, score = popped[0]
            try:
                payload = json.loads(member)
            except json.JSONDecodeError:
                logger.exception(
                    "mem_delta queue bad member | novel_id=%s member=%s",
                    novel_id,
                    member[:200],
                )
                continue
            chapter_id = payload.get("chapter_id")
            approve_batch_id = payload.get("approve_batch_id")
            if not chapter_id or not approve_batch_id:
                continue
            logger.info(
                "mem_delta serial apply | novel_id=%s chapter_no=%s chapter_id=%s",
                novel_id,
                score,
                chapter_id,
            )
            _execute_chapter_approve_memory_delta(
                novel_id, str(chapter_id), str(approve_batch_id)
            )
            processed += 1
    finally:
        try:
            lock.release()
        except Exception:
            logger.exception(
                "mem_delta lock release failed | novel_id=%s", novel_id
            )

    return {"status": "ok", "novel_id": novel_id, "processed": processed}


@celery_app.task(name="novel.chapter_approve_memory_delta")
def novel_chapter_approve_memory_delta(
    novel_id: str,
    chapter_id: str,
    approve_batch_id: str,
    chapter_no: int | None = None,
) -> dict[str, Any]:
    """
    审定通过后入队单章增量记忆：同一小说内按章号顺序串行执行（Redis ZSET + 消费者任务）。
    无 Redis 时退化为直接执行（单机调试）。
    """
    resolved_no = chapter_no
    if resolved_no is None or resolved_no <= 0:
        db = SessionLocal()
        try:
            ch = db.query(Chapter).filter(Chapter.id == chapter_id).first()
            resolved_no = int(ch.chapter_no) if ch and ch.chapter_no is not None else 0
        finally:
            db.close()

    r = _redis_for_novel_queue()
    if r is None:
        return _execute_chapter_approve_memory_delta(
            novel_id, chapter_id, approve_batch_id
        )

    member = json.dumps(
        {"chapter_id": chapter_id, "approve_batch_id": approve_batch_id},
        sort_keys=True,
    )
    r.zadd(_novel_mem_delta_zkey(novel_id), {member: float(resolved_no)})
    logger.info(
        "mem_delta enqueued | novel_id=%s chapter_no=%s chapter_id=%s zcard=%s",
        novel_id,
        resolved_no,
        chapter_id,
        r.zcard(_novel_mem_delta_zkey(novel_id)),
    )
    novel_chapter_approve_memory_delta_serial.delay(novel_id)
    return {
        "status": "queued",
        "novel_id": novel_id,
        "ordering": "chapter_no_asc",
    }


@celery_app.task(name="novel.generate_chapters_for_novel")
def novel_generate_chapters_for_novel(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    后台批量生成章节：与 HTTP 同步版逻辑一致，便于用户离站后继续执行。
    """
    db = SessionLocal()
    try:
        _task_set_started(db, batch_id=batch_id, message="章节生成任务已开始")
        raw_nos = body.get("chapter_nos")
        if not isinstance(raw_nos, list) or not raw_nos:
            raise ValueError("缺少 chapter_nos")
        chapter_nos = [int(x) for x in raw_nos]
        result = run_generate_chapters_batch_sync(
            db,
            novel_id=novel_id,
            billing_user_id=user_id,
            title_hint=str(body.get("title_hint") or ""),
            chapter_nos=chapter_nos,
            use_cold_recall=bool(body.get("use_cold_recall")),
            cold_recall_items=max(1, min(int(body.get("cold_recall_items") or 5), 12)),
            auto_consistency_check=bool(body.get("auto_consistency_check")),
            auto_plan_guard_check=bool(body.get("auto_plan_guard_check")),
            auto_plan_guard_fix=bool(body.get("auto_plan_guard_fix")),
            auto_style_polish=bool(body.get("auto_style_polish")),
            auto_expressive_enhance=body.get("auto_expressive_enhance"),
            batch_id=batch_id,
            source=str(body.get("source") or "batch_auto"),
        )
        result_status = str(result.get("status") or "")
        if result_status == "cancelled":
            _task_set_terminal(db, batch_id=batch_id, status="cancelled", message="已取消")
        elif result_status == "blocked":
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="failed",
                message=f"已停止：第{int(result.get('blocked_chapter_no') or 0)}章未通过自动审定门禁",
            )
        else:
            _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        return result
    except Exception as e:
        logger.exception(
            "novel.generate_chapters_for_novel failed | novel_id=%s batch_id=%s",
            novel_id,
            batch_id,
        )
        try:
            db.rollback()
            # 更新小说状态为 failed
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="batch_failed",
                level="error",
                message=f"批量生成失败：{e}",
                meta={"error": str(e)},
            )
            db.commit()
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="failed",
                message=f"失败：{e}",
            )
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


def try_requeue_stale_chapter_generation_batch(
    db: Session,
    novel_id: str,
    batch_id: str,
    *,
    held: bool | None,
) -> bool:
    """
    检测到 Worker 已不在 running/reserved/scheduled 中持有本 batch、且库中未见业务失败终态时，
    按 user_tasks.meta 重新入队同一 Celery 任务，实现宕机/重启后的自动续跑。
    """
    from app.services.novel_chapter_generate_batch import (
        _STALE_REQUEUE_FORBIDDEN,
        _batch_has_terminal_stops,
    )

    if held is not False:
        return False
    if _batch_has_terminal_stops(db, novel_id, batch_id, _STALE_REQUEUE_FORBIDDEN):
        return False
    ut = (
        db.query(UserTask)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.batch_id == batch_id,
            UserTask.kind == "generate_chapters",
        )
        .order_by(UserTask.created_at.desc())
        .first()
    )
    if not ut or str(ut.status or "") in TERMINAL_STATUSES:
        return False
    meta_raw = dict(ut.meta)
    cur = int(meta_raw.get("auto_resume_count") or 0)
    if cur >= _MAX_AUTO_RESUME_COUNT:
        logger.warning(
            "chapter auto-resume cap reached | novel_id=%s batch_id=%s",
            novel_id,
            batch_id,
        )
        return False
    body = {k: v for k, v in meta_raw.items() if k != "auto_resume_count"}
    raw_nos = body.get("chapter_nos")
    if not isinstance(raw_nos, list) or not raw_nos:
        return False
    body["chapter_nos"] = [int(x) for x in raw_nos]
    try:
        task = novel_generate_chapters_for_novel.delay(
            novel_id,
            str(ut.user_id),
            batch_id,
            body,
        )
        tid = getattr(task, "id", None)
    except Exception:
        logger.exception(
            "try_requeue_stale_chapter_generation_batch.delay failed | batch_id=%s",
            batch_id,
        )
        return False
    meta_raw["auto_resume_count"] = cur + 1
    if tid:
        meta_raw["celery_task_id"] = str(tid)
    ut.meta_json = json.dumps(meta_raw, ensure_ascii=False)
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="chapter_generation_resume_enqueued",
        level="info",
        message="检测到后台任务已丢失，已自动重新入队续跑",
        meta={"celery_task_id": tid, "auto_resume_count": cur + 1},
    )
    db.commit()
    logger.warning(
        "chapter batch requeued after stale | novel_id=%s batch_id=%s resume_n=%s",
        novel_id,
        batch_id,
        cur + 1,
    )
    return True


@celery_app.task(name="novel.volume_plan_batch_for_volume")
def novel_volume_plan_batch_for_volume(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        _task_set_started(db, batch_id=batch_id, message="卷章计划任务已开始")
        result = run_volume_chapter_plan_batch_sync(
            db,
            novel_id=novel_id,
            billing_user_id=user_id,
            volume_id=str(body["volume_id"]),
            batch_id=batch_id,
            force_regen=bool(body.get("force_regen")),
            batch_size=body.get("batch_size"),
            from_chapter=body.get("from_chapter"),
        )
        if str(result.get("status") or "") == "cancelled":
            _task_set_terminal(db, batch_id=batch_id, status="cancelled", message="已取消")
        else:
            _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        return result
    except Exception as e:
        logger.exception(
            "novel.volume_plan_batch_for_volume failed | novel_id=%s batch_id=%s",
            novel_id,
            batch_id,
        )
        try:
            db.rollback()
            # 更新小说状态为 failed
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="volume_plan_failed",
                level="error",
                message=f"卷章计划生成失败：{e}",
                meta={"error": str(e), "volume_id": body.get("volume_id")},
            )
            db.commit()
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="failed",
                message=f"失败：{e}",
            )
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="novel.chapter_consistency_fix")
def novel_chapter_consistency_fix(
    chapter_id: str,
    user_id: str | None,
    batch_id: str,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        c = db.get(Chapter, chapter_id)
        if not c:
            raise ValueError("章节不存在")
        n = db.get(Novel, c.novel_id)
        if not n:
            raise ValueError("小说不存在")
        llm = NovelLLMService(billing_user_id=user_id)
        mem = latest_memory_json(db, c.novel_id)
        continuity = format_continuity_excerpts(db, c.novel_id, approved_only=True)
        append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=batch_id,
            event="chapter_consistency_started",
            message="后台一致性修订已开始",
            chapter_no=c.chapter_no,
            meta={"chapter_id": chapter_id},
        )
        db.commit()
        fixed_text = llm.check_and_fix_chapter_sync(
            n,
            c.chapter_no,
            c.title or "",
            mem,
            continuity,
            c.content,
            db=db,
        )
        c.pending_content = fixed_text
        c.pending_revision_prompt = "一致性修订（手动触发）"
        c.status = "pending_review"
        append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=batch_id,
            event="chapter_consistency_done",
            message="一致性修订已完成，待审阅",
            chapter_no=c.chapter_no,
            meta={"chapter_id": chapter_id},
        )
        db.commit()
        return {"status": "ok", "chapter_id": chapter_id}
    except Exception as e:
        logger.exception("novel.chapter_consistency_fix failed | chapter_id=%s", chapter_id)
        try:
            db.rollback()
            c2 = db.get(Chapter, chapter_id)
            if c2:
                # 更新小说状态为 failed
                n = db.get(Novel, c2.novel_id)
                if n:
                    n.status = "failed"
                
                append_generation_log(
                    db,
                    novel_id=c2.novel_id,
                    batch_id=batch_id,
                    event="chapter_consistency_failed",
                    level="error",
                    message=f"一致性修订失败：{e}",
                    chapter_no=c2.chapter_no,
                    meta={"chapter_id": chapter_id, "error": str(e)},
                )
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="novel.chapter_revise")
def novel_chapter_revise(
    chapter_id: str,
    user_id: str | None,
    batch_id: str,
    user_prompt: str,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        c = db.get(Chapter, chapter_id)
        if not c:
            raise ValueError("章节不存在")
        n = db.get(Novel, c.novel_id)
        if not n:
            raise ValueError("小说不存在")
        fbs = (
            db.query(ChapterFeedback)
            .filter(ChapterFeedback.chapter_id == chapter_id)
            .order_by(ChapterFeedback.created_at.asc())
            .all()
        )
        bodies = [x.body for x in fbs]
        llm = NovelLLMService(billing_user_id=user_id)
        mem = latest_memory_json(db, c.novel_id)
        append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=batch_id,
            event="chapter_revise_started",
            message="后台按意见改稿已开始",
            chapter_no=c.chapter_no,
            meta={"chapter_id": chapter_id},
        )
        db.commit()
        new_text = llm.revise_chapter_sync(
            n, c, mem, bodies, user_prompt.strip(), db=db
        )
        c.pending_content = new_text
        c.pending_revision_prompt = user_prompt.strip()
        c.status = "pending_review"
        append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=batch_id,
            event="chapter_revise_done",
            message="按意见改稿已完成，待审阅",
            chapter_no=c.chapter_no,
            meta={"chapter_id": chapter_id},
        )
        db.commit()
        return {"status": "ok", "chapter_id": chapter_id}
    except Exception as e:
        logger.exception("novel.chapter_revise failed | chapter_id=%s", chapter_id)
        try:
            db.rollback()
            c2 = db.get(Chapter, chapter_id)
            if c2:
                # 更新小说状态为 failed
                n = db.get(Novel, c2.novel_id)
                if n:
                    n.status = "failed"
                
                append_generation_log(
                    db,
                    novel_id=c2.novel_id,
                    batch_id=batch_id,
                    event="chapter_revise_failed",
                    level="error",
                    message=f"按意见改稿失败：{e}",
                    chapter_no=c2.chapter_no,
                    meta={"chapter_id": chapter_id, "error": str(e)},
                )
                db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="novel.sync_json_snapshot")
def novel_sync_json_snapshot(novel_id: str, summary: str = "手动同步：从规范化存储生成 JSON 快照") -> dict[str, Any]:
    """
    异步任务：将规范化存储中的数据反向同步到 NovelMemory (JSON 快照) 中。
    """
    db = SessionLocal()
    try:
        new_ver = sync_json_snapshot_from_normalized(db, novel_id, summary)
        db.commit()
        logger.info("novel.sync_json_snapshot done | novel_id=%s version=%s", novel_id, new_ver)
        return {"status": "ok", "version": new_ver}
    except Exception:
        db.rollback()
        logger.exception("novel.sync_json_snapshot failed | novel_id=%s", novel_id)
        raise
    finally:
        db.close()


@celery_app.task(name="novel.consolidate_memory")
def novel_consolidate_memory(novel_id: str) -> dict[str, Any]:
    """
    异步任务：将较早章节的 key_facts 压缩进 timeline_archive，并裁剪过久章节的 key_facts。
    通常在每 N 章审定通过时由后台触发，也可手动调用。
    """
    db = SessionLocal()
    try:
        n = db.get(Novel, novel_id)
        if not n:
            return {"status": "not_found", "novel_id": novel_id}
        llm = _novel_llm_for_novel(n)
        result = llm.consolidate_memory_archive_sync(n, db)
        logger.info(
            "novel.consolidate_memory done | novel_id=%s result=%s",
            novel_id,
            result,
        )
        return {"status": "ok", "novel_id": novel_id, **result}
    except Exception:
        db.rollback()
        logger.exception("novel.consolidate_memory failed | novel_id=%s", novel_id)
        raise
    finally:
        db.close()


@celery_app.task(name="novel.ai_create_and_start_task")
def novel_ai_create_and_start_task(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    styles: list[str],
    notes: str,
    length_type: str,
    target_generate_chapters: int,
    target_chapters: int | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    r = _redis_for_novel_queue()
    lock = None
    acquired = False
    try:
        if r is not None:
            lock = r.lock(
                _novel_auto_pipeline_lock_key(novel_id),
                timeout=6 * 60 * 60,
                blocking=False,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                recover_stale_auto_pipeline_state(
                    db,
                    novel_id,
                    exclude_batch_id=batch_id,
                    exclude_task_ids={str(novel_ai_create_and_start_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="ai_create_failed",
                    level="error",
                    message="AI 一键建书跳过：同一小说已有任务在执行",
                    meta={"reason": "locked"},
                )
                db.commit()
                _task_set_terminal(
                    db,
                    batch_id=batch_id,
                    status="skipped",
                    message="已跳过：同一小说已有任务在执行",
                )
                return {"status": "skipped", "reason": "locked"}

        _task_set_started(db, batch_id=batch_id, message="AI 建书任务已开始")
        from app.services.novel_auto_pipeline import run_ai_create_and_start_sync
        result = run_ai_create_and_start_sync(
            db=db,
            novel_id=novel_id,
            styles=styles,
            notes=notes,
            length_type=length_type,
            target_generate_chapters=target_generate_chapters,
            target_chapters=target_chapters,
            billing_user_id=user_id,
            batch_id=batch_id,
        )
        if result.get("resume_only"):
            db.commit()
            if not result.get("skip_task_done_log"):
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="ai_create_done",
                    message=f"AI 一键建书完成，本次生成 {result.get('chapters_generated', 0)} 章",
                    meta={"chapters_generated": result.get("chapters_generated", 0)},
                )
                db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
            return result
        if str(result.get("status") or "") == "cancelled":
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="cancelled", message="已取消")
        else:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="ai_create_done",
                message=f"AI 一键建书完成，本次生成 {result.get('chapters_generated', 0)} 章",
                meta={"chapters_generated": result.get("chapters_generated", 0)},
            )
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        return result
    except Exception as e:
        logger.exception("novel_ai_create_and_start_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
            # 更新小说状态为 failed 标识失败
            from app.models.novel import Novel
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="ai_create_failed",
                level="error",
                message=f"AI 一键建书失败：{e}",
                meta={"error": str(e)}
            )
            db.commit()
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="failed",
                message=f"失败：{e}",
            )
        except Exception:
            db.rollback()
        raise
    finally:
        if lock is not None and acquired:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    "ai_create lock release failed | novel_id=%s batch_id=%s",
                    novel_id,
                    batch_id,
                )
        db.close()


def _regenerate_framework_sync(
    llm: NovelLLMService,
    novel: Novel,
    instruction: str,
    db,
    progress_callback=None,
) -> tuple[str, str]:
    """同步包装：按指令重写 base framework（设定/人物/主线），不含 arcs。
    重写后需要用户重新确认 base，然后手动触发 arcs 生成。
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            llm.generate_base_framework(
                novel,
                db=db,
                progress_callback=progress_callback,
                mode="regen",
                instruction=instruction,
            )
        )
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _update_framework_characters_sync(
    llm: NovelLLMService,
    novel: Novel,
    characters: list[dict[str, Any]],
    db,
    progress_callback=None,
) -> tuple[str, str]:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            llm.update_framework_characters(
                novel,
                characters,
                db=db,
                progress_callback=progress_callback,
            )
        )
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _generate_base_framework_sync(
    llm: NovelLLMService, novel: Novel, db, progress_callback=None
) -> tuple[str, str]:
    """同步包装：只生成 base framework（设定/人物/主线），不含 arcs。"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            llm.generate_base_framework(novel, db=db, progress_callback=progress_callback)
        )
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _generate_arcs_for_volumes_sync(
    llm: NovelLLMService,
    novel: Novel,
    *,
    target_volume_nos: list[int] | None = None,
    instruction: str = "",
    db=None,
    progress_callback=None,
) -> tuple[str, str]:
    """同步包装：为指定卷生成 arcs 并增量合并。"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            llm.generate_arcs_for_volumes(
                novel,
                target_volume_nos=target_volume_nos,
                instruction=instruction,
                db=db,
                progress_callback=progress_callback,
            )
        )
    finally:
        asyncio.set_event_loop(None)
        loop.close()


@celery_app.task(name="novel.novel_generate_framework_task")
def novel_generate_framework_task(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
) -> dict[str, Any]:
    db = SessionLocal()
    r = _redis_for_novel_queue()
    lock = None
    acquired = False
    try:
        if r is not None:
            lock = r.lock(
                _novel_auto_pipeline_lock_key(novel_id),
                timeout=6 * 60 * 60,
                blocking=False,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                recover_stale_auto_pipeline_state(
                    db,
                    novel_id,
                    exclude_batch_id=batch_id,
                    exclude_task_ids={str(novel_generate_framework_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
                _mark_novel_failed_if_missing_framework(db, novel_id)
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="framework_generate_failed",
                    level="error",
                    message="生成大纲跳过：同一小说已有任务在执行",
                    meta={"reason": "locked"},
                )
                _task_set_terminal(
                    db,
                    batch_id=batch_id,
                    status="failed",
                    message="生成大纲失败：同一小说已有任务在执行，请稍后重试",
                )
                db.commit()
                return {"status": "skipped", "reason": "locked"}

        _task_set_started(db, batch_id=batch_id, message="生成大纲任务已开始")
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_generate_started",
            message="正在生成设定、人物与主线大纲...",
        )
        db.commit()

        n = db.get(Novel, novel_id)
        if not n:
            _task_set_terminal(db, batch_id=batch_id, status="failed", message="小说不存在")
            db.commit()
            return {"status": "not_found", "novel_id": novel_id}
        
        llm = NovelLLMService(billing_user_id=user_id)
        progress_logger = _make_generation_progress_logger(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_generate_progress",
        )
        # 只生成 base（设定/人物/主线），不生成 arcs
        md, fj = _generate_base_framework_sync(llm, n, db, progress_callback=progress_logger)
        n.framework_markdown = md
        n.framework_json = fj
        n.framework_confirmed = False
        n.base_framework_confirmed = False
        db.commit()
        
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_generate_done",
            message="基础大纲生成完毕（待确认）",
        )
        _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        db.commit()
        return {"status": "ok", "batch_id": batch_id}
    except Exception as e:
        logger.exception("novel_generate_framework_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="framework_generate_failed",
                level="error",
                message=f"生成大纲失败：{e}",
                meta={"error": str(e)},
            )
            _task_set_terminal(db, batch_id=batch_id, status="failed", message=f"失败：{e}")
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        if lock is not None and acquired:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    "framework_generate lock release failed | novel_id=%s batch_id=%s",
                    novel_id,
                    batch_id,
                )
        db.close()


@celery_app.task(name="novel.framework_regen_task")
def novel_framework_regen_task(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    instruction: str,
) -> dict[str, Any]:
    db = SessionLocal()
    r = _redis_for_novel_queue()
    lock = None
    acquired = False
    try:
        if r is not None:
            lock = r.lock(
                _novel_auto_pipeline_lock_key(novel_id),
                timeout=6 * 60 * 60,
                blocking=False,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                recover_stale_auto_pipeline_state(
                    db,
                    novel_id,
                    exclude_batch_id=batch_id,
                    exclude_task_ids={str(novel_framework_regen_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
                _mark_novel_failed_if_missing_framework(db, novel_id)
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="framework_regen_failed",
                    level="error",
                    message="重生成大纲跳过：同一小说已有任务在执行",
                    meta={"reason": "locked"},
                )
                _task_set_terminal(
                    db,
                    batch_id=batch_id,
                    status="failed",
                    message="重生成大纲失败：同一小说已有任务在执行，请稍后重试",
                )
                db.commit()
                return {"status": "skipped", "reason": "locked"}

        _task_set_started(db, batch_id=batch_id, message="重生成大纲任务已开始")
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_regen_started",
            message="正在按指令重生成大纲...",
        )
        db.commit()

        n = db.get(Novel, novel_id)
        if not n:
            _task_set_terminal(db, batch_id=batch_id, status="failed", message="小说不存在")
            db.commit()
            return {"status": "not_found", "novel_id": novel_id}
        llm = NovelLLMService(billing_user_id=user_id)
        progress_logger = _make_generation_progress_logger(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_regen_progress",
        )
        md, fj = _regenerate_framework_sync(
            llm,
            n,
            instruction,
            db,
            progress_callback=progress_logger,
        )
        n.framework_markdown = md
        n.framework_json = fj
        n.framework_confirmed = False
        n.base_framework_confirmed = False
        db.commit()
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_regen_done",
            message="大纲已重生成（待确认）",
        )
        _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        db.commit()
        return {"status": "ok", "batch_id": batch_id}
    except Exception as e:
        logger.exception("novel_framework_regen_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="framework_regen_failed",
                level="error",
                message=f"重生成大纲失败：{e}",
                meta={"error": str(e)},
            )
            _task_set_terminal(db, batch_id=batch_id, status="failed", message=f"失败：{e}")
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        if lock is not None and acquired:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    "framework_regen lock release failed | novel_id=%s batch_id=%s",
                    novel_id,
                    batch_id,
                )
        db.close()


@celery_app.task(name="novel.framework_update_characters_task")
def novel_framework_update_characters_task(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    characters: list[dict[str, Any]],
) -> dict[str, Any]:
    db = SessionLocal()
    r = _redis_for_novel_queue()
    lock = None
    acquired = False
    try:
        if r is not None:
            lock = r.lock(
                _novel_auto_pipeline_lock_key(novel_id),
                timeout=6 * 60 * 60,
                blocking=False,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                recover_stale_auto_pipeline_state(
                    db,
                    novel_id,
                    exclude_batch_id=batch_id,
                    exclude_task_ids={str(novel_framework_update_characters_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="framework_characters_failed",
                    level="error",
                    message="更新人物设定跳过：同一小说已有任务在执行",
                    meta={"reason": "locked"},
                )
                db.commit()
                _task_set_terminal(
                    db,
                    batch_id=batch_id,
                    status="skipped",
                    message="已跳过：同一小说已有任务在执行",
                )
                return {"status": "skipped", "reason": "locked"}

        _task_set_started(db, batch_id=batch_id, message="更新人物设定任务已开始")
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_characters_started",
            message="正在按人物设定更新大纲...",
            meta={"characters_count": len(characters or [])},
        )
        db.commit()

        n = db.get(Novel, novel_id)
        if not n:
            _task_set_terminal(db, batch_id=batch_id, status="failed", message="小说不存在")
            return {"status": "not_found", "novel_id": novel_id}
        llm = NovelLLMService(billing_user_id=user_id)
        progress_logger = _make_generation_progress_logger(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_characters_progress",
        )
        md, fj = _update_framework_characters_sync(
            llm,
            n,
            characters or [],
            db,
            progress_callback=progress_logger,
        )
        n.framework_markdown = md
        n.framework_json = fj
        n.framework_confirmed = False
        n.base_framework_confirmed = False
        db.commit()
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="framework_characters_done",
            message="人物设定已更新到大纲（待确认）",
            meta={"characters_count": len(characters or [])},
        )
        db.commit()
        _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        return {"status": "ok", "batch_id": batch_id}
    except Exception as e:
        logger.exception(
            "novel_framework_update_characters_task failed | novel_id=%s batch_id=%s",
            novel_id,
            batch_id,
        )
        try:
            db.rollback()
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="framework_characters_failed",
                level="error",
                message=f"更新人物设定失败：{e}",
                meta={"error": str(e)},
            )
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="failed", message=f"失败：{e}")
        except Exception:
            db.rollback()
        raise
    finally:
        if lock is not None and acquired:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    "framework_characters lock release failed | novel_id=%s batch_id=%s",
                    novel_id,
                    batch_id,
                )
        db.close()


def _ensure_novel_volume_rows_for_arcs_writes(
    db,
    novel: Novel,
    target_volume_nos: list[int] | None,
    *,
    volume_size: int = 50,
) -> list[int]:
    """
    为 Arcs 落库补齐 NovelVolume 行。

    若用户未先在主流程「生成卷列表」，按 target_volume_nos 写入时 vol_row 查询为空，
    旧逻辑会静默跳过落库却仍报「生成完毕」，导致卷列表 API 仍为空。
    """
    created: list[int] = []
    if not target_volume_nos:
        return created
    tc_raw = getattr(novel, "target_chapters", None)
    total_chapters = int(tc_raw) if isinstance(tc_raw, int) and tc_raw > 0 else 1

    for vol_no in sorted({int(v) for v in target_volume_nos if isinstance(v, int) and v > 0}):
        exists = (
            db.query(NovelVolume)
            .filter(NovelVolume.novel_id == novel.id, NovelVolume.volume_no == vol_no)
            .first()
        )
        if exists:
            continue
        vol_lo = (vol_no - 1) * volume_size + 1
        vol_hi = min(total_chapters, vol_no * volume_size)
        if vol_lo > total_chapters:
            continue
        db.add(
            NovelVolume(
                novel_id=novel.id,
                volume_no=vol_no,
                title=f"第{vol_no}卷",
                summary="",
                from_chapter=vol_lo,
                to_chapter=vol_hi,
                status="draft",
            )
        )
        created.append(vol_no)
    if created:
        db.flush()
    return created


def _arcs_overlapping_chapter_range(
    arcs_list: list[Any], vol_lo: int, vol_hi: int
) -> list[Any]:
    """按章节区间把弧线归入某一卷（与 novel_repo.arc_bounds_from_dict 一致，兼容字符串/浮点）。"""
    out: list[Any] = []
    for arc in arcs_list:
        if not isinstance(arc, dict):
            continue
        b = arc_bounds_from_dict(arc)
        if not b:
            continue
        a_lo, a_hi = b
        if not (a_hi < vol_lo or a_lo > vol_hi):
            out.append(arc)
    return out


@celery_app.task(name="novel.generate_arcs_task")
def novel_generate_arcs_task(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    target_volume_nos: list[int] | None = None,
    instruction: str = "",
) -> dict[str, Any]:
    """为指定卷生成 arcs：写入各卷 outline_*；小说表仅保留基础大纲（不含 arcs）。"""
    db = SessionLocal()
    r = _redis_for_novel_queue()
    lock = None
    acquired = False
    try:
        if r is not None:
            lock = r.lock(
                _novel_auto_pipeline_lock_key(novel_id),
                timeout=6 * 60 * 60,
                blocking=False,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                recover_stale_auto_pipeline_state(
                    db,
                    novel_id,
                    exclude_batch_id=batch_id,
                    exclude_task_ids={str(novel_generate_arcs_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="arcs_generate_failed",
                    level="error",
                    message="生成 Arcs 跳过：同一小说已有任务在执行",
                    meta={"reason": "locked"},
                )
                db.commit()
                _task_set_terminal(
                    db,
                    batch_id=batch_id,
                    status="skipped",
                    message="已跳过：同一小说已有任务在执行",
                )
                return {"status": "skipped", "reason": "locked"}

        _task_set_started(db, batch_id=batch_id, message="Arcs 生成任务已开始")
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="arcs_generate_started",
            message=f"正在生成第{','.join(str(v) for v in (target_volume_nos or []))}卷的 Arcs...",
            meta={"target_volume_nos": target_volume_nos},
        )
        db.commit()

        n = db.get(Novel, novel_id)
        if not n:
            _task_set_terminal(db, batch_id=batch_id, status="failed", message="小说不存在")
            return {"status": "not_found", "novel_id": novel_id}

        if not n.base_framework_confirmed:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="arcs_generate_failed",
                level="error",
                message="基础大纲尚未确认，无法生成 Arcs",
            )
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="failed", message="基础大纲尚未确认")
            return {"status": "failed", "reason": "base_not_confirmed"}

        llm = NovelLLMService(billing_user_id=user_id)
        progress_logger = _make_generation_progress_logger(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="arcs_generate_progress",
        )
        md, fj = _generate_arcs_for_volumes_sync(
            llm,
            n,
            target_volume_nos=target_volume_nos,
            instruction=instruction,
            db=db,
            progress_callback=progress_logger,
        )
        base_md, base_j = coerce_novel_outline_base_fields(md, fj)
        n.framework_markdown = base_md
        n.framework_json = base_j

        vol_autocreated = _ensure_novel_volume_rows_for_arcs_writes(
            db, n, target_volume_nos
        )
        if vol_autocreated:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="arcs_generate_volumes_autocreated",
                level="info",
                message=(
                    "卷表尚无对应卷记录，已自动创建占位卷以便写入 Arcs：第"
                    f"{','.join(str(v) for v in vol_autocreated)}卷"
                ),
                meta={"volume_nos": vol_autocreated},
            )

        # 将 arcs 写入对应卷的 outline_json / outline_markdown（与小说级大纲分离）
        try:
            arcs_data = json.loads(fj) if fj else {}
        except json.JSONDecodeError:
            arcs_data = {}
        arcs_list = arcs_data.get("arcs", []) if isinstance(arcs_data, dict) else []
        if isinstance(arcs_list, list) and arcs_list and target_volume_nos:
            volume_size = 50
            targets: list[int] = []
            for raw in target_volume_nos:
                vn: int | None = None
                if isinstance(raw, int) and raw > 0:
                    vn = raw
                elif isinstance(raw, float) and raw.is_integer():
                    i = int(raw)
                    if i > 0:
                        vn = i
                if vn is not None:
                    targets.append(vn)
            targets = sorted(set(targets))
            for vol_no in targets:
                vol_lo = (vol_no - 1) * volume_size + 1
                vol_hi = vol_no * volume_size
                vol_arcs = _arcs_overlapping_chapter_range(arcs_list, vol_lo, vol_hi)
                if (
                    not vol_arcs
                    and len(targets) == 1
                    and vol_no == targets[0]
                ):
                    vol_arcs = list(arcs_list)
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="arcs_generate_volume_fallback_whole_list",
                        level="warning",
                        message=(
                            f"第{vol_no}卷：弧线章节区间与默认 1–50 章网格未对齐，"
                            "已将本次模型返回的全部弧线写入该卷。"
                        ),
                        meta={"volume_no": vol_no, "arc_count": len(arcs_list)},
                    )
                vol_row = (
                    db.query(NovelVolume)
                    .filter(
                        NovelVolume.novel_id == novel_id,
                        NovelVolume.volume_no == vol_no,
                    )
                    .first()
                )
                if vol_row and vol_arcs:
                    vol_row.outline_json = json.dumps(
                        {"volume_no": vol_no, "arcs": vol_arcs}, ensure_ascii=False
                    )
                    vol_row.outline_markdown = render_volume_arcs_markdown(vol_no, vol_arcs)
        else:
            volumes = (
                db.query(NovelVolume)
                .filter(NovelVolume.novel_id == novel_id)
                .order_by(NovelVolume.volume_no.asc())
                .all()
            )
            if isinstance(arcs_list, list) and arcs_list and volumes:
                for vol in volumes:
                    vol_lo = int(vol.from_chapter or 0)
                    vol_hi = int(vol.to_chapter or 0)
                    if vol_lo <= 0 or vol_hi <= 0:
                        continue
                    vol_arcs = _arcs_overlapping_chapter_range(arcs_list, vol_lo, vol_hi)
                    if vol_arcs:
                        vn = int(vol.volume_no)
                        vol.outline_json = json.dumps(
                            {"volume_no": vn, "arcs": vol_arcs}, ensure_ascii=False
                        )
                        vol.outline_markdown = render_volume_arcs_markdown(vn, vol_arcs)
        db.commit()

        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="arcs_generate_done",
            message=f"第{','.join(str(v) for v in (target_volume_nos or []))}卷 Arcs 生成完毕",
            meta={"target_volume_nos": target_volume_nos},
        )
        db.commit()
        _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        return {"status": "ok", "batch_id": batch_id, "target_volume_nos": target_volume_nos}
    except Exception as e:
        logger.exception("novel_generate_arcs_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="arcs_generate_failed",
                level="error",
                message=f"生成 Arcs 失败：{e}",
                meta={"error": str(e)},
            )
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="failed", message=f"失败：{e}")
        except Exception:
            db.rollback()
        raise
    finally:
        if lock is not None and acquired:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    "arcs_generate lock release failed | novel_id=%s batch_id=%s",
                    novel_id,
                    batch_id,
                )
        db.close()


@celery_app.task(name="novel.auto_pipeline_task")
def novel_auto_pipeline_task(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    target_count: int,
    trigger_source: str = "manual",
    scheduled_date: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    r = _redis_for_novel_queue()
    lock = None
    acquired = False
    workflow_run = None
    try:
        if settings.novel_workflow_v2_enabled:
            workflow_run = get_workflow_run_by_batch_id(db, batch_id=batch_id)
            if workflow_run is None:
                workflow_run = create_workflow_run(
                    db,
                    novel_id=novel_id,
                    run_type="auto_pipeline",
                    trigger_source=trigger_source,
                    batch_id=batch_id,
                    input_payload={
                        "target_count": target_count,
                        "scheduled_date": scheduled_date,
                    },
                    cursor_payload={"phase": "queued"},
                )
                append_workflow_event(
                    db,
                    run=workflow_run,
                    event_type="queued",
                    message="全自动生成任务已入队",
                    meta={
                        "target_count": target_count,
                        "trigger_source": trigger_source,
                        "scheduled_date": scheduled_date,
                    },
                )
                db.commit()
        if r is not None:
            lock = r.lock(
                _novel_auto_pipeline_lock_key(novel_id),
                timeout=6 * 60 * 60,
                blocking=False,
            )
            acquired = lock.acquire(blocking=False)
            if not acquired:
                recover_stale_auto_pipeline_state(
                    db,
                    novel_id,
                    exclude_batch_id=batch_id,
                    exclude_task_ids={str(novel_auto_pipeline_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
                if workflow_run is not None:
                    touch_workflow_run_status(
                        db,
                        workflow_run,
                        status="skipped",
                        current_step="lock_check",
                        cursor_payload={"phase": "skipped", "reason": "locked"},
                        error_payload={"reason": "locked"},
                    )
                    append_workflow_event(
                        db,
                        run=workflow_run,
                        event_type="skipped_locked",
                        level="warning",
                        message="全自动生成已跳过：同一小说已有任务在执行",
                        meta={"reason": "locked"},
                    )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="auto_pipeline_skipped",
                    level="warning",
                    message="全自动生成已跳过：同一小说已有任务在执行",
                    meta={"reason": "locked", "trigger_source": trigger_source},
                )
                db.commit()
                _task_set_terminal(
                    db,
                    batch_id=batch_id,
                    status="skipped",
                    message="已跳过：同一小说已有任务在执行",
                )
                return {"status": "skipped", "reason": "locked"}

        if has_pending_auto_pipeline_batch(db, novel_id, exclude_batch_id=batch_id) or (
            has_pending_chapter_generation_batch(db, novel_id)
        ):
            if workflow_run is not None:
                touch_workflow_run_status(
                    db,
                    workflow_run,
                    status="skipped",
                    current_step="pending_batch_check",
                    cursor_payload={"phase": "skipped", "reason": "pending_batch"},
                    error_payload={"reason": "pending_batch"},
                )
                append_workflow_event(
                    db,
                    run=workflow_run,
                    event_type="skipped_pending_batch",
                    level="warning",
                    message="全自动生成已跳过：检测到同书已有进行中的生成批次",
                    meta={"reason": "pending_batch"},
                )
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_skipped",
                level="warning",
                message="全自动生成已跳过：检测到同书已有进行中的生成批次",
                meta={"reason": "pending_batch", "trigger_source": trigger_source},
            )
            db.commit()
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="skipped",
                message="已跳过：检测到同书已有进行中的生成批次",
            )
            return {"status": "skipped", "reason": "pending_batch"}

        from app.services.novel_auto_pipeline import run_full_auto_generation_sync

        _task_set_started(db, batch_id=batch_id, message="全自动生成任务已开始")
        if workflow_run is not None:
            touch_workflow_run_status(
                db,
                workflow_run,
                status="running",
                current_step="auto_pipeline_start",
                cursor_payload={
                    "phase": "running",
                    "target_count": target_count,
                    "trigger_source": trigger_source,
                },
            )
            append_workflow_event(
                db,
                run=workflow_run,
                event_type="started",
                message="全自动生成任务已开始执行",
                meta={"target_count": target_count, "trigger_source": trigger_source},
            )
            db.commit()
        result = run_full_auto_generation_sync(
            db=db,
            novel_id=novel_id,
            target_count=target_count,
            billing_user_id=user_id,
            batch_id=batch_id,
            use_cold_recall=False,
            cold_recall_items=5,
            auto_consistency_check=None,
            auto_plan_guard_check=None,
            auto_plan_guard_fix=None,
            auto_style_polish=None,
            workflow_run=workflow_run,
        )
        if result.get("already_done"):
            if workflow_run is not None and settings.novel_workflow_v2_enabled:
                touch_workflow_run_status(
                    db,
                    workflow_run,
                    status="done",
                    current_step="done",
                    cursor_payload={"phase": "noop"},
                    output_payload=result,
                )
            db.commit()
            _task_set_terminal(
                db, batch_id=batch_id, status="done", message="已完成（恢复时补终态）"
            )
            return result
        result_status = str(result.get("status") or "")
        if result_status == "cancelled":
            if workflow_run is not None:
                touch_workflow_run_status(
                    db,
                    workflow_run,
                    status="cancelled",
                    current_step="cancelled",
                    cursor_payload={
                        "phase": "cancelled",
                        "chapters_generated": result.get("chapters_generated", 0),
                    },
                    output_payload=result,
                )
                append_workflow_event(
                    db,
                    run=workflow_run,
                    event_type="cancelled",
                    level="warning",
                    message="全自动生成任务已取消",
                    meta=result,
                )
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="cancelled", message="已取消")
        elif result_status == "blocked":
            if workflow_run is not None:
                touch_workflow_run_status(
                    db,
                    workflow_run,
                    status="blocked",
                    current_step="chapter_auto_approve_blocked",
                    cursor_payload={
                        "phase": "blocked",
                        "blocked_chapter_no": result.get("blocked_chapter_no"),
                    },
                    error_payload={
                        "blocked_chapter_no": result.get("blocked_chapter_no"),
                        "blocked_issues": result.get("blocked_issues") or [],
                    },
                    output_payload=result,
                )
                append_workflow_event(
                    db,
                    run=workflow_run,
                    event_type="blocked",
                    level="warning",
                    message="全自动生成因自动审定门禁被阻断",
                    meta=result,
                )
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_failed",
                level="warning",
                message=(
                    f"全自动生成已停止：第{int(result.get('blocked_chapter_no') or 0)}章未通过自动审定门禁"
                ),
                meta={"issues": result.get("blocked_issues") or []},
            )
            db.commit()
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="failed",
                message=f"已停止：第{int(result.get('blocked_chapter_no') or 0)}章未通过自动审定门禁",
            )
        else:
            if workflow_run is not None:
                touch_workflow_run_status(
                    db,
                    workflow_run,
                    status="done",
                    current_step="done",
                    cursor_payload={
                        "phase": "done",
                        "chapters_generated": result.get("chapters_generated", 0),
                    },
                    output_payload=result,
                )
                append_workflow_event(
                    db,
                    run=workflow_run,
                    event_type="done",
                    message="全自动生成任务已完成",
                    meta=result,
                )
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_done",
                message=f"全自动生成完成，本次生成 {result.get('chapters_generated', 0)} 章",
                meta={
                    "trigger_source": trigger_source,
                    "chapters_generated": result.get("chapters_generated", 0),
                },
            )
            if trigger_source == "schedule" and scheduled_date:
                n = db.get(Novel, novel_id)
                if n and (n.last_auto_date or "") < scheduled_date:
                    n.last_auto_date = scheduled_date
            db.commit()
            _task_set_terminal(db, batch_id=batch_id, status="done", message="已完成")
        return result
    except Exception as e:
        logger.exception("novel_auto_pipeline_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
            if workflow_run is not None:
                touch_workflow_run_status(
                    db,
                    workflow_run,
                    status="failed",
                    current_step="failed",
                    cursor_payload={"phase": "failed"},
                    error_payload={"error": str(e)},
                )
                append_workflow_event(
                    db,
                    run=workflow_run,
                    event_type="failed",
                    level="error",
                    message=f"全自动生成失败：{e}",
                    meta={"error": str(e)},
                )
            # 更新小说状态为 failed
            n = db.get(Novel, novel_id)
            if n:
                n.status = "failed"
            
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_failed",
                level="error",
                message=f"全自动生成失败：{e}",
                meta={"error": str(e)}
            )
            db.commit()
            _task_set_terminal(
                db,
                batch_id=batch_id,
                status="failed",
                message=f"失败：{e}",
            )
        except Exception:
            db.rollback()
        raise
    finally:
        if lock is not None and acquired:
            try:
                lock.release()
            except Exception:
                logger.exception(
                    "auto_pipeline lock release failed | novel_id=%s batch_id=%s",
                    novel_id,
                    batch_id,
                )
        db.close()
