"""
小说生成相关共用工具：日志、章节标题规范化、章计划提示词、并发检测。

供 HTTP 路由与 Celery 任务复用，避免逻辑分叉。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import NovelGenerationLog
from app.services.chapter_plan_schema import normalize_beats_to_v2


_CHAPTER_POLISH_STALE_GRACE = timedelta(minutes=30)


def memory_refresh_confirmation_token(
    novel_id: str, current_version: int, candidate_json: str
) -> str:
    payload = f"{novel_id}:{current_version}:{candidate_json}".encode("utf-8")
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def append_generation_log(
    db: Session,
    *,
    novel_id: str,
    batch_id: str,
    event: str,
    message: str,
    level: str = "info",
    chapter_no: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    row = NovelGenerationLog(
        novel_id=novel_id,
        batch_id=batch_id,
        level=level,
        event=event,
        chapter_no=chapter_no,
        message=message,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
    )
    db.add(row)


def extract_title_from_generated_content(chapter_no: int, content: str) -> str:
    first = (content or "").splitlines()[0].strip() if (content or "").strip() else ""
    if not first:
        return f"第{chapter_no}章"
    m = re.match(rf"^第\s*{chapter_no}\s*章\s*[《<（(]?\s*(.+?)\s*[》>）)]?\s*$", first)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m2 = re.match(r"^第\s*\d+\s*章\s*[：:\-—]?\s*(.+)$", first)
    if m2 and m2.group(1).strip():
        return m2.group(1).strip()
    return f"第{chapter_no}章"


def ensure_chapter_heading(
    chapter_no: int, content: str, *, title_hint: str = ""
) -> tuple[str, str]:
    """兜底：保证正文首行为 `第N章《章名》`，并返回可用于落库的章节标题。"""
    raw = (content or "").strip()
    title = (title_hint or "").strip() or extract_title_from_generated_content(chapter_no, raw)
    if title.startswith(f"第{chapter_no}章"):
        title = title.replace(f"第{chapter_no}章", "").strip(" 《》:：-—\t")
    if not title:
        title = f"第{chapter_no}章"
    heading = f"第{chapter_no}章《{title}》"

    if not raw:
        return title, f"{heading}\n\n（本章内容为空，待补写）"

    first_line = raw.splitlines()[0].strip()
    has_heading = bool(
        re.match(rf"^第\s*{chapter_no}\s*章", first_line)
        and ("《" in first_line or "章" in first_line)
    )
    if has_heading:
        body = "\n".join(raw.splitlines()[1:]).strip()
        return title, (f"{heading}\n\n{body}" if body else heading)

    return title, f"{heading}\n\n{raw}"


def build_chapter_plan_hint(
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
    added: list[Any],
    resolved: list[Any],
) -> str:
    """
    构建「执行清单」格式的章节计划提示词。

    将原本自由的 plot_summary 转化为结构化的场景清单（如有），
    并明确每个章节的执行检查点，确保 LLM 按步骤完成而非跳过。
    """
    _ = chapter_no  # 保留参数与路由层一致
    normalized = normalize_beats_to_v2(beats)
    meta = normalized.get("meta", {}) if isinstance(normalized, dict) else {}
    summary = (
        normalized.get("display_summary", {}) if isinstance(normalized, dict) else {}
    )
    card = (
        normalized.get("execution_card", {}) if isinstance(normalized, dict) else {}
    )

    lines: list[str] = [
        "【本章执行清单（逐项勾选，禁止跳过）】",
        f"计划章名：{plan_title}",
        "",
        "=== 执行检查点（完成后勾选） ===",
    ]

    if meta.get("edited_by_user"):
        lines.append("[ ] 该执行卡已被用户手动编辑，优先按执行卡写作，不得自行改意图")

    goal = card.get("chapter_goal", "")
    conflict = card.get("core_conflict", "")
    turn = card.get("key_turn", "")
    hook = card.get("ending_hook", "")

    if isinstance(goal, str) and goal.strip():
        lines.append(f"[ ] 开局目标：{goal.strip()}")
    if isinstance(conflict, str) and conflict.strip():
        lines.append(f"[ ] 核心冲突：{conflict.strip()}")
    if isinstance(turn, str) and turn.strip():
        lines.append(f"[ ] 情节转折：{turn.strip()}")
    if isinstance(hook, str) and hook.strip():
        lines.append(f"[ ] 结尾钩子：{hook.strip()}")

    must_happen = card.get("must_happen")
    if isinstance(must_happen, list) and must_happen:
        bullets = "\n".join(f"  [ ] 必须发生：{str(x).strip()}" for x in must_happen if str(x).strip())
        if bullets:
            lines.append(bullets)

    callbacks = card.get("required_callbacks")
    if isinstance(callbacks, list) and callbacks:
        bullets = "\n".join(f"  [ ] 必须承接：{str(x).strip()}" for x in callbacks if str(x).strip())
        if bullets:
            lines.append(bullets)

    lines.append("")

    if isinstance(summary.get("stage_position"), str) and summary.get("stage_position", "").strip():
        lines.append(f"=== 本章阶段位置 ===\n{summary['stage_position'].strip()}")
    if isinstance(summary.get("pacing_justification"), str) and summary.get("pacing_justification", "").strip():
        lines.append(f"=== 节奏护栏说明 ===\n{summary['pacing_justification'].strip()}")

    ps = summary.get("plot_summary")
    scenes: list[dict[str, Any]] = []
    raw_scene_cards = card.get("scene_cards")
    if isinstance(raw_scene_cards, list):
        scenes = [s for s in raw_scene_cards if isinstance(s, dict)]
    elif isinstance(ps, list):
        scenes = [s for s in ps if isinstance(s, dict)]
    if isinstance(ps, str) and ps.strip():
        lines.append(f"=== 本章剧情梗概 ===\n{ps.strip()}")

    if scenes:
        lines.append("=== 场景分解（必须按顺序完成，每场景约500-800字） ===")
        total_words = 0
        for i, scene in enumerate(scenes, 1):
            if not isinstance(scene, dict):
                continue
            scene_goal = scene.get("goal", "")
            scene_conflict = scene.get("conflict", "")
            scene_content = scene.get("content", "")
            scene_outcome = scene.get("outcome", "")
            scene_words = scene.get("words", 600)
            if isinstance(scene_words, int) and scene_words > 0:
                total_words += scene_words
            else:
                total_words += 600

            lines.append(f"\n场景{i}:")
            if scene_goal:
                lines.append(f"  [ ] 目标：{scene_goal}")
            if scene_conflict:
                lines.append(f"  冲突：{scene_conflict}")
            if scene_content:
                lines.append(f"  内容：{scene_content}")
            if scene_outcome:
                lines.append(f"  收束：{scene_outcome}")
            lines.append(f"  建议字数：约{scene_words}字")
        lines.append(f"\n本章建议总字数：{total_words}字")

    lines.append("")

    pa = card.get("allowed_progress")
    if isinstance(pa, str) and pa.strip():
        lines.append(f"=== 进度边界·允许推进 ===\n{pa.strip()}")
    elif isinstance(pa, list) and pa:
        bullets = "\n".join(f"  · {x}" for x in pa if str(x).strip())
        if bullets:
            lines.append(f"=== 进度边界·允许推进 ===\n{bullets}")

    mn = card.get("must_not")
    if isinstance(mn, list) and mn:
        bullets = "\n".join(f"  [ ] 禁止：{x}" for x in mn if str(x).strip())
        if bullets:
            lines.append(f"\n=== 绝对禁止（违反视为不合格） ===\n{bullets}")

    rsv = card.get("reserved_for_later")
    if isinstance(rsv, list) and rsv:
        parts: list[str] = []
        for it in rsv:
            if not isinstance(it, dict):
                continue
            item = it.get("item")
            nb = it.get("not_before_chapter")
            reason = it.get("reason")
            if not (isinstance(item, str) and item.strip()):
                continue
            item_s = item.strip()
            if isinstance(nb, int):
                msg = f"  [ ] 禁写「{item_s}」——须在第{nb}章及之后才可出现"
            else:
                msg = f"  [ ] 禁写「{item_s}」——留待后续章"
            if isinstance(reason, str) and reason.strip():
                msg += f"（{reason.strip()}）"
            parts.append(msg)
        if parts:
            lines.append("\n=== 延后解锁（当前章不得写出） ===\n" + "\n".join(parts))

    end_state_targets = card.get("end_state_targets")
    if isinstance(end_state_targets, dict):
        sections: list[str] = []
        labels = {
            "characters": "角色状态",
            "relations": "关系状态",
            "items": "物品状态",
            "plots": "线索状态",
        }
        for key, label in labels.items():
            value = end_state_targets.get(key)
            if not isinstance(value, list):
                continue
            bullets = [str(x).strip() for x in value if str(x).strip()]
            if bullets:
                sections.append(f"{label}：\n" + "\n".join(f"  · {x}" for x in bullets))
        if sections:
            lines.append("\n=== 本章结束状态目标 ===\n" + "\n\n".join(sections))

    style_guardrails = card.get("style_guardrails")
    if isinstance(style_guardrails, list) and style_guardrails:
        bullets = "\n".join(f"  [ ] 风格要求：{x}" for x in style_guardrails if str(x).strip())
        if bullets:
            lines.append("\n=== 风格护栏 ===\n" + bullets)

    lines.append("")

    if added:
        lines.append("=== Open Plots 新增意图 ===")
        for item in added:
            lines.append(f"  [ ] 可引入：{item}")
    if resolved:
        lines.append("=== Open Plots 收束意图（最多1条） ===")
        for item in resolved[:1]:
            lines.append(f"  [ ] 可收束：{item}")

    lines.append("")

    lines.append(
        "=== 交付要求 ===\n"
        "1. 必须按【场景分解】顺序写作，禁止跳过或合并场景\n"
        "2. 每个场景必须包含：可视化行动/对话/观察，禁止总结性叙述\n"
        "3. 结尾必须留下明确的【钩子】，使下一章立即可写\n"
        "4. 禁止在单章内完成多个关键事件（发现→验证→解决不得连跳）\n"
        "5. 角色动机必须在场景中自然落地，而非通过旁白说明"
    )

    return "\n".join(lines)


def has_pending_chapter_generation_batch(db: Session, novel_id: str) -> bool:
    """
    是否存在未结束的章节生成批次（已入队 batch_start 或 chapter_generation_queued，
    但尚无 batch_done / batch_failed / batch_blocked）。
    """
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event.in_(
                ["batch_start", "chapter_generation_queued"]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    [
                        "batch_done",
                        "batch_failed",
                        "batch_blocked",
                        "chapter_generation_enqueue_failed",
                    ]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    return False


def has_pending_auto_pipeline_batch(
    db: Session, novel_id: str, *, exclude_batch_id: str | None = None
) -> bool:
    """
    是否存在未结束的全自动 Pipeline 批次。
    包含 queued/start/plan/chapters 阶段；done/failed/skipped 视为终态。
    """
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event.in_(
                [
                    "auto_pipeline_queued",
                    "auto_pipeline_start",
                    "auto_pipeline_plan_batch",
                    "auto_pipeline_chapters",
                ]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid or bid == exclude_batch_id:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    [
                        "auto_pipeline_done",
                        "auto_pipeline_failed",
                        "auto_pipeline_skipped",
                        "auto_pipeline_enqueue_failed",
                        "ai_create_done",
                        "ai_create_failed",
                    ]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    return False

def get_active_auto_pipeline_count(db: Session) -> int:
    """
    获取全局当前正在排队或执行的全自动生成/建书批次数量。
    用于限流和排队提示。
    """
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.event.in_(
                [
                    "auto_pipeline_queued",
                    "auto_pipeline_start",
                    "ai_create_queued",
                    "ai_create_brainstorming",
                ]
            )
        )
        .distinct()
        .all()
    )
    
    count = 0
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    [
                        "auto_pipeline_done",
                        "auto_pipeline_failed",
                        "auto_pipeline_skipped",
                        "auto_pipeline_enqueue_failed",
                        "ai_create_done",
                        "ai_create_failed",
                    ]
                ),
            )
            .first()
        )
        if not terminal:
            count += 1
    return count


def has_pending_volume_plan_batch(db: Session, novel_id: str) -> bool:
    """是否存在未结束的卷章计划生成批次。"""
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event.in_(
                ["volume_plan_queued", "volume_plan_started"]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    [
                        "volume_plan_done",
                        "volume_plan_failed",
                        "volume_plan_enqueue_failed",
                    ]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    return False


def has_pending_memory_refresh_batch(db: Session, novel_id: str) -> bool:
    """是否存在未结束的手动/后台记忆刷新批次（已入队或已开始，尚无终态）。"""
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event.in_(
                [
                    "memory_refresh_queued",
                    "memory_refresh_consumed",
                    "memory_refresh_started",
                ]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    [
                        "memory_refresh_done",
                        "memory_refresh_failed",
                        "memory_refresh_validation_failed",
                        "memory_refresh_warning",
                        "memory_refresh_no_approved",
                        "memory_refresh_not_found",
                        "memory_refresh_enqueue_failed",
                    ]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    return False


def has_pending_chapter_consistency_batch(
    db: Session, novel_id: str, chapter_id: str
) -> bool:
    """同一章节是否有一致性修订任务尚未结束。"""
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id.like(f"consist-{chapter_id}-%"),
            NovelGenerationLog.event.in_(
                ["chapter_consistency_queued", "chapter_consistency_started"]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    ["chapter_consistency_done", "chapter_consistency_failed"]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    return False


def has_pending_chapter_revise_batch(
    db: Session, novel_id: str, chapter_id: str
) -> bool:
    """同一章节是否有按意见改稿任务尚未结束。"""
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id.like(f"revise-{chapter_id}-%"),
            NovelGenerationLog.event.in_(
                ["chapter_revise_queued", "chapter_revise_started"]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    ["chapter_revise_done", "chapter_revise_failed"]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    return False


def has_pending_chapter_polish_batch(
    db: Session, novel_id: str, chapter_id: str
) -> bool:
    """同一章节是否有去AI味润色任务尚未结束。"""
    rows = (
        db.query(NovelGenerationLog.batch_id)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id.like(f"polish-{chapter_id}-%"),
            NovelGenerationLog.event.in_(
                ["chapter_polish_queued", "chapter_polish_started"]
            ),
        )
        .distinct()
        .all()
    )
    for (bid,) in rows:
        if not bid:
            continue
        terminal = (
            db.query(NovelGenerationLog.id)
            .filter(
                NovelGenerationLog.batch_id == bid,
                NovelGenerationLog.event.in_(
                    ["chapter_polish_done", "chapter_polish_failed"]
                ),
            )
            .first()
        )
        if terminal:
            continue
        last_log = (
            db.query(NovelGenerationLog.created_at)
            .filter(NovelGenerationLog.batch_id == bid)
            .order_by(NovelGenerationLog.created_at.desc())
            .first()
        )
        last_at = last_log[0] if last_log else None
        if last_at and (datetime.utcnow() - last_at) >= _CHAPTER_POLISH_STALE_GRACE:
            continue
        if not last_at:
            continue
        if not terminal:
            return True
    return False
