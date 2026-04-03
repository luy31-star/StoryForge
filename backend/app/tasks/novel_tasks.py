from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import redis
from redis.exceptions import RedisError
from sqlalchemy import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.novel import Chapter, ChapterFeedback, Novel, NovelGenerationLog, NovelMemory
from app.services.memory_normalize_sync import sync_json_snapshot_from_normalized
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_repo import (
    chapter_content_metrics,
    format_approved_chapters_summary,
    format_continuity_excerpts,
    format_recent_approved_fulltext_context,
    latest_memory_json,
    next_chapter_no_from_approved,
)
from app.services.memory_readable import memory_payload_to_readable_zh
from app.services.novel_chapter_generate_batch import run_generate_chapters_batch_sync
from app.services.novel_generation_common import (
    append_generation_log,
    has_pending_auto_pipeline_batch,
    has_pending_chapter_generation_batch,
    memory_refresh_confirmation_token,
)
from app.services.novel_volume_plan_batch import run_volume_chapter_plan_batch_sync
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_AUTO_PIPELINE_TASK_NAMES = {
    "novel.auto_pipeline_task",
    "novel.ai_create_and_start_task",
}
_AUTO_PIPELINE_NONTERMINAL_EVENTS = {
    "auto_pipeline_queued",
    "auto_pipeline_start",
    "auto_pipeline_plan_batch",
    "auto_pipeline_chapters",
    "ai_create_queued",
    "ai_create_brainstorming",
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
        return None


def _novel_llm_for_novel(novel: Novel) -> NovelLLMService:
    """后台任务按书主计费；无 user_id 的历史数据仍不计费。"""
    uid = getattr(novel, "user_id", None)
    if not uid:
        logger.warning(
            "novel task: novel has no user_id, LLM calls will not bill | novel_id=%s",
            novel.id,
        )
    return NovelLLMService(billing_user_id=uid)


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
        if active:
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
    for batch_id in stale_batches:
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
        recovered_batches.append(batch_id)

    if recovered_batches:
        db.commit()

    return {
        "active": active,
        "lock_exists": lock_exists,
        "recovered_lock": recovered_lock,
        "recovered_batches": recovered_batches,
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
    return {"triggered": processed}


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
) -> dict[str, int | str]:
    """
    单本小说后台刷新记忆：用于「审定通过/已审定章节改动」后异步刷新，避免阻塞接口。
    """
    db = SessionLocal()
    bid = batch_id or f"mem-refresh-{novel_id[:8]}-{int(time.time())}"
    try:
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
        chapters = (
            db.query(Chapter)
            .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
            .order_by(Chapter.chapter_no.asc())
            .all()
        )
        logger.info(
            "refresh_memory_for_novel loading approved chapters | novel_id=%s count=%s batch_id=%s",
            novel_id,
            len(chapters),
            bid,
        )
        if not chapters:
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
            max_chapters=settings.novel_memory_refresh_chapters,
        )
        prev = latest_memory_json(db, novel_id)
        current_version = (
            db.query(func.max(NovelMemory.version))
            .filter(NovelMemory.novel_id == novel_id)
            .scalar()
            or 0
        )
        llm = _novel_llm_for_novel(n)
        result = llm.refresh_memory_from_chapters_sync(n, summary, prev, db=db)
        if not result.get("ok"):
            cand = str(result.get("candidate_json") or "{}")
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_validation_failed",
                level="error",
                message="后台记忆刷新被校验拦截，未覆盖当前记忆",
                meta={
                    "errors": result.get("blocking_errors") or result.get("errors") or [],
                    "warnings": result.get("warnings") or [],
                    "auto_pass_notes": result.get("auto_pass_notes") or [],
                    "batch": result.get("batch"),
                    "current_version": current_version,
                    "candidate_json": cand,
                    "candidate_readable_zh": memory_payload_to_readable_zh(cand),
                },
            )
            db.commit()
            return {"status": "blocked", "novel_id": novel_id}
        if result.get("status") == "warning":
            cand = str(result.get("candidate_json") or "{}")
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_warning",
                level="warning",
                message="后台记忆刷新产出 warning 候选，未自动覆盖当前记忆",
                meta={
                    "warnings": result.get("warnings") or [],
                    "auto_pass_notes": result.get("auto_pass_notes") or [],
                    "current_version": current_version,
                    "candidate_json": cand,
                    "candidate_readable_zh": memory_payload_to_readable_zh(cand),
                    "confirmation_token": memory_refresh_confirmation_token(
                        novel_id, current_version, cand
                    ),
                },
            )
            db.commit()
            return {"status": "warning", "novel_id": novel_id}
        done_ver = (
            db.query(func.max(NovelMemory.version))
            .filter(NovelMemory.novel_id == novel_id)
            .scalar()
            or 0
        )
        _append_refresh_log(
            db,
            novel_id=novel_id,
            batch_id=bid,
            event="memory_refresh_done",
            message=f"后台记忆刷新完成，版本 v{done_ver}",
            meta={"version": done_ver},
        )
        db.commit()
        logger.info(
            "refresh_memory_for_novel done | novel_id=%s version=%s batch_id=%s",
            novel_id,
            done_ver,
            bid,
        )
        return {"status": "ok", "novel_id": novel_id, "version": done_ver}
    except Exception:
        db.rollback()
        try:
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
                meta={"source": "chapter_approve_memory_delta"},
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
        raw_nos = body.get("chapter_nos")
        if not isinstance(raw_nos, list) or not raw_nos:
            raise ValueError("缺少 chapter_nos")
        chapter_nos = [int(x) for x in raw_nos]
        return run_generate_chapters_batch_sync(
            db,
            novel_id=novel_id,
            billing_user_id=user_id,
            title_hint=str(body.get("title_hint") or ""),
            chapter_nos=chapter_nos,
            use_cold_recall=bool(body.get("use_cold_recall")),
            cold_recall_items=max(1, min(int(body.get("cold_recall_items") or 5), 12)),
            auto_consistency_check=bool(body.get("auto_consistency_check")),
            batch_id=batch_id,
            source=str(body.get("source") or "batch_auto"),
        )
    except Exception as e:
        logger.exception(
            "novel.generate_chapters_for_novel failed | novel_id=%s batch_id=%s",
            novel_id,
            batch_id,
        )
        try:
            db.rollback()
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
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="novel.volume_plan_batch_for_volume")
def novel_volume_plan_batch_for_volume(
    novel_id: str,
    user_id: str | None,
    batch_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_volume_chapter_plan_batch_sync(
            db,
            novel_id=novel_id,
            billing_user_id=user_id,
            volume_id=str(body["volume_id"]),
            batch_id=batch_id,
            force_regen=bool(body.get("force_regen")),
            batch_size=body.get("batch_size"),
            from_chapter=body.get("from_chapter"),
        )
    except Exception as e:
        logger.exception(
            "novel.volume_plan_batch_for_volume failed | novel_id=%s batch_id=%s",
            novel_id,
            batch_id,
        )
        try:
            db.rollback()
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
                return {"status": "skipped", "reason": "locked"}

        from app.services.novel_auto_pipeline import run_ai_create_and_start_sync
        result = run_ai_create_and_start_sync(
            db=db,
            novel_id=novel_id,
            styles=styles,
            notes=notes,
            length_type=length_type,
            target_generate_chapters=target_generate_chapters,
            billing_user_id=user_id,
            batch_id=batch_id,
        )
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="ai_create_done",
            message=f"AI 一键建书完成，本次生成 {result.get('chapters_generated', 0)} 章",
            meta={"chapters_generated": result.get("chapters_generated", 0)},
        )
        db.commit()
        return result
    except Exception as e:
        logger.exception("novel_ai_create_and_start_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
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
                    exclude_task_ids={str(novel_auto_pipeline_task.request.id or "")},
                )
                acquired = lock.acquire(blocking=False)
            if not acquired:
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
                return {"status": "skipped", "reason": "locked"}

        if has_pending_auto_pipeline_batch(db, novel_id, exclude_batch_id=batch_id) or (
            has_pending_chapter_generation_batch(db, novel_id)
        ):
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
            return {"status": "skipped", "reason": "pending_batch"}

        from app.services.novel_auto_pipeline import run_full_auto_generation_sync

        result = run_full_auto_generation_sync(
            db=db,
            novel_id=novel_id,
            target_count=target_count,
            billing_user_id=user_id,
            batch_id=batch_id,
            use_cold_recall=False,
            cold_recall_items=5,
            auto_consistency_check=bool(settings.novel_consistency_check_chapter),
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
        return result
    except Exception as e:
        logger.exception("novel_auto_pipeline_task failed | novel_id=%s batch_id=%s", novel_id, batch_id)
        try:
            db.rollback()
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
