"""
小说生成相关共用工具：日志、章节标题规范化、章计划提示词、并发检测。

供 HTTP 路由与 Celery 任务复用，避免逻辑分叉。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import NovelGenerationLog
from app.models.task import UserTask
from app.services.chapter_plan_schema import normalize_beats_to_v2
from app.services.user_task_service import TERMINAL_STATUSES


_CHAPTER_POLISH_STALE_GRACE = timedelta(minutes=30)
_CHAPTER_GENERATION_MIN_STALE_GRACE = timedelta(minutes=30)
_CHAPTER_GENERATION_PER_CHAPTER_BUFFER_SECONDS = 900
# Worker 内已无对应 Celery 任务时，尽快回收僵尸批次（进程重启、任务丢失）
_CHAPTER_GENERATION_IF_WORKER_GONE_GRACE = timedelta(minutes=5)
_VOLUME_PLAN_BASE_STALE_GRACE = timedelta(minutes=45)
_VOLUME_PLAN_IF_WORKER_GONE_GRACE = timedelta(minutes=5)

logger = logging.getLogger(__name__)


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


def _safe_log_meta(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _chapter_generation_stale_grace(meta: dict[str, Any]) -> timedelta:
    raw_count = (
        meta.get("actual_count")
        or meta.get("requested_count")
        or meta.get("count")
        or len(meta.get("chapter_nos") or [])
        or 1
    )
    try:
        count = max(1, int(raw_count))
    except Exception:
        count = 1
    per_chapter = float(settings.novel_chapter_timeout or 900.0)
    seconds = count * per_chapter + _CHAPTER_GENERATION_PER_CHAPTER_BUFFER_SECONDS
    return max(_CHAPTER_GENERATION_MIN_STALE_GRACE, timedelta(seconds=seconds))


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
    expressive = (
        normalized.get("expressive_brief", {}) if isinstance(normalized, dict) else {}
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
    expressive_lines: list[str] = []
    expressive_labels = {
        "pov_strategy": "视角策略",
        "emotional_curve": "情绪曲线",
        "sensory_focus": "感官焦点",
        "dialogue_strategy": "对白策略",
        "scene_tempo": "场景节奏",
        "reveal_strategy": "揭示策略",
    }
    if isinstance(expressive, dict):
        for key, label in expressive_labels.items():
            value = expressive.get(key)
            if isinstance(value, str) and value.strip():
                expressive_lines.append(f"- {label}：{value.strip()}")
    if expressive_lines:
        lines.append("=== 表现力简报 ===\n" + "\n".join(expressive_lines))

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
            scene_emotion = scene.get("emotion_beat", "")
            scene_camera = scene.get("camera", "")
            scene_dialogue = scene.get("dialogue_density", "")
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
            if scene_emotion:
                lines.append(f"  情绪节拍：{scene_emotion}")
            if scene_camera:
                lines.append(f"  镜头调度：{scene_camera}")
            if scene_dialogue:
                lines.append(f"  对白密度：{scene_dialogue}")
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


def build_future_plan_summary(
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
) -> str:
    """构建后续章节的精简摘要（用于多章执行卡注入）。

    只保留最核心的信息：章名 + 目标 + 冲突 + 结尾钩子 + must_not + reserved_for_later。
    不包含场景分解、交付要求等详细内容，控制在 100-200 字/章。
    """
    normalized = normalize_beats_to_v2(beats)
    card = (
        normalized.get("execution_card", {}) if isinstance(normalized, dict) else {}
    )

    parts: list[str] = [f"第{chapter_no}章「{plan_title or '待定'}」"]

    goal = card.get("chapter_goal", "")
    conflict = card.get("core_conflict", "")
    turn = card.get("key_turn", "")
    hook = card.get("ending_hook", "")

    if isinstance(goal, str) and goal.strip():
        parts.append(f"  目标：{goal.strip()}")
    if isinstance(conflict, str) and conflict.strip():
        parts.append(f"  冲突：{conflict.strip()}")
    if isinstance(turn, str) and turn.strip():
        parts.append(f"  转折：{turn.strip()}")
    if isinstance(hook, str) and hook.strip():
        parts.append(f"  钩子：{hook.strip()}")

    must_happen = card.get("must_happen")
    if isinstance(must_happen, list) and must_happen:
        items = [str(x).strip() for x in must_happen if str(x).strip()]
        if items:
            parts.append(f"  必须发生：{'；'.join(items[:3])}")

    must_not = card.get("must_not")
    if isinstance(must_not, list) and must_not:
        items = [str(x).strip() for x in must_not if str(x).strip()]
        if items:
            parts.append(f"  禁止：{'；'.join(items[:3])}")

    rsv = card.get("reserved_for_later")
    if isinstance(rsv, list) and rsv:
        items = []
        for it in rsv:
            if not isinstance(it, dict):
                continue
            item_name = it.get("item", "")
            if isinstance(item_name, str) and item_name.strip():
                nb = it.get("not_before_chapter")
                if isinstance(nb, int):
                    items.append(f"{item_name.strip()}（第{nb}章后）")
                else:
                    items.append(f"{item_name.strip()}（后续）")
        if items:
            parts.append(f"  延后解锁：{'；'.join(items[:3])}")

    return "\n".join(parts)


def build_multi_chapter_plan_hint(
    current_plan_hint: str,
    future_plans: list[dict[str, Any]],
    max_future: int = 9,
) -> str:
    """将当前章完整执行卡与后续章摘要组合为多章执行卡。"""
    if not future_plans:
        return current_plan_hint

    lines: list[str] = [current_plan_hint]
    lines.append("")
    lines.append("【后续章节计划摘要（仅供参考，只需写当前章）】")

    shown = 0
    for fp in future_plans[:max_future]:
        summary = fp.get("summary", "")
        if summary:
            lines.append(summary)
            shown += 1

    if shown == 0:
        # 没有可用的后续章摘要，不添加
        return current_plan_hint

    lines.append("")
    lines.append(
        "注意：上方【后续章节计划摘要】仅供你了解故事走向，帮助提前埋伏笔和避免冲突；"
        "你只需完成当前章的执行清单，不得提前写后续章节的内容。"
    )

    return "\n".join(lines)


def has_pending_chapter_generation_batch(db: Session, novel_id: str) -> bool:
    """
    是否存在未结束的章节生成批次（已入队 batch_start 或 chapter_generation_queued，
    但尚无 batch_done / batch_failed / batch_blocked）。

    用户可清空「生成日志」；并发判断同时看 user_tasks，避免日志被删后误判为空闲或无法恢复。
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
                        "batch_cancelled",
                        "chapter_generation_enqueue_failed",
                        # 全自动 pipeline 与章节生成共用同一 batch_id 时，内层会写 batch_start，
                        # 失败路径常见 chapter_memory_delta_failed / auto_pipeline_failed，必须视为终态。
                        "chapter_failed",
                        "chapter_memory_delta_failed",
                        "auto_pipeline_done",
                        "auto_pipeline_failed",
                        "auto_pipeline_cancelled",
                    ]
                ),
            )
            .first()
        )
        if not terminal:
            return True
    ut = (
        db.query(UserTask.id)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.kind == "generate_chapters",
            UserTask.batch_id.isnot(None),
            ~UserTask.status.in_(list(TERMINAL_STATUSES)),
        )
        .first()
    )
    return bool(ut)


def recover_stale_chapter_generation_batches(db: Session, novel_id: str) -> dict[str, Any]:
    """
    将明显超时且没有终态的普通章节生成批次标记为失败。

    章节生成没有独立 Redis 锁。    默认可按「章节数 × 超时」给较长宽限；若 Celery inspect
    显示已无任何 worker 持有该 batch 任务（进程重启、任务从队列丢失），则改用约 5 分钟短宽限，
    避免长时间占住「进行中」槽位。丢失的后台任务不会自动续跑，需用户重新发起生成。
    用户清空生成日志后，仍根据未终态的 user_tasks 合并批次并回收。
    在 Celery 中已无本 batch 时优先按 user_tasks.meta 自动再入队续跑；失败或达次数上限后仍落回 batch_failed。
    """
    rows = (
        db.query(NovelGenerationLog)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event.in_(
                [
                    "batch_start",
                    "chapter_generation_queued",
                    "chapter_generation_resume_enqueued",
                    "batch_resumed",
                    "chapter_start",
                    "chapter_draft_done",
                    "chapter_consistency_done",
                    "chapter_consistency_failed",
                    "chapter_plan_guard_failed",
                    "chapter_plan_guard_fixed",
                    "chapter_plan_guard_warn",
                    "chapter_expressive_enhance_done",
                    "chapter_expressive_enhance_failed",
                    "chapter_style_polish_done",
                    "chapter_style_polish_failed",
                    "chapter_saved",
                    "chapter_judge_done",
                    "chapter_judge_failed",
                    "chapter_story_assets_queued",
                    "chapter_story_assets_enqueue_failed",
                    "batch_done",
                    "batch_failed",
                    "batch_blocked",
                    "batch_cancelled",
                    "chapter_generation_enqueue_failed",
                ]
            ),
        )
        .order_by(NovelGenerationLog.created_at.asc())
        .all()
    )
    batches: dict[str, dict[str, Any]] = {}
    for row in rows:
        bid = str(row.batch_id or "")
        if not bid or not bid.startswith("gen-"):
            continue
        info = batches.setdefault(
            bid,
            {"events": set(), "last_at": row.created_at, "meta": {}},
        )
        event = str(row.event or "")
        info["events"].add(event)
        if row.created_at and (
            info["last_at"] is None or row.created_at > info["last_at"]
        ):
            info["last_at"] = row.created_at
        if event in ("chapter_generation_queued", "batch_start"):
            meta = _safe_log_meta(getattr(row, "meta_json", None))
            if meta:
                info["meta"] = {**info.get("meta", {}), **meta}

    # 生成日志可被清空；未终态的 user_tasks 仍须参与回收，否则仅依赖上面 logs 的批次会漏掉
    for ut in (
        db.query(UserTask)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.kind == "generate_chapters",
            UserTask.batch_id.isnot(None),
            UserTask.batch_id.like("gen-%"),
            ~UserTask.status.in_(list(TERMINAL_STATUSES)),
        )
        .all()
    ):
        bid = str(ut.batch_id or "")
        if not bid:
            continue
        m = ut.meta if isinstance(ut.meta, dict) else {}
        t_ref = ut.updated_at or ut.started_at or ut.created_at
        if bid not in batches:
            batches[bid] = {
                "events": set(),
                "last_at": t_ref,
                "meta": m,
            }
        else:
            if t_ref and (
                batches[bid].get("last_at") is None
                or t_ref > batches[bid]["last_at"]
            ):
                batches[bid]["last_at"] = t_ref
            if m and not batches[bid].get("meta"):
                batches[bid]["meta"] = m

    from app.tasks import novel_tasks as _novel_tasks

    now = datetime.utcnow()
    recovered_batches: list[str] = []
    requeued_batches: list[str] = []
    terminal_events = {
        "batch_done",
        "batch_failed",
        "batch_blocked",
        "batch_cancelled",
        "chapter_generation_enqueue_failed",
        "chapter_failed",
        "chapter_memory_delta_failed",
        "auto_pipeline_done",
        "auto_pipeline_failed",
        "auto_pipeline_cancelled",
    }
    for batch_id, info in batches.items():
        events = info["events"]
        if events & terminal_events:
            continue
        last_at = info.get("last_at")
        if not last_at:
            continue
        long_grace = _chapter_generation_stale_grace(info.get("meta") or {})
        held = _novel_tasks.celery_chapter_batch_held_in_workers(batch_id)
        if held is True:
            grace = long_grace
        elif held is False:
            grace = _CHAPTER_GENERATION_IF_WORKER_GONE_GRACE
        else:
            grace = long_grace
        if now - last_at < grace:
            continue
        if _novel_tasks.try_requeue_stale_chapter_generation_batch(
            db,
            novel_id,
            batch_id,
            held=held,
        ):
            requeued_batches.append(batch_id)
            continue
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="batch_failed",
            level="warning",
            message="章节生成任务疑似因进程重启或异常退出中断，系统已自动回收僵尸批次",
            meta={
                "reason": "stale_recovered",
                "last_event_at": last_at.isoformat() if last_at else None,
                "stale_grace_seconds": int(grace.total_seconds()),
            },
        )
        try:
            from app.services.user_task_service import update_user_task_by_batch_id

            update_user_task_by_batch_id(
                db,
                batch_id=batch_id,
                status="failed",
                last_message="章节生成任务疑似中断，系统已自动回收僵尸批次",
                finished_at=now,
            )
        except Exception:
            logger.exception(
                "update stale chapter user task failed | batch_id=%s",
                batch_id,
            )
        recovered_batches.append(batch_id)

    if recovered_batches or requeued_batches:
        db.commit()
        if recovered_batches:
            logger.warning(
                "recovered stale chapter generation batches | novel_id=%s batches=%s",
                novel_id,
                recovered_batches,
            )
        if requeued_batches:
            logger.warning(
                "requeued chapter generation after stale | novel_id=%s batches=%s",
                novel_id,
                requeued_batches,
            )
    return {
        "recovered_batches": recovered_batches,
        "requeued_batches": requeued_batches,
    }


def recover_stale_volume_plan_batches(db: Session, novel_id: str) -> dict[str, Any]:
    """
    卷章计划生成无独立 Redis 锁；Worker 掉线后同章节生成，可能长时间被判定为进行中。
    在 Celery 已找不到对应 batch 任务时，用较短宽限释放槽位；否则仍用较长写计划宽限。
    """
    from app.tasks import novel_tasks as _novel_tasks
    from app.services.user_task_service import update_user_task_by_batch_id

    rows = (
        db.query(NovelGenerationLog)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.batch_id.like("vol-plan-%"),
        )
        .order_by(NovelGenerationLog.created_at.asc())
        .all()
    )
    batches: dict[str, dict[str, Any]] = {}
    for row in rows:
        bid = str(row.batch_id or "")
        if not bid:
            continue
        info = batches.setdefault(
            bid,
            {"events": set(), "last_at": row.created_at},
        )
        info["events"].add(str(row.event or ""))
        if row.created_at and (
            info["last_at"] is None or row.created_at > info["last_at"]
        ):
            info["last_at"] = row.created_at

    for ut in (
        db.query(UserTask)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.kind == "volume_plan",
            UserTask.batch_id.isnot(None),
            UserTask.batch_id.like("vol-plan-%"),
            ~UserTask.status.in_(list(TERMINAL_STATUSES)),
        )
        .all()
    ):
        bid = str(ut.batch_id or "")
        if not bid:
            continue
        t_ref = ut.updated_at or ut.started_at or ut.created_at
        if bid not in batches:
            batches[bid] = {"events": set(), "last_at": t_ref}
        elif t_ref and (
            batches[bid].get("last_at") is None or t_ref > batches[bid]["last_at"]
        ):
            batches[bid]["last_at"] = t_ref

    terminal = {
        "volume_plan_done",
        "volume_plan_failed",
        "volume_plan_enqueue_failed",
    }
    now = datetime.utcnow()
    recovered: list[str] = []
    requeued_vol: list[str] = []
    for batch_id, info in batches.items():
        if info["events"] & terminal:
            continue
        last_at = info.get("last_at")
        if not last_at:
            continue
        held = _novel_tasks.celery_volume_plan_batch_held_in_workers(batch_id)
        if held is True:
            grace = _VOLUME_PLAN_BASE_STALE_GRACE
        elif held is False:
            grace = _VOLUME_PLAN_IF_WORKER_GONE_GRACE
        else:
            grace = _VOLUME_PLAN_BASE_STALE_GRACE
        if now - last_at < grace:
            continue
        if _novel_tasks.try_requeue_stale_volume_plan_batch(
            db, novel_id, batch_id, held=held
        ):
            requeued_vol.append(batch_id)
            continue
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="volume_plan_failed",
            level="warning",
            message="卷章计划生成疑似因进程重启或异常退出中断，系统已自动回收僵尸批次",
            meta={
                "reason": "stale_recovered",
                "last_event_at": last_at.isoformat() if last_at else None,
                "stale_grace_seconds": int(grace.total_seconds()),
            },
        )
        try:
            update_user_task_by_batch_id(
                db,
                batch_id=batch_id,
                status="failed",
                last_message="卷章计划任务疑似中断，系统已自动回收僵尸批次",
                finished_at=now,
            )
        except Exception:
            logger.exception(
                "update stale volume plan user task failed | batch_id=%s", batch_id
            )
        recovered.append(batch_id)

    if recovered or requeued_vol:
        db.commit()
        if recovered:
            logger.warning(
                "recovered stale volume plan batches | novel_id=%s batches=%s",
                novel_id,
                recovered,
            )
        if requeued_vol:
            logger.warning(
                "requeued volume plan after stale | novel_id=%s batches=%s",
                novel_id,
                requeued_vol,
            )
    return {"recovered_batches": recovered, "requeued_batches": requeued_vol}


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
                    "auto_pipeline_resumed",
                    "auto_pipeline_plan_batch",
                    "auto_pipeline_chapters",
                    "auto_pipeline_resume_enqueued",
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
    qut = (
        db.query(UserTask.id)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.kind.in_(("auto_generate", "ai_create_and_start")),
            UserTask.batch_id.isnot(None),
            ~UserTask.status.in_(list(TERMINAL_STATUSES)),
        )
    )
    if exclude_batch_id:
        qut = qut.filter(UserTask.batch_id != exclude_batch_id)
    if qut.first():
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
                    "auto_pipeline_resumed",
                    "auto_pipeline_resume_enqueued",
                    "ai_create_queued",
                    "ai_create_brainstorming",
                    "ai_create_resume_enqueued",
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
    ut = (
        db.query(UserTask.id)
        .filter(
            UserTask.novel_id == novel_id,
            UserTask.kind == "volume_plan",
            UserTask.batch_id.isnot(None),
            ~UserTask.status.in_(list(TERMINAL_STATUSES)),
        )
        .first()
    )
    return bool(ut)


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
