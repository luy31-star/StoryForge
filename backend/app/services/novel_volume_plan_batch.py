"""
卷章计划分批生成（同步）：供 Celery 与逻辑复用，与 volume 路由内联版一致。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Chapter, Novel, NovelGenerationLog
from app.models.volume import NovelChapterPlan, NovelVolume
from app.services.chapter_plan_schema import (
    chapter_plan_hook,
    chapter_plan_plot_summary,
    normalize_beats_to_v2,
)
from app.services.novel_generation_common import append_generation_log
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_repo import latest_memory_json
from app.services.task_cancel import is_cancel_requested

logger = logging.getLogger(__name__)


def _log_has_event(
    db: Session, *, novel_id: str, batch_id: str, event: str
) -> bool:
    return (
        db.query(NovelGenerationLog.id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id == batch_id,
            NovelGenerationLog.event == event,
        )
        .first()
    ) is not None


def parse_volume_plan_json(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return {"chapters": data}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
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
    m2 = re.search(r"\{[\s\S]*\}$", s)
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


def build_prev_batch_context_from_db(
    db: Session,
    *,
    volume_id: str,
) -> str:
    rows = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == volume_id)
        .order_by(NovelChapterPlan.chapter_no.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return ""
    rows = list(reversed(rows))
    parts: list[str] = []
    active_plots: set[str] = set()
    for r in rows:
        try:
            beats = json.loads(r.beats_json or "{}")
        except Exception:
            beats = {}
        beats = normalize_beats_to_v2(beats)
        plot_summary = chapter_plan_plot_summary(beats)
        hook = chapter_plan_hook(beats)
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


def _tail_excerpt_for_cross_volume_bridge(text: str, *, max_chars: int = 2200) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    head = "…（该章前半已省略）…\n"
    tail_len = max_chars - len(head)
    return head + t[-tail_len:]


def build_prev_volume_tail_context_for_plan(
    db: Session,
    *,
    novel_id: str,
    current_volume: NovelVolume,
    batch_start: int,
) -> str:
    """
    新开卷「第一批」章计划时：拼接上一卷末 1～2 章的章计划摘要 + 上一卷末章正文摘录（若有），
    供 LLM 做跨卷衔接。（仅当 batch_start 对齐本卷 from_chapter 且存在上一卷时返回非空。）
    """
    if int(batch_start) != int(current_volume.from_chapter):
        return ""
    vn = int(current_volume.volume_no or 0)
    if vn <= 1:
        return ""
    prev = (
        db.query(NovelVolume)
        .filter(
            NovelVolume.novel_id == novel_id,
            NovelVolume.volume_no == vn - 1,
        )
        .one_or_none()
    )
    if prev is None:
        return ""

    lines: list[str] = [
        f"上一卷为第{vn - 1}卷《{(prev.title or '').strip() or '（无标题）'}》，"
        f"全书章号约第{prev.from_chapter}—{prev.to_chapter}章。"
    ]

    rows = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == prev.id)
        .order_by(NovelChapterPlan.chapter_no.desc())
        .limit(2)
        .all()
    )
    rows = list(reversed(rows))
    plan_block = ""
    if rows:
        parts: list[str] = []
        active_plots: set[str] = set()
        for r in rows:
            try:
                beats = json.loads(r.beats_json or "{}")
            except Exception:
                beats = {}
            beats = normalize_beats_to_v2(beats)
            plot_summary = chapter_plan_plot_summary(beats)
            hook = chapter_plan_hook(beats)
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
                f"  剧情梗概: {(plot_summary or '（无）')[:520]}\n"
                f"  章末钩子: {(hook or '（无）')[:220]}\n"
                f"  新增线索: {json.dumps(added if isinstance(added, list) else [], ensure_ascii=False)}\n"
                f"  解决线索: {json.dumps(resolved if isinstance(resolved, list) else [], ensure_ascii=False)}\n"
            )
        plan_block = "【上一卷末 1～2 章的章计划摘要】\n" + "\n".join(parts)
        if active_plots:
            plan_block += (
                "\n上述末段在计划中遗留的活跃线索（后续须承接或解决）:\n"
                + json.dumps(sorted(active_plots), ensure_ascii=False)
                + "\n"
            )

    chap = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.chapter_no == prev.to_chapter)
        .first()
    )
    body_block = ""
    if chap is not None:
        raw = (chap.content or "").strip()
        src = "已审定正文"
        if not raw:
            raw = (chap.pending_content or "").strip()
            src = "待审定修订稿" if raw else ""
        if raw:
            ex = _tail_excerpt_for_cross_volume_bridge(raw, max_chars=2200)
            body_block = (
                f"【上一卷末章正文摘录】全书第{prev.to_chapter}章（来源：{src}；为便于衔接取章末若干字，勿复述原文）\n"
                f"{ex}\n"
            )
        else:
            body_block = (
                f"【上一卷末章】全书第{prev.to_chapter}章尚无正文，请仅依据章计划与结构化记忆衔接。\n"
            )
    else:
        body_block = (
            f"【上一卷末章】全书第{prev.to_chapter}章尚无正文记录。\n"
        )

    has_plan = bool(rows)
    has_body = chap is not None and bool(
        (getattr(chap, "content", None) or "").strip()
        or (getattr(chap, "pending_content", None) or "").strip()
    )
    if not has_plan and not has_body:
        return ""

    out = "\n".join(lines) + "\n\n" + (plan_block + "\n\n" if plan_block else "") + body_block
    return out.strip()


def run_volume_chapter_plan_batch_sync(
    db: Session,
    *,
    novel_id: str,
    billing_user_id: str | None,
    volume_id: str,
    batch_id: str,
    force_regen: bool,
    batch_size: int | None,
    from_chapter: int | None,
) -> dict[str, Any]:
    """
    执行与 POST .../chapter-plan/generate 相同的单批卷章计划生成（同步 LLM）。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise ValueError("小说不存在")
    v = db.get(NovelVolume, volume_id)
    if not v or v.novel_id != novel_id:
        raise ValueError("卷不存在")

    t0 = time.perf_counter()
    existing = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.volume_id == volume_id)
        .order_by(NovelChapterPlan.chapter_no.asc())
        .all()
    )
    if existing and force_regen:
        for x in existing:
            db.delete(x)
        db.flush()
        existing = []

    bs = int(batch_size or settings.novel_volume_plan_batch_size or 8)
    bs = max(1, min(bs, 50))
    if force_regen or not existing:
        default_start = v.from_chapter
    else:
        last_no = existing[-1].chapter_no
        default_start = int(last_no) + 1
    batch_start = int(from_chapter or default_start)
    if batch_start < v.from_chapter:
        batch_start = v.from_chapter
    if batch_start > v.to_chapter:
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="volume_plan_done",
            message="本卷章计划已全部生成，无需新批次",
            meta={"volume_id": volume_id, "saved": 0, "done": True},
        )
        db.commit()
        return {
            "status": "ok",
            "saved": 0,
            "done": True,
            "next_from_chapter": None,
            "existing": len(existing),
        }

    if _log_has_event(
        db, novel_id=novel_id, batch_id=batch_id, event="volume_plan_started"
    ) and not _log_has_event(
        db, novel_id=novel_id, batch_id=batch_id, event="volume_plan_done"
    ):
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="volume_plan_resumed",
            level="info",
            message="续跑：上次中断后继续生成本批次卷章计划",
            meta={"volume_id": volume_id, "volume_no": v.volume_no},
        )
    else:
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="volume_plan_started",
            message="后台开始生成本批次卷章计划",
            meta={"volume_id": volume_id, "volume_no": v.volume_no},
        )
    db.commit()

    if is_cancel_requested(batch_id):
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="volume_plan_cancelled",
            level="warning",
            message="任务已取消",
            meta={"volume_id": volume_id},
        )
        db.commit()
        return {"status": "cancelled", "saved": 0, "done": False, "batch_id": batch_id}

    mem = latest_memory_json(db, novel_id)
    llm = NovelLLMService(billing_user_id=billing_user_id)
    batch_end = min(batch_start + bs - 1, v.to_chapter)
    prev_ctx = ""
    if existing and batch_start > v.from_chapter:
        prev_ctx = build_prev_batch_context_from_db(db, volume_id=volume_id)

    cross_vol_ctx = ""
    if batch_start == v.from_chapter and int(v.volume_no or 0) > 1:
        cross_vol_ctx = build_prev_volume_tail_context_for_plan(
            db,
            novel_id=novel_id,
            current_volume=v,
            batch_start=batch_start,
        )

    logger.info(
        "volume_plan batch sync llm | novel_id=%s volume_id=%s batch=%s-%s mem_chars=%s prev_ctx_chars=%s cross_vol_chars=%s",
        novel_id,
        volume_id,
        batch_start,
        batch_end,
        len(mem or ""),
        len(prev_ctx or ""),
        len(cross_vol_ctx or ""),
    )

    raw = llm.generate_volume_chapter_plan_batch_json_sync(
        n,
        volume_no=v.volume_no,
        volume_title=v.title,
        from_chapter=batch_start,
        to_chapter=batch_end,
        memory_json=mem,
        prev_batch_context=prev_ctx,
        cross_volume_tail_context=cross_vol_ctx,
        db=db,
    )

    parsed = parse_volume_plan_json(raw)
    chapters = parsed.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        snippet = (raw or "")[:1200]
        raise ValueError(
            "LLM 未生成有效 chapters 计划（JSON 解析失败）。输出开头片段："
            + snippet[:400]
        )

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
        beats = normalize_beats_to_v2(beats)
        added = item.get("open_plots_intent_added")
        resolved = item.get("open_plots_intent_resolved")
        added_list = (
            [str(x).strip() for x in (added or []) if str(x).strip()]
            if isinstance(added, list)
            else []
        )
        resolved_list = (
            [str(x).strip() for x in (resolved or []) if str(x).strip()]
            if isinstance(resolved, list)
            else []
        )
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

    db.flush()
    expected_in_batch = batch_end - batch_start + 1
    batch_partial = saved < expected_in_batch
    if max_cn_saved is None:
        done = False
        next_from: int | None = batch_start
    else:
        done = max_cn_saved >= v.to_chapter
        next_from = None if done else (max_cn_saved + 1)
        if next_from is not None and next_from > v.to_chapter:
            next_from = None
            done = True

    total_elapsed = time.perf_counter() - t0
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="volume_plan_done",
        message=f"本批次卷章计划已落库（保存 {saved} 章）",
        meta={
            "volume_id": volume_id,
            "saved": saved,
            "batch_from": batch_start,
            "batch_to": batch_end,
            "partial": batch_partial,
            "done": done,
            "next_from_chapter": next_from,
            "elapsed_s": round(total_elapsed, 2),
        },
    )
    db.commit()

    return {
        "status": "ok",
        "saved": saved,
        "volume_title": v.title,
        "volume_summary": v.summary[:300],
        "batch": {
            "from_chapter": batch_start,
            "to_chapter": batch_end,
            "size": bs,
            "requested_count": expected_in_batch,
            "saved_count": saved,
            "partial": batch_partial,
        },
        "done": done,
        "next_from_chapter": next_from,
        "existing": len(existing) + saved,
    }
