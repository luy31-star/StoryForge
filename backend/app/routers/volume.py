from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_novel_access
from app.models.novel import Novel
from app.models.user import User
from app.models.volume import NovelChapterPlan, NovelVolume
from app.services.chapter_plan_schema import (
    merge_execution_card_patch,
    normalize_beats_to_v2,
)
from app.services.novel_generation_common import (
    append_generation_log,
    has_pending_volume_plan_batch,
)
from app.services.novel_repo import latest_memory_json
from app.services.novel_llm_service import NovelLLMService
from app.services.user_task_service import create_user_task
from app.tasks.novel_tasks import novel_volume_plan_batch_for_volume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novels/{novel_id}/volumes", tags=["novel-volumes"])


def _novel_llm(user: User) -> NovelLLMService:
    return NovelLLMService(billing_user_id=user.id)


class VolumesGenerateBody(BaseModel):
    approx_size: int = Field(default=50, ge=10, le=200)
    total_chapters: int | None = Field(default=None, ge=1, le=20000)


class VolumePatchBody(BaseModel):
    title: str | None = None
    summary: str | None = None
    from_chapter: int | None = Field(default=None, ge=1, le=20000)
    to_chapter: int | None = Field(default=None, ge=1, le=20000)
    status: str | None = None


class PlanGenerateBody(BaseModel):
    force_regen: bool = False
    # 手动推进：每次生成本卷章计划的“批次章节数”（默认读后端配置）
    batch_size: int | None = Field(default=None, ge=1, le=50)
    # 手动指定从哪一章开始生成（默认：从当前已存在计划的下一章开始；force_regen 时从卷起始章）
    from_chapter: int | None = Field(default=None, ge=1, le=20000)


def _extract_total_chapters_from_framework(framework_json: str) -> int | None:
    raw = (framework_json or "").strip()
    if not raw:
        return None
    # 兼容“第1-1500章/1500章”这类文本
    m = re.search(r"第\\s*\\d+\\s*[-~—–]\\s*(\\d+)\\s*章", raw)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    m2 = re.search(r"(\\d{2,5})\\s*章", raw)
    if m2:
        try:
            n = int(m2.group(1))
            return n if n >= 50 else None
        except Exception:
            return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # 若 arcs 最后一个 range 有上界
            arcs = data.get("arcs")
            if isinstance(arcs, list) and arcs:
                last = arcs[-1]
                if isinstance(last, dict):
                    hi = last.get("to_chapter") or last.get("to")
                    if isinstance(hi, int):
                        return hi
                    ch = last.get("chapters") or last.get("chapter_range")
                    if isinstance(ch, str):
                        m3 = re.search(r"(\\d+)\\s*[-~—–]\\s*(\\d+)", ch)
                        if m3:
                            return int(m3.group(2))
    except Exception:
        return None
    return None


def _append_volumes(
    db: Session,
    *,
    novel_id: str,
    start_volume_no: int,
    start_chapter: int,
    total_chapters: int,
    approx_size: int,
) -> int:
    added = 0
    vol_no = start_volume_no
    ch = start_chapter
    while ch <= total_chapters:
        lo = ch
        hi = min(total_chapters, ch + approx_size - 1)
        db.add(
            NovelVolume(
                novel_id=novel_id,
                volume_no=vol_no,
                title=f"第{vol_no}卷",
                summary="",
                from_chapter=lo,
                to_chapter=hi,
                status="draft",
            )
        )
        added += 1
        vol_no += 1
        ch = hi + 1
    return added


@router.post("/generate")
def generate_volumes(
    novel_id: str,
    body: VolumesGenerateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    op = uuid.uuid4().hex[:12]
    logger.info(
        "volumes.generate start | op=%s novel_id=%s approx_size=%s total_chapters=%s",
        op,
        novel_id,
        body.approx_size,
        body.total_chapters,
    )
    n = require_novel_access(db, novel_id, user)

    # 1) 计算 total_chapters：优先 body，其次框架推断，最后 target_word_count 粗略兜底
    total = body.total_chapters
    if total is None:
        tc = getattr(n, "target_chapters", None)
        if isinstance(tc, int) and tc > 0:
            total = tc
    if total is None:
        total = _extract_total_chapters_from_framework(n.framework_json or "")
    if total is None:
        total = max(1, int((getattr(n, "target_word_count", 100_000) or 100_000) // 3000))

    approx = int(body.approx_size or 50)
    # 2) 已有卷时不直接跳过，而是按目标章数补齐缺失的后续卷
    existing = (
        db.query(NovelVolume)
        .filter(NovelVolume.novel_id == novel_id)
        .order_by(NovelVolume.volume_no.asc())
        .all()
    )
    if existing:
        covered_to = max(int(v.to_chapter or 0) for v in existing)
        if covered_to >= total:
            logger.info(
                "volumes.generate skipped | op=%s novel_id=%s reason=already_covered count=%s covered_to=%s total=%s",
                op,
                novel_id,
                len(existing),
                covered_to,
                total,
            )
            return {
                "status": "skipped",
                "reason": f"现有卷列表已覆盖到第{covered_to}章",
                "count": len(existing),
                "covered_to": covered_to,
                "total_chapters": total,
                "approx_size": approx,
            }
        added = _append_volumes(
            db,
            novel_id=novel_id,
            start_volume_no=max(int(v.volume_no or 0) for v in existing) + 1,
            start_chapter=covered_to + 1,
            total_chapters=total,
            approx_size=approx,
        )
        db.commit()
        logger.info(
            "volumes.generate extended | op=%s novel_id=%s existing=%s added=%s covered_to=%s total=%s approx_size=%s",
            op,
            novel_id,
            len(existing),
            added,
            covered_to,
            total,
            approx,
        )
        return {
            "status": "extended",
            "count": len(existing) + added,
            "added": added,
            "covered_to": total,
            "total_chapters": total,
            "approx_size": approx,
        }

    added = _append_volumes(
        db,
        novel_id=novel_id,
        start_volume_no=1,
        start_chapter=1,
        total_chapters=total,
        approx_size=approx,
    )
    db.commit()
    logger.info(
        "volumes.generate done | op=%s novel_id=%s count=%s total_chapters=%s approx_size=%s",
        op,
        novel_id,
        added,
        total,
        approx,
    )
    return {"status": "ok", "count": added, "total_chapters": total, "approx_size": approx}


@router.get("")
def list_volumes(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_novel_access(db, novel_id, user)
    rows = (
        db.query(NovelVolume)
        .filter(NovelVolume.novel_id == novel_id)
        .order_by(NovelVolume.volume_no.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for v in rows:
        plan_count = (
            db.query(func.count(NovelChapterPlan.id))
            .filter(NovelChapterPlan.volume_id == v.id)
            .scalar()
            or 0
        )
        out.append(
            {
                "id": v.id,
                "volume_no": v.volume_no,
                "title": v.title,
                "summary": v.summary,
                "from_chapter": v.from_chapter,
                "to_chapter": v.to_chapter,
                "status": v.status,
                "chapter_plan_count": int(plan_count),
            }
        )
    return out


@router.patch("/{volume_id}")
def patch_volume(
    novel_id: str,
    volume_id: str,
    body: VolumePatchBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    data = body.model_dump(exclude_unset=True)
    logger.info(
        "volume.patch | novel_id=%s volume_id=%s volume_no=%s fields=%s",
        novel_id,
        volume_id,
        v.volume_no,
        list(data.keys()),
    )
    for k, val in data.items():
        if val is None:
            continue
        setattr(v, k, val)
    # 简单合法性
    if v.from_chapter <= 0 or v.to_chapter <= 0 or v.from_chapter > v.to_chapter:
        raise HTTPException(400, "from_chapter/to_chapter 范围不合法")
    db.commit()
    return {"status": "ok"}


@router.post("/{volume_id}/chapter-plan/generate")
def generate_volume_chapter_plan(
    novel_id: str,
    volume_id: str,
    body: PlanGenerateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """入队后台生成本卷一批章计划；执行逻辑在 Celery worker 中。"""
    op = uuid.uuid4().hex[:12]
    n = require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    if has_pending_volume_plan_batch(db, novel_id):
        raise HTTPException(
            409,
            "当前已有卷章计划生成任务进行中，请在「生成日志」中查看进度后再试",
        )

    if n.status == "failed":
        n.status = "active"
        db.commit()

    logger.info(
        "volume.chapter_plan.generate enqueue | op=%s novel_id=%s volume_id=%s force_regen=%s",
        op,
        novel_id,
        volume_id,
        body.force_regen,
    )
    batch_id = f"vol-plan-{int(time.time())}-{novel_id[:8]}"
    payload = {
        "force_regen": body.force_regen,
        "batch_size": body.batch_size,
        "from_chapter": body.from_chapter,
        "volume_id": volume_id,
    }
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="volume_plan_queued",
        message="已入队后台生成本卷章计划",
        meta={"volume_id": volume_id, **payload},
    )
    db.commit()
    try:
        task = novel_volume_plan_batch_for_volume.delay(
            novel_id, str(user.id), batch_id, payload
        )
        task_id = getattr(task, "id", None)
    except Exception as e:
        logger.exception("volume.chapter_plan.generate enqueue failed | novel_id=%s", novel_id)
        try:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="volume_plan_enqueue_failed",
                level="error",
                message=f"后台任务入队失败：{e}",
                meta={"error": str(e)},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(503, f"后台任务入队失败：{e}") from e
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="volume_plan_task_accepted",
        message="后台卷章计划任务已接收",
        meta={"task_id": task_id, "volume_id": volume_id},
    )
    db.commit()

    try:
        create_user_task(
            db,
            user_id=user.id,
            kind="volume_plan",
            title=f"生成本卷章计划（第{v.volume_no}卷）",
            status="queued",
            batch_id=batch_id,
            celery_task_id=str(task_id) if task_id else None,
            novel_id=novel_id,
            volume_id=volume_id,
            meta=payload,
        )
    except Exception:
        logger.exception("create user task failed | batch_id=%s", batch_id)
    return {
        "status": "queued",
        "batch_id": batch_id,
        "task_id": task_id,
        "message": "卷章计划生成已在后台执行，可在生成日志中查看进度",
    }


class ChapterPlanRegenerateBody(BaseModel):
    instruction: str = ""


class ChapterPlanPatchBody(BaseModel):
    chapter_title: str | None = None
    beats: dict[str, Any] | None = None


def _load_plan_beats(row: NovelChapterPlan | None) -> dict[str, Any]:
    if not row:
        return normalize_beats_to_v2({})
    try:
        beats = json.loads(row.beats_json or "{}")
    except Exception:
        beats = {}
    return normalize_beats_to_v2(beats)


@router.post("/{volume_id}/chapter-plan/{chapter_no}/regenerate")
async def regenerate_chapter_plan(
    novel_id: str,
    volume_id: str,
    chapter_no: int,
    body: ChapterPlanRegenerateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """单章重生成"""
    n = require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")

    # 获取本章旧计划（用于 check 权限或状态）
    old = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.volume_id == volume_id,
            NovelChapterPlan.chapter_no == chapter_no,
        )
        .first()
    )
    if old and old.status == "locked":
        raise HTTPException(400, "该章节计划已锁定，无法重生成")

    # 获取前后各 2 章作为参考
    prev_rows = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.volume_id == volume_id,
            NovelChapterPlan.chapter_no < chapter_no,
        )
        .order_by(NovelChapterPlan.chapter_no.desc())
        .limit(2)
        .all()
    )
    prev_rows = prev_rows[::-1]  # 转回正序
    
    next_rows = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.volume_id == volume_id,
            NovelChapterPlan.chapter_no > chapter_no,
        )
        .order_by(NovelChapterPlan.chapter_no.asc())
        .limit(2)
        .all()
    )

    def row_to_dict(r):
        beats = _load_plan_beats(r)
        return {
            "chapter_no": r.chapter_no,
            "title": r.chapter_title,
            "beats": beats,
        }

    llm = _novel_llm(user)
    mem = latest_memory_json(db, novel_id)

    new_data = await llm.regenerate_single_chapter_plan(
        n,
        volume_no=v.volume_no,
        volume_title=v.title,
        chapter_no=chapter_no,
        memory_json=mem,
        prev_chapters=[row_to_dict(r) for r in prev_rows],
        next_chapters=[row_to_dict(r) for r in next_rows],
        user_instruction=body.instruction,
        db=db,
    )

    # 落库更新
    title = new_data.get("title") or f"第{chapter_no}章"
    beats = normalize_beats_to_v2(new_data.get("beats") or {})
    added = new_data.get("open_plots_intent_added") or []
    resolved = new_data.get("open_plots_intent_resolved") or []

    if old:
        old.chapter_title = title[:512]
        old.beats_json = json.dumps(beats, ensure_ascii=False)
        old.open_plots_intent_added_json = json.dumps(added, ensure_ascii=False)
        old.open_plots_intent_resolved_json = json.dumps(resolved, ensure_ascii=False)
        old.status = "planned"
    else:
        # 如果原来没计划（虽然 UI 上通常不会），则新建
        old = NovelChapterPlan(
            novel_id=novel_id,
            volume_id=volume_id,
            chapter_no=chapter_no,
            chapter_title=title[:512],
            beats_json=json.dumps(beats, ensure_ascii=False),
            open_plots_intent_added_json=json.dumps(added, ensure_ascii=False),
            open_plots_intent_resolved_json=json.dumps(resolved, ensure_ascii=False),
            status="planned",
        )
        db.add(old)
    
    db.commit()
    return {"status": "ok", "chapter_no": chapter_no, "title": title}


@router.patch("/{volume_id}/chapter-plan/{chapter_no}")
def patch_chapter_plan(
    novel_id: str,
    volume_id: str,
    chapter_no: int,
    body: ChapterPlanPatchBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    row = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.volume_id == volume_id,
            NovelChapterPlan.chapter_no == chapter_no,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "章计划不存在")
    if row.status == "locked":
        raise HTTPException(400, "该章节计划已锁定，无法编辑执行卡")

    changed = False
    if body.chapter_title is not None:
        row.chapter_title = (body.chapter_title.strip() or f"第{chapter_no}章")[:512]
        changed = True
    if body.beats is not None:
        merged = merge_execution_card_patch(
            _load_plan_beats(row),
            body.beats,
            editor_id=str(user.id) if getattr(user, "id", None) else None,
        )
        row.beats_json = json.dumps(merged, ensure_ascii=False)
        changed = True

    if not changed:
        return {
            "status": "ok",
            "chapter_no": chapter_no,
            "chapter_title": row.chapter_title,
            "beats": _load_plan_beats(row),
        }

    if row.status == "revised":
        row.status = "planned"
    db.commit()
    db.refresh(row)
    return {
        "status": "ok",
        "chapter_no": chapter_no,
        "chapter_title": row.chapter_title,
        "beats": _load_plan_beats(row),
    }


@router.delete("/{volume_id}/chapter-plan")
def clear_volume_chapter_plans(
    novel_id: str,
    volume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    一键清除本卷未锁定的章计划（locked 保留）。
    用于计划跑偏后重置，再分批重新生成。
    """
    require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    deleted = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.volume_id == volume_id,
            NovelChapterPlan.status != "locked",
        )
        .delete(synchronize_session=False)
    )
    if v.status == "planned":
        v.status = "draft"
    db.commit()
    logger.info(
        "volume.chapter_plan.cleared | novel_id=%s volume_id=%s deleted=%s",
        novel_id,
        volume_id,
        deleted,
    )
    return {"status": "ok", "deleted": int(deleted or 0)}


@router.get("/{volume_id}/chapter-plan")
def list_volume_chapter_plan(
    novel_id: str,
    volume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    rows = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == volume_id)
        .order_by(NovelChapterPlan.chapter_no.asc())
        .all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        beats = _load_plan_beats(r)
        out.append(
            {
                "id": r.id,
                "chapter_no": r.chapter_no,
                "chapter_title": r.chapter_title,
                "beats": beats,
                "status": r.status,
            }
        )
    return out


@router.post("/{volume_id}/chapter-plan/lock")
def lock_volume_chapter_plan(
    novel_id: str,
    volume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    rows = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == volume_id)
        .all()
    )
    logger.info(
        "volume.chapter_plan.lock | novel_id=%s volume_id=%s volume_no=%s plan_rows=%s",
        novel_id,
        volume_id,
        v.volume_no,
        len(rows),
    )
    for r in rows:
        r.status = "locked"
    v.status = "locked"
    db.commit()
    return {"status": "ok", "count": len(rows)}
