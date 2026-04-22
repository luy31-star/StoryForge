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
from app.services.chapter_approval_guard import collect_chapter_approval_issues
from app.services.chapter_plan_schema import normalize_beats_to_v2
from app.services.novel_generation_common import (
    append_generation_log,
    build_chapter_plan_hint,
    build_future_plan_summary,
    build_multi_chapter_plan_hint,
    ensure_chapter_heading,
)
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_repo import (
    chapter_content_metrics,
    format_continuity_excerpts,
    format_previous_chapter_fulltext,
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
    auto_plan_guard_check: bool,
    auto_plan_guard_fix: bool,
    auto_style_polish: bool,
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
    do_plan_guard_fix = bool(auto_plan_guard_fix)
    do_plan_guard_check = bool(auto_plan_guard_check or do_plan_guard_fix)
    do_style_polish = bool(auto_style_polish)
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
            "plan_guard_check": do_plan_guard_check,
            "plan_guard_fix": do_plan_guard_fix,
            "style_polish": do_style_polish,
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
        full_context = format_previous_chapter_fulltext(db, novel_id)
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

        # 查询后续章计划摘要（最多9章）
        future_plans: list[dict[str, Any]] = []
        future_rows = (
            db.query(NovelChapterPlan)
            .filter(
                NovelChapterPlan.novel_id == novel_id,
                NovelChapterPlan.chapter_no > no,
            )
            .order_by(NovelChapterPlan.chapter_no.asc())
            .limit(9)
            .all()
        )
        for fp in future_rows:
            try:
                fp_beats = json.loads(fp.beats_json or "{}")
            except Exception:
                fp_beats = {}
            fp_beats = normalize_beats_to_v2(fp_beats)
            summary = build_future_plan_summary(
                fp.chapter_no, fp.chapter_title, fp_beats
            )
            future_plans.append({"summary": summary})

        chapter_plan_hint = build_multi_chapter_plan_hint(
            chapter_plan_hint, future_plans
        )
        effective_title_hint = (plan.chapter_title or title_hint or "").strip()
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
            effective_title_hint,
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
            no, content, title_hint=effective_title_hint
        )
        content = normalized_content

        if do_plan_guard_check:
            plan_audit = llm.audit_chapter_against_plan_sync(
                chapter_no=no,
                plan_title=plan.chapter_title,
                beats=beats,
                chapter_text=content,
                db=db,
            )
            if not plan_audit.get("ok"):
                violations = plan_audit.get("violations") or []
                if do_plan_guard_fix:
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_plan_guard_failed",
                        chapter_no=no,
                        level="warning",
                        message=f"第 {no} 章未通过执行卡校验，开始自动纠偏",
                        meta={
                            "violations": violations,
                            "warnings": plan_audit.get("warnings") or [],
                        },
                    )
                    db.commit()
                    content = llm.fix_chapter_to_plan_sync(
                        n,
                        chapter_no=no,
                        plan_title=plan.chapter_title,
                        beats=beats,
                        memory_json=mem,
                        continuity_excerpt=continuity,
                        chapter_text=content,
                        violations=violations,
                        db=db,
                    )
                    normalized_title, normalized_content = ensure_chapter_heading(
                        no, content, title_hint=effective_title_hint
                    )
                    content = normalized_content
                    re_audit = llm.audit_chapter_against_plan_sync(
                        chapter_no=no,
                        plan_title=plan.chapter_title,
                        beats=beats,
                        chapter_text=content,
                        db=db,
                    )
                    if not re_audit.get("ok"):
                        raise RuntimeError(
                            "执行卡校验仍未通过："
                            + "；".join(re_audit.get("violations") or [])[:1000]
                        )
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_plan_guard_fixed",
                        chapter_no=no,
                        message=f"第 {no} 章已按执行卡完成自动纠偏",
                        meta={"warnings": re_audit.get("warnings") or []},
                    )
                    db.commit()
                else:
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_plan_guard_failed",
                        chapter_no=no,
                        level="error",
                        message=f"第 {no} 章未通过执行卡硬校验，已停止当前批次",
                        meta={
                            "violations": violations,
                            "warnings": plan_audit.get("warnings") or [],
                        },
                    )
                    db.commit()
                    raise RuntimeError(
                        "执行卡硬校验未通过："
                        + "；".join(str(x).strip() for x in violations if str(x).strip())[:1000]
                    )
            elif plan_audit.get("warnings"):
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_plan_guard_warn",
                    chapter_no=no,
                    level="info",
                    message=f"第 {no} 章通过执行卡硬校验，但存在可优化项",
                    meta={"warnings": plan_audit.get("warnings") or []},
                )
                db.commit()

        if do_style_polish:
            pre_polish_metrics = chapter_content_metrics(content)
            pre_polish_body_chars = int(pre_polish_metrics.get("body_chars", 0) or 0)
            try:
                polished = llm.polish_chapter_style_sync(
                    n,
                    chapter_no=no,
                    plan_title=plan.chapter_title,
                    beats=beats,
                    chapter_text=content,
                    db=db,
                )
                normalized_title, normalized_content = ensure_chapter_heading(
                    no, polished, title_hint=effective_title_hint
                )
                polished_metrics = chapter_content_metrics(normalized_content)
                polished_body_chars = int(polished_metrics.get("body_chars", 0) or 0)
                content = normalized_content
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_style_polish_done",
                    chapter_no=no,
                    message=f"第 {no} 章已完成去 AI 味润色",
                    meta={
                        "body_chars": polished_body_chars,
                        "reduced_body_chars": max(0, pre_polish_body_chars - polished_body_chars),
                    },
                )
                db.commit()
            except Exception:
                logger.exception(
                    "generate_chapters style polish failed, fallback original | novel_id=%s chapter_no=%s",
                    novel_id,
                    no,
                )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_style_polish_failed",
                    chapter_no=no,
                    level="warning",
                    message=f"第 {no} 章去 AI 味润色失败，已保留当前正文",
                )
                db.commit()

        # 一键续写默认直接自动审定并同步工作记忆；
        # 但若用户显式开启了执行卡校验/纠偏，则允许校验链路拦截。
        force_auto_approve = source == "auto_pipeline" and not do_plan_guard_check
        auto_approve_requested = force_auto_approve or source != "manual"
        auto_approval_issues: list[str] = []
        if auto_approve_requested and not force_auto_approve:
            auto_approval_issues = collect_chapter_approval_issues(
                novel=n,
                chapter_no=no,
                chapter_text=content,
                llm=llm,
                db=db,
                plan=plan,
                include_plan_audit=False,
            )
            if auto_approval_issues:
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_auto_approve_blocked",
                    chapter_no=no,
                    level="warning",
                    message=f"第 {no} 章未通过自动审定门禁，已转为待审定",
                    meta={"issues": auto_approval_issues},
                )
                db.commit()
        auto_approve = force_auto_approve or (
            auto_approve_requested and not auto_approval_issues
        )
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
            if auto_approval_issues:
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="batch_blocked",
                    chapter_no=no,
                    level="warning",
                    message=f"第 {no} 章未通过自动审定门禁，已停止后续生成",
                    meta={
                        "chapter_id": ch.id,
                        "issues": auto_approval_issues,
                    },
                )
                db.commit()
                return {
                    "status": "blocked",
                    "chapter_ids": created,
                    "batch_id": batch_id,
                    "blocked_chapter_no": no,
                    "blocked_issues": auto_approval_issues,
                }
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
