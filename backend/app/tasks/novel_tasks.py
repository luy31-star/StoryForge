from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import func

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.novel import Chapter, Novel, NovelGenerationLog, NovelMemory
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
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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
    状态为 pending_review，供人工审阅与反馈意见。
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
        llm = NovelLLMService()
        for n in novels:
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
                    if ch and ch.status != "approved":
                        ch.title = f"第{no}章"
                        ch.content = content
                        ch.pending_content = ""
                        ch.pending_revision_prompt = ""
                        ch.status = "pending_review"
                        ch.source = "daily_job"
                    else:
                        ch = Chapter(
                            novel_id=n.id,
                            chapter_no=no,
                            title=f"第{no}章",
                            content=content,
                            status="pending_review",
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
    llm = NovelLLMService()
    try:
        novels = db.query(Novel).filter(Novel.framework_confirmed.is_(True)).all()
        for n in novels:
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
        llm = NovelLLMService()
        result = llm.refresh_memory_from_chapters_sync(n, summary, prev, db=db)
        if not result.get("ok"):
            _append_refresh_log(
                db,
                novel_id=novel_id,
                batch_id=bid,
                event="memory_refresh_validation_failed",
                level="error",
                message="后台记忆刷新被校验拦截，未覆盖当前记忆",
                meta={
                    "errors": result.get("errors") or [],
                    "batch": result.get("batch"),
                },
            )
            db.commit()
            return {"status": "validation_failed", "novel_id": novel_id}
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
        llm = NovelLLMService()
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
