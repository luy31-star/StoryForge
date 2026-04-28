"""
批量章节生成（同步）：供 Celery worker 调用，与原先 HTTP 内联逻辑一致。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Chapter, Novel, NovelGenerationLog, NovelMemory
from app.models.novel_memory_runtime import NovelMemoryUpdateRun
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
from app.services.novel_judge_service import run_chapter_judge_suite
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_memory_diff_service import build_memory_diff
from app.services.novel_memory_update_service import (
    build_memory_update_run_from_result,
    create_memory_update_run,
    set_memory_update_run_assets_status,
    touch_memory_update_run,
)
from app.services.novel_repo import (
    chapter_content_metrics,
    format_continuity_excerpts,
    format_previous_chapter_fulltext,
    latest_memory_json,
)
from app.services.novel_retrieval_service import (
    is_novel_rag_enabled,
    is_novel_story_bible_enabled,
)
from app.services.novel_workflow_service import get_workflow_run_by_batch_id
from app.services.task_cancel import is_cancel_requested

logger = logging.getLogger(__name__)


def _chapter_saved_nos_for_batch(
    db: Session, novel_id: str, batch_id: str
) -> set[int]:
    rows = (
        db.query(NovelGenerationLog.chapter_no)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id == batch_id,
            NovelGenerationLog.event == "chapter_saved",
            NovelGenerationLog.chapter_no.isnot(None),
        )
        .all()
    )
    return {int(r[0]) for r in rows if r[0] is not None}


def _batch_has_terminal_stops(
    db: Session, novel_id: str, batch_id: str, events: frozenset[str]
) -> bool:
    return (
        db.query(NovelGenerationLog.id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id == batch_id,
            NovelGenerationLog.event.in_(list(events)),
        )
        .first()
    ) is not None


# 一旦在任一章上因可恢复/需人工作为的终态出现，不应在“无任务在跑”时再被误判为宕机续跑
_STALE_REQUEUE_FORBIDDEN: frozenset[str] = frozenset(
    {
        "batch_done",
        "batch_failed",
        "batch_blocked",
        "batch_cancelled",
        "chapter_generation_enqueue_failed",
        "chapter_failed",
        "chapter_memory_delta_failed",
    }
)


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
    auto_expressive_enhance: bool | None,
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
    do_expressive_enhance = (
        bool(getattr(n, "auto_expressive_enhance", False))
        if auto_expressive_enhance is None
        else bool(auto_expressive_enhance)
    )
    started = time.perf_counter()
    original_plan = list(chapter_nos)

    if _batch_has_terminal_stops(db, novel_id, batch_id, frozenset({"batch_done"})):
        return {
            "status": "ok",
            "chapter_ids": [],
            "batch_id": batch_id,
            "already_done": True,
        }

    err_like = _STALE_REQUEUE_FORBIDDEN - {"batch_done"}
    if _batch_has_terminal_stops(db, novel_id, batch_id, err_like):
        raise ValueError("该批次已因错误或已取消中断，请重新发起生成")

    saved_nos = _chapter_saved_nos_for_batch(db, novel_id, batch_id)
    pending = [no for no in original_plan if no not in saved_nos]
    batch_start_exists = _batch_has_terminal_stops(
        db, novel_id, batch_id, frozenset({"batch_start"})
    )

    if not pending:
        if batch_start_exists and not _batch_has_terminal_stops(
            db, novel_id, batch_id, frozenset({"batch_done"})
        ):
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="batch_done",
                message=(
                    f"批量生成完成，共 {len(saved_nos)} 章（续跑时检测到已全部落库，补齐终态）"
                ),
                meta={"elapsed_seconds": round(time.perf_counter() - started, 2)},
            )
            db.commit()
        return {
            "status": "ok",
            "chapter_ids": [],
            "batch_id": batch_id,
            "already_done": True,
        }

    chapter_nos = pending
    count = len(chapter_nos)

    logger.info(
        "generate_chapters sync start | novel_id=%s chapter_nos=%s batch_id=%s resumed=%s",
        novel_id,
        chapter_nos,
        batch_id,
        batch_start_exists,
    )
    if not batch_start_exists:
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="batch_start",
            message=(
                f"开始串行生成 {len(original_plan)} 章（章号：{', '.join(str(x) for x in original_plan)}）"
            ),
            meta={
                "count": len(original_plan),
                "chapter_nos": original_plan,
                "use_cold_recall": use_cold_recall,
                "cold_recall_items": cold_recall_items,
                "consistency_check": do_consistency_check,
                "plan_guard_check": do_plan_guard_check,
                "plan_guard_fix": do_plan_guard_fix,
                "style_polish": do_style_polish,
                "expressive_enhance": do_expressive_enhance,
            },
        )
        db.commit()
    else:
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="batch_resumed",
            level="info",
            message=(
                f"续跑：尚余 {count} 章（原计划 {len(original_plan)} 章，本批次已落库 {len(saved_nos)} 章）"
            ),
            meta={
                "original_chapter_nos": original_plan,
                "pending_chapter_nos": chapter_nos,
                "saved_count": len(saved_nos),
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

        do_expressive = do_expressive_enhance and settings.novel_expressive_enhance_enabled
        if do_expressive:
            try:
                content = llm.expressive_enhance_chapter_sync(
                    n,
                    chapter_no=no,
                    plan_title=plan.chapter_title,
                    beats=beats,
                    chapter_text=content,
                    db=db,
                )
                normalized_title, normalized_content = ensure_chapter_heading(
                    no, content, title_hint=effective_title_hint
                )
                content = normalized_content
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_expressive_enhance_done",
                    chapter_no=no,
                    message=f"第 {no} 章已完成表现力增强",
                    meta={"strength": settings.novel_expressive_enhance_strength},
                )
                db.commit()
            except Exception:
                logger.exception(
                    "generate_chapters expressive enhance failed, keep current | novel_id=%s chapter_no=%s",
                    novel_id,
                    no,
                )
                append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_expressive_enhance_failed",
                    chapter_no=no,
                    level="warning",
                    message=f"第 {no} 章表现力增强失败，已保留当前正文",
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
            memory_update_run = None
            if auto_approve:
                current_version = (
                    db.query(func.max(NovelMemory.version))
                    .filter(NovelMemory.novel_id == novel_id)
                    .scalar()
                    or 0
                )
                memory_update_run = create_memory_update_run(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    trigger_source=source,
                    source="chapter_generate_auto_approve",
                    chapter_no=no,
                    base_memory_version=int(current_version),
                    request_payload={
                        "chapter_no": no,
                        "chapter_title": normalized_title,
                        "source": source,
                    },
                )
                touch_memory_update_run(
                    db,
                    memory_update_run,
                    status="running",
                    current_stage="delta_extracting",
                    delta_status="running",
                    validation_status="pending",
                    norm_status="pending",
                    snapshot_status="pending",
                )
                memory_delta_result = llm.propose_memory_update_from_chapter_sync(
                    n,
                    chapter_no=no,
                    chapter_title=normalized_title,
                    chapter_text=content,
                    prev_memory=mem,
                    db=db,
                )
                build_memory_update_run_from_result(
                    db,
                    memory_update_run,
                    previous_payload_json=mem,
                    result=memory_delta_result,
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
                    meta={
                        **(memory_delta_result.get("stats") or {}),
                        "run_id": memory_update_run.id if memory_update_run else None,
                    },
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
            if settings.novel_judge_enabled:
                try:
                    workflow_run = get_workflow_run_by_batch_id(db, batch_id=batch_id)
                    judge_meta = run_chapter_judge_suite(
                        db,
                        novel=n,
                        chapter=ch,
                        chapter_text=content,
                        plan_title=plan.chapter_title or normalized_title,
                        beats=beats,
                        workflow_run_id=workflow_run.id if workflow_run else None,
                        trigger_source=source,
                    )
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_judge_done",
                        chapter_no=no,
                        message=(
                            f"第 {no} 章评估完成：分数 {judge_meta['score']}，"
                            f"发现 {judge_meta['issue_count']} 个问题"
                        ),
                        meta=judge_meta,
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "chapter judge failed | novel_id=%s chapter_no=%s batch_id=%s",
                        novel_id,
                        no,
                        batch_id,
                    )
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_judge_failed",
                        chapter_no=no,
                        level="warning",
                        message=f"第 {no} 章评估失败，已跳过 Judge",
                    )
                    db.commit()
            if auto_approve and memory_update_run is not None and (
                is_novel_story_bible_enabled(db, novel_id) or is_novel_rag_enabled(db, novel_id)
            ):
                try:
                    from app.tasks.novel_tasks import novel_sync_memory_derived_assets

                    task = novel_sync_memory_derived_assets.delay(
                        novel_id,
                        memory_update_run.id,
                        batch_id,
                        no,
                    )
                    task_id = getattr(task, "id", None)
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_story_assets_queued",
                        chapter_no=no,
                        message=f"第 {no} 章已转入异步同步 Story Bible / RAG",
                        meta={"run_id": memory_update_run.id, "task_id": task_id},
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    set_memory_update_run_assets_status(
                        db,
                        memory_update_run,
                        failed=True,
                        error_message="异步同步任务入队失败",
                    )
                    logger.exception(
                        "enqueue story assets after auto approve failed | novel_id=%s chapter_no=%s",
                        novel_id,
                        no,
                    )
                    append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_story_assets_enqueue_failed",
                        chapter_no=no,
                        level="warning",
                        message=f"第 {no} 章正文已保存，但 Story Bible / RAG 异步任务入队失败",
                        meta={"run_id": memory_update_run.id},
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
            if auto_approve:
                latest_run = (
                    db.query(NovelMemoryUpdateRun)
                    .filter(
                        NovelMemoryUpdateRun.novel_id == novel_id,
                        NovelMemoryUpdateRun.batch_id == batch_id,
                        NovelMemoryUpdateRun.chapter_no == no,
                    )
                    .order_by(NovelMemoryUpdateRun.created_at.desc())
                    .first()
                )
                if latest_run is not None:
                    touch_memory_update_run(
                        db,
                        latest_run,
                        status="failed",
                        current_stage="failed",
                        errors=[str(e)],
                        error_payload={"error": str(e)},
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
                meta={
                    "diff_summary": build_memory_diff(
                        mem,
                        str(memory_delta_result.get("candidate_json") or "{}"),
                    )
                    if auto_approve and memory_delta_result
                    else {},
                },
            )
            db.commit()
            raise

    total_in_batch = len(_chapter_saved_nos_for_batch(db, novel_id, batch_id))
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="batch_done",
        message=f"批量生成完成，共 {total_in_batch} 章（本段新写 {len(created)} 章）",
        meta={
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "saved_total": total_in_batch,
            "saved_this_run": len(created),
        },
    )
    db.commit()
    logger.info(
        "generate_chapters sync done | novel_id=%s pending_loop=%s created_this_run=%s batch_id=%s",
        novel_id,
        count,
        len(created),
        batch_id,
    )
    return {"chapter_ids": created, "batch_id": batch_id}
