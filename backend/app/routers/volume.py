from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.novel import Novel
from app.models.volume import NovelChapterPlan, NovelVolume
from app.services.novel_repo import latest_memory_json
from app.services.novel_llm_service import NovelLLMService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novels/{novel_id}/volumes", tags=["novel-volumes"])


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


@router.post("/generate")
def generate_volumes(
    novel_id: str, body: VolumesGenerateBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    op = uuid.uuid4().hex[:12]
    logger.info(
        "volumes.generate start | op=%s novel_id=%s approx_size=%s total_chapters=%s",
        op,
        novel_id,
        body.approx_size,
        body.total_chapters,
    )
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")

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
    # 2) 清理旧 volumes（仅当还没写任何计划时可安全重建；这里先“保守策略”：如果已有 volume 直接返回）
    existing = (
        db.query(NovelVolume)
        .filter(NovelVolume.novel_id == novel_id)
        .order_by(NovelVolume.volume_no.asc())
        .all()
    )
    if existing:
        logger.info(
            "volumes.generate skipped | op=%s novel_id=%s reason=volumes_already_exist count=%s",
            op,
            novel_id,
            len(existing),
        )
        return {"status": "skipped", "reason": "volumes 已存在", "count": len(existing)}

    vol_no = 1
    ch = 1
    while ch <= total:
        lo = ch
        hi = min(total, ch + approx - 1)
        v = NovelVolume(
            novel_id=novel_id,
            volume_no=vol_no,
            title=f"第{vol_no}卷",
            summary="",
            from_chapter=lo,
            to_chapter=hi,
            status="draft",
        )
        db.add(v)
        vol_no += 1
        ch = hi + 1
    db.commit()
    logger.info(
        "volumes.generate done | op=%s novel_id=%s count=%s total_chapters=%s approx_size=%s",
        op,
        novel_id,
        vol_no - 1,
        total,
        approx,
    )
    return {"status": "ok", "count": vol_no - 1, "total_chapters": total, "approx_size": approx}


@router.get("")
def list_volumes(novel_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
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
) -> dict[str, str]:
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


def _parse_plan_json(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}

    # 1) 直接 parse
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return {"chapters": data}
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2) 优先提取 ```json ...``` 代码块
    m = re.search(r"```(?:json)?\\s*([\\s\\S]*?)```", s, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip()
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return {"chapters": data}
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3) 容错：提取首个 { ... } 或最后一个 { ... } 片段尝试
    first = s.find("{")
    last = s.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = s[first : last + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return {"chapters": data}
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    m2 = re.search(r"\\{[\\s\\S]*\\}$", s)
    if m2:
        try:
            data = json.loads(m2.group(0))
            if isinstance(data, list):
                return {"chapters": data}
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return {}

def _build_prev_batch_context_from_db(
    db: Session,
    *,
    volume_id: str,
) -> str:
    """
    从已落库的章计划中构建“上一批次衔接上下文”。
    只取最后 2 章的 beats(plot_summary/hook) + open_plots 意图，供下一批计划承接。
    """
    rows = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == volume_id)
        .order_by(NovelChapterPlan.chapter_no.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return ""
    rows = list(reversed(rows))  # 按章节号升序拼接
    parts: list[str] = []
    active_plots: set[str] = set()
    for r in rows:
        try:
            beats = json.loads(r.beats_json or "{}")
        except Exception:
            beats = {}
        plot_summary = beats.get("plot_summary", "") if isinstance(beats, dict) else ""
        hook = beats.get("hook", "") if isinstance(beats, dict) else ""
        try:
            added = json.loads(r.open_plots_intent_added_json or "[]")
        except Exception:
            added = []
        try:
            resolved = json.loads(r.open_plots_intent_resolved_json or "[]")
        except Exception:
            resolved = []
        if isinstance(added, list):
            for x in added:
                if str(x).strip():
                    active_plots.add(str(x).strip())
        if isinstance(resolved, list):
            for x in resolved:
                if str(x).strip():
                    active_plots.discard(str(x).strip())
        parts.append(
            f"第{r.chapter_no}章《{r.chapter_title}》:\n"
            f"  剧情梗概: {(plot_summary or '（无）')[:500]}\n"
            f"  章末钩子: {(hook or '（无）')[:200]}\n"
            f"  新增线索: {json.dumps(added if isinstance(added, list) else [], ensure_ascii=False)}\n"
            f"  解决线索: {json.dumps(resolved if isinstance(resolved, list) else [], ensure_ascii=False)}\n"
        )
    summary = "\n".join(parts)
    if active_plots:
        summary += (
            "\n当前已生成计划遗留的活跃线索（后续需承接或解决）:\n"
            + json.dumps(sorted(active_plots), ensure_ascii=False)
            + "\n"
        )
    return summary


@router.post("/{volume_id}/chapter-plan/generate")
async def generate_volume_chapter_plan(
    request: Request,
    novel_id: str,
    volume_id: str,
    body: PlanGenerateBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    op = uuid.uuid4().hex[:12]
    rid = (request.headers.get("x-request-id") or "").strip() or "-"
    t0 = time.perf_counter()
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise HTTPException(404, "卷不存在")
    logger.info(
        "volume.chapter_plan.generate start | op=%s request_id=%s novel_id=%s volume_id=%s "
        "force_regen=%s novel_title=%r volume_no=%s range=%s-%s",
        op,
        rid,
        novel_id,
        volume_id,
        body.force_regen,
        n.title,
        v.volume_no,
        v.from_chapter,
        v.to_chapter,
    )

    existing = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == volume_id)
        .order_by(NovelChapterPlan.chapter_no.asc())
        .all()
    )
    if existing and not body.force_regen:
        # 手动推进模式：允许多次点击，每次补齐下一批。这里不再直接 skipped。
        pass

    # 清理旧计划（force_regen）
    if existing and body.force_regen:
        logger.info(
            "volume.chapter_plan.generate clearing old plans | op=%s request_id=%s count=%s",
            op,
            rid,
            len(existing),
        )
        for x in existing:
            db.delete(x)
        db.flush()
        existing = []

    mem = latest_memory_json(db, novel_id)
    llm = NovelLLMService()
    ch_total = v.to_chapter - v.from_chapter + 1
    # 选择本次要生成的范围：默认从“下一未覆盖章”开始；force_regen/无计划则从卷起始章。
    batch_size = int(body.batch_size or settings.novel_volume_plan_batch_size or 8)
    batch_size = max(1, min(batch_size, 50))
    if body.force_regen or not existing:
        default_start = v.from_chapter
    else:
        last_no = existing[-1].chapter_no
        default_start = int(last_no) + 1
    batch_start = int(body.from_chapter or default_start)
    if batch_start < v.from_chapter:
        batch_start = v.from_chapter
    if batch_start > v.to_chapter:
        logger.info(
            "volume.chapter_plan.generate already_done | op=%s request_id=%s novel_id=%s volume_id=%s "
            "range=%s-%s existing=%s",
            op,
            rid,
            novel_id,
            volume_id,
            v.from_chapter,
            v.to_chapter,
            len(existing),
        )
        return {
            "status": "ok",
            "saved": 0,
            "done": True,
            "next_from_chapter": None,
            "existing": len(existing),
        }
    batch_end = min(batch_start + batch_size - 1, v.to_chapter)

    prev_ctx = ""
    if existing and batch_start > v.from_chapter:
        prev_ctx = _build_prev_batch_context_from_db(db, volume_id=volume_id)

    logger.info(
        "volume.chapter_plan.generate llm_call | op=%s request_id=%s novel_id=%s volume_no=%s "
        "volume_range=%s-%s volume_chapters=%s batch=%s-%s batch_size=%s mem_json_chars=%s prev_ctx_chars=%s",
        op,
        rid,
        novel_id,
        v.volume_no,
        v.from_chapter,
        v.to_chapter,
        ch_total,
        batch_start,
        batch_end,
        batch_size,
        len(mem or ""),
        len(prev_ctx or ""),
    )

    try:
        raw = await llm.generate_volume_chapter_plan_batch_json(
            n,
            volume_no=v.volume_no,
            volume_title=v.title,
            from_chapter=batch_start,
            to_chapter=batch_end,
            memory_json=mem,
            prev_batch_context=prev_ctx,
            db=db,
        )
    except RuntimeError as e:
        logger.exception(
            "volume.chapter_plan.generate llm_failed | op=%s request_id=%s novel_id=%s volume_id=%s err=%s",
            op,
            rid,
            novel_id,
            volume_id,
            e,
        )
        raise HTTPException(status_code=502, detail=str(e)) from e

    llm_elapsed = time.perf_counter() - t0
    logger.info(
        "volume.chapter_plan.generate llm_done | op=%s request_id=%s raw_chars=%s elapsed=%.2fs",
        op,
        rid,
        len(raw or ""),
        llm_elapsed,
    )

    parsed = _parse_plan_json(raw)
    chapters = parsed.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        snippet = (raw or "")[:1200]
        logger.error(
            "volume.chapter_plan.generate parse_empty | op=%s request_id=%s snippet=%r",
            op,
            rid,
            snippet[:400],
        )
        raise HTTPException(
            500,
            "LLM 未生成有效 chapters 计划（JSON 解析失败）。"
            "请检查模型输出是否包含严格 JSON。输出开头片段："
            + snippet,
        )

    # 更新卷标题/摘要（若提供）
    vt = parsed.get("volume_title")
    vs = parsed.get("volume_summary")
    if isinstance(vt, str) and vt.strip():
        v.title = vt.strip()[:512]
    if isinstance(vs, str) and vs.strip():
        v.summary = vs.strip()
    v.status = "planned"

    saved = 0
    max_cn_saved: int | None = None
    for item in chapters:
        if not isinstance(item, dict):
            continue
        cn = item.get("chapter_no")
        title = item.get("title")
        beats = item.get("beats")
        if not isinstance(cn, int):
            continue
        if cn < v.from_chapter or cn > v.to_chapter:
            continue
        if not isinstance(title, str):
            title = f"第{cn}章"
        if not isinstance(beats, dict):
            beats = {}
        added = item.get("open_plots_intent_added")
        resolved = item.get("open_plots_intent_resolved")
        added_list = [str(x).strip() for x in (added or []) if str(x).strip()] if isinstance(added, list) else []
        resolved_list = [str(x).strip() for x in (resolved or []) if str(x).strip()] if isinstance(resolved, list) else []
        if len(resolved_list) > 1:
            resolved_list = resolved_list[:1]
        row = NovelChapterPlan(
            novel_id=novel_id,
            volume_id=volume_id,
            chapter_no=cn,
            chapter_title=title.strip()[:512],
            beats_json=json.dumps(beats, ensure_ascii=False),
            open_plots_intent_added_json=json.dumps(added_list, ensure_ascii=False),
            open_plots_intent_resolved_json=json.dumps(resolved_list, ensure_ascii=False),
            status="planned",
        )
        db.add(row)
        saved += 1
        max_cn_saved = cn if max_cn_saved is None else max(max_cn_saved, cn)
    db.commit()
    total_elapsed = time.perf_counter() - t0
    expected_in_batch = batch_end - batch_start + 1
    batch_partial = saved < expected_in_batch
    if batch_partial and saved > 0:
        logger.warning(
            "volume.chapter_plan.generate partial_batch | op=%s request_id=%s novel_id=%s volume_id=%s "
            "saved=%s expected_in_batch=%s batch=%s-%s max_cn_saved=%s",
            op,
            rid,
            novel_id,
            volume_id,
            saved,
            expected_in_batch,
            batch_start,
            batch_end,
            max_cn_saved,
        )
    # 下一批起点：按实际已生成最大章号 +1，避免本批少生成时跳过中间章节
    if max_cn_saved is None:
        done = False
        next_from: int | None = batch_start
    else:
        done = max_cn_saved >= v.to_chapter
        next_from = None if done else (max_cn_saved + 1)
        if next_from is not None and next_from > v.to_chapter:
            next_from = None
            done = True
    logger.info(
        "volume.chapter_plan.generate done | op=%s request_id=%s novel_id=%s volume_id=%s "
        "saved_rows=%s parsed_chapters=%s batch=%s-%s batch_partial=%s max_cn_saved=%s done=%s next_from=%s total_elapsed=%.2fs",
        op,
        rid,
        novel_id,
        volume_id,
        saved,
        len(chapters) if isinstance(chapters, list) else 0,
        batch_start,
        batch_end,
        batch_partial,
        max_cn_saved,
        done,
        next_from,
        total_elapsed,
    )
    return {
        "status": "ok",
        "saved": saved,
        "volume_title": v.title,
        "volume_summary": v.summary[:300],
        "batch": {
            "from_chapter": batch_start,
            "to_chapter": batch_end,
            "size": batch_size,
            "requested_count": expected_in_batch,
            "saved_count": saved,
            "partial": batch_partial,
        },
        "done": done,
        "next_from_chapter": next_from,
        "existing": len(existing) + saved,
    }


class ChapterPlanRegenerateBody(BaseModel):
    instruction: str = ""


@router.post("/{volume_id}/chapter-plan/{chapter_no}/regenerate")
async def regenerate_chapter_plan(
    novel_id: str,
    volume_id: str,
    chapter_no: int,
    body: ChapterPlanRegenerateBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """单章重生成"""
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
        try:
            beats = json.loads(r.beats_json or "{}")
        except:
            beats = {}
        return {
            "chapter_no": r.chapter_no,
            "title": r.chapter_title,
            "beats": beats,
        }

    llm = NovelLLMService()
    mem = latest_memory_json(db, novel_id)
    n = db.get(Novel, novel_id)
    
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
    beats = new_data.get("beats") or {}
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


@router.delete("/{volume_id}/chapter-plan")
def clear_volume_chapter_plans(
    novel_id: str, volume_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    一键清除本卷未锁定的章计划（locked 保留）。
    用于计划跑偏后重置，再分批重新生成。
    """
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
    novel_id: str, volume_id: str, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
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
        try:
            beats = json.loads(r.beats_json or "{}")
        except Exception:
            beats = {}
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
def lock_volume_chapter_plan(novel_id: str, volume_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
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

