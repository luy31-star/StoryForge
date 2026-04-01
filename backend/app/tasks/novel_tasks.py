from __future__ import annotations

import json
import logging
import time
from typing import Any

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
    memory_refresh_confirmation_token,
)
from app.services.novel_volume_plan_batch import run_volume_chapter_plan_batch_sync
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _novel_mem_delta_zkey(novel_id: str) -> str:
    return f"vocalflow:novel:mem_delta:{novel_id}"


def _novel_mem_delta_lock_key(novel_id: str) -> str:
    return f"vocalflow:lock:novel_mem_delta:{novel_id}"


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
    每日定时：对 daily_auto_chapters > 0 且已确认框架的书，自动生成指定章数，
    状态为已审定（approved），与自动续写一致；正文生成后已在流程中更新工作记忆。
    """
    db = SessionLocal()
    processed = 0
    started = time.perf_counter()
    try:
        novels = (
            db.query(Novel)
            .filter(Novel.daily_auto_chapters > 0, Novel.framework_confirmed.is_(True))
            .all()
        )
        for n in novels:
            llm = _novel_llm_for_novel(n)
            try:
                novel_started = time.perf_counter()
                mem = latest_memory_json(db, n.id)
                base_no = next_chapter_no_from_approved(db, n.id)
                logger.info(
                    "daily_chapters start novel | novel_id=%s title=%r count=%s base_no=%s mem_chars=%s",
                    n.id,
                    n.title,
                    n.daily_auto_chapters,
                    base_no,
                    len(mem or ""),
                )
                for idx in range(n.daily_auto_chapters):
                    step_started = time.perf_counter()
                    continuity = format_continuity_excerpts(
                        db, n.id, approved_only=True
                    )
                    full_context = format_recent_approved_fulltext_context(
                        db,
                        n.id,
                        max_chapters=max(1, settings.novel_recent_full_context_chapters),
                    )
                    no = base_no + idx
                    raw_content = llm.generate_chapter_sync(
                        n, no, "", mem, continuity, full_context, db=db
                    )
                    content = raw_content
                    draft_metrics = chapter_content_metrics(raw_content)
                    if settings.novel_consistency_check_chapter:
                        try:
                            content = llm.check_and_fix_chapter_sync(
                                n, no, "", mem, continuity, raw_content, db=db
                            )
                        except Exception:
                            logger.exception(
                                "daily_chapters consistency failed, fallback raw | novel_id=%s chapter_no=%s",
                                n.id,
                                no,
                            )
                            content = raw_content
                    try:
                        memory_delta_result = llm.propose_memory_update_from_chapter_sync(
                            n,
                            chapter_no=no,
                            chapter_title=f"第{no}章",
                            chapter_text=content,
                            prev_memory=mem,
                            db=db,
                        )
                        if memory_delta_result.get("ok"):
                            mem = str(memory_delta_result.get("payload_json") or mem)
                        else:
                            logger.warning(
                                "daily_chapters memory delta invalid | novel_id=%s chapter_no=%s errors=%s",
                                n.id,
                                no,
                                memory_delta_result.get("errors") or [],
                            )
                    except Exception:
                        logger.exception(
                            "daily_chapters memory delta failed | novel_id=%s chapter_no=%s",
                            n.id,
                            no,
                        )
                    saved_metrics = chapter_content_metrics(content)
                    ch = (
                        db.query(Chapter)
                        .filter(Chapter.novel_id == n.id, Chapter.chapter_no == no)
                        .order_by(Chapter.updated_at.desc())
                        .first()
                    )
                    if ch:
                        ch.title = f"第{no}章"
                        ch.content = content
                        ch.pending_content = ""
                        ch.pending_revision_prompt = ""
                        ch.status = "approved"
                        ch.source = "daily_job"
                    else:
                        ch = Chapter(
                            novel_id=n.id,
                            chapter_no=no,
                            title=f"第{no}章",
                            content=content,
                            status="approved",
                            source="daily_job",
                        )
                        db.add(ch)
                        db.flush()
                    processed += 1
                    logger.info(
                        "daily_chapters step done | novel_id=%s chapter_no=%s draft_body_chars=%s saved_body_chars=%s paragraphs=%s elapsed=%.2fs",
                        n.id,
                        no,
                        draft_metrics["body_chars"],
                        saved_metrics["body_chars"],
                        saved_metrics["paragraph_count"],
                        time.perf_counter() - step_started,
                    )
                db.commit()
                logger.info(
                    "daily_chapters novel done | novel_id=%s elapsed=%.2fs",
                    n.id,
                    time.perf_counter() - novel_started,
                )
            except RuntimeError as e:
                db.rollback()
                msg = str(e)
                if "积分" in msg or "不足" in msg:
                    logger.warning(
                        "daily_chapters novel skipped (billing) | novel_id=%s err=%s",
                        n.id,
                        msg,
                    )
                    continue
                logger.exception("daily_chapters novel failed | novel_id=%s", n.id)
                raise
            except Exception:
                db.rollback()
                logger.exception("daily_chapters novel failed | novel_id=%s", n.id)
                raise
    finally:
        db.close()
    logger.info(
        "daily_chapters finished | chapters_written=%s elapsed=%.2fs",
        processed,
        time.perf_counter() - started,
    )
    return {"chapters_written": processed}


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
