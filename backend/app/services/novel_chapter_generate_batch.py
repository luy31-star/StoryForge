"""
批量章节生成（同步）：供 Celery worker 调用，与原先 HTTP 内联逻辑一致。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Chapter, Novel
from app.models.volume import NovelChapterPlan
from app.services.chapter_plan_schema import normalize_beats_to_v2
from app.services.novel_generation_common import (
    append_generation_log,
    build_chapter_plan_hint,
    ensure_chapter_heading,
)
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_repo import (
    chapter_content_metrics,
    format_continuity_excerpts,
    format_recent_approved_fulltext_context,
    latest_memory_json,
)
from app.services.task_cancel import is_cancel_requested

logger = logging.getLogger(__name__)


def run_generate_chapters_batch_sync(
    db: Session,
    *,
    novel_id: str,
    billing_user_id: str | None,
    title_hint: str,
    chapter_nos: list[int],
    use_cold_recall: bool,
    cold_recall_items: int,
    auto_consistency_check: bool,
    batch_id: str,
    source: str = "batch_auto",
) -> dict[str, Any]:
    """
    按给定章号列表串行生成（须每章在章计划中已有条目），与 POST /chapters/generate 一致。
    返回 chapter_ids、batch_id；异常时由调用方记录 batch_failed。
    """
    if not chapter_nos:
        raise ValueError("chapter_nos 不能为空")
    n = db.get(Novel, novel_id)
    if not n:
        raise ValueError("小说不存在")
    if not n.framework_confirmed:
        raise ValueError("请先确认小说框架后再生成章节")

    llm = NovelLLMService(billing_user_id=billing_user_id)
    mem = latest_memory_json(db, novel_id)
    created: list[str] = []
    do_consistency_check = bool(auto_consistency_check)
    started = time.perf_counter()
    count = len(chapter_nos)

    logger.info(
        "generate_chapters sync start | novel_id=%s chapter_nos=%s batch_id=%s",
        novel_id,
        chapter_nos,
        batch_id,
    )
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="batch_start",
        message=f"开始串行生成 {count} 章（章号：{', '.join(str(x) for x in chapter_nos)}）",
        meta={
            "count": count,
            "chapter_nos": chapter_nos,
            "use_cold_recall": use_cold_recall,
            "cold_recall_items": cold_recall_items,
            "consistency_check": do_consistency_check,
        },
    )
    db.commit()

    if is_cancel_requested(batch_id):
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="batch_cancelled",
            level="warning",
            message="任务已取消",
        )
        db.commit()
        return {"status": "cancelled", "chapter_ids": [], "batch_id": batch_id}

    for idx, no in enumerate(chapter_nos):
        if is_cancel_requested(batch_id):
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="batch_cancelled",
                level="warning",
                message="任务已取消",
                meta={"created": len(created), "stopped_at": no},
            )
            db.commit()
            return {
                "status": "cancelled",
                "chapter_ids": created,
                "batch_id": batch_id,
            }
        step_start = time.perf_counter()
        continuity = format_continuity_excerpts(db, novel_id, approved_only=True)
        full_context = format_recent_approved_fulltext_context(
            db,
            novel_id,
            max_chapters=max(1, settings.novel_recent_full_context_chapters),
        )
        plan = (
            db.query(NovelChapterPlan)
            .filter(NovelChapterPlan.novel_id == novel_id, NovelChapterPlan.chapter_no == no)
            .order_by(NovelChapterPlan.updated_at.desc())
            .first()
        )
        if not plan:
            raise ValueError(f"第 {no} 章缺少章计划，无法生成正文")
        try:
            beats = json.loads(plan.beats_json or "{}")
        except Exception:
            beats = {}
        beats = normalize_beats_to_v2(beats)
        try:
            added = json.loads(plan.open_plots_intent_added_json or "[]")
        except Exception:
            added = []
        try:
            resolved = json.loads(plan.open_plots_intent_resolved_json or "[]")
        except Exception:
            resolved = []
        chapter_plan_hint = build_chapter_plan_hint(
            no, plan.chapter_title, beats, added, resolved
        )
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="chapter_start",
            chapter_no=no,
            message=f"第 {no} 章开始生成（{idx + 1}/{count}）",
            meta={"continuity_chars": len(continuity or "")},
        )
        db.commit()

        raw_content = llm.generate_chapter_sync(
            n,
            no,
            (plan.chapter_title if plan and plan.chapter_title else title_hint),
            mem,
            continuity,
            full_context,
            chapter_plan_hint,
            db=db,
            use_cold_recall=use_cold_recall,
            cold_recall_items=cold_recall_items,
        )
        content = raw_content
        draft_metrics = chapter_content_metrics(raw_content)
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="chapter_draft_done",
            chapter_no=no,
            message=f"第 {no} 章初稿生成完成（正文约 {draft_metrics['body_chars']} 字）",
            meta={
                "raw_chars": len(raw_content or ""),
                **draft_metrics,
            },
        )
        db.commit()

        if do_consistency_check:
            try:
                content = llm.check_and_fix_chapter_sync(
                    n, no, title_hint, mem, continuity, raw_content, db=db
                )
                fixed_metrics = chapter_content_metrics(content)
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_consistency_done",
                    chapter_no=no,
                    message=f"第 {no} 章一致性修订完成（正文约 {fixed_metrics['body_chars']} 字）",
                    meta={
                        "fixed_chars": len(content or ""),
                        **fixed_metrics,
                    },
                )
                db.commit()
            except Exception:
                logger.exception(
                    "generate_chapters step consistency failed, fallback raw | novel_id=%s chapter_no=%s",
                    novel_id,
                    no,
                )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_consistency_failed",
                    chapter_no=no,
                    level="error",
                    message=f"第 {no} 章一致性修订失败，已回退初稿",
                )
                db.commit()
                content = raw_content

        normalized_title, normalized_content = ensure_chapter_heading(
            no, content, title_hint=title_hint
        )
        content = normalized_content

        # 仅 batch_auto 或非 manual 来源才自动更新工作记忆并审定
        auto_approve = source != "manual"
        try:
            memory_delta_result: dict[str, Any] | None = None
            if auto_approve:
                memory_delta_result = llm.propose_memory_update_from_chapter_sync(
                    n,
                    chapter_no=no,
                    chapter_title=normalized_title,
                    chapter_text=content,
                    prev_memory=mem,
                    db=db,
                )
                if not memory_delta_result.get("ok"):
                    err_text = "；".join(memory_delta_result.get("errors") or []) or "未知错误"
                    raise RuntimeError(f"第 {no} 章工作记忆更新失败：{err_text}")
                mem = str(memory_delta_result.get("payload_json") or mem)

            saved_metrics = chapter_content_metrics(content)
            ch = (
                db.query(Chapter)
                .filter(Chapter.novel_id == novel_id, Chapter.chapter_no == no)
                .order_by(Chapter.updated_at.desc())
                .first()
            )
            target_status = "approved" if auto_approve else "pending_review"
            if ch:
                ch.title = normalized_title
                ch.content = content
                ch.pending_content = ""
                ch.pending_revision_prompt = ""
                ch.status = target_status
                ch.source = source
            else:
                ch = Chapter(
                    novel_id=novel_id,
                    chapter_no=no,
                    title=normalized_title,
                    content=content,
                    status=target_status,
                    source=source,
                )
                db.add(ch)
                db.flush()

            if auto_approve and memory_delta_result is not None:
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_memory_delta_applied",
                    chapter_no=no,
                    message=f"第 {no} 章工作记忆已更新",
                    meta=memory_delta_result.get("stats") or {},
                )

            created.append(ch.id)
            status_label = "已审定" if auto_approve else "待审定"
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="chapter_saved",
                chapter_no=no,
                message=f"第 {no} 章已保存（{status_label}，正文约 {saved_metrics['body_chars']} 字）",
                meta={
                    "chapter_id": ch.id,
                    **saved_metrics,
                    "elapsed_seconds": round(time.perf_counter() - step_start, 2),
                },
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception(
                "generate_chapters step failed | novel_id=%s chapter_no=%s",
                novel_id,
                no,
            )
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="chapter_memory_delta_failed" if auto_approve else "chapter_failed",
                chapter_no=no,
                level="error",
                message=(
                    f"第 {no} 章工作记忆更新失败，已停止后续生成：{e}"
                    if auto_approve
                    else f"第 {no} 章保存失败：{e}"
                ),
            )
            db.commit()
            raise

    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="batch_done",
        message=f"批量生成完成，共 {len(created)} 章",
        meta={"elapsed_seconds": round(time.perf_counter() - started, 2)},
    )
    db.commit()
    logger.info(
        "generate_chapters sync done | novel_id=%s count=%s created=%s batch_id=%s",
        novel_id,
        count,
        len(created),
        batch_id,
    )
    return {"chapter_ids": created, "batch_id": batch_id}
