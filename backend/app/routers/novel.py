from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.novel import (
    Chapter,
    ChapterFeedback,
    Novel,
    NovelGenerationLog,
    NovelMemory,
)
from app.models.volume import NovelVolume, NovelChapterPlan
from app.services.memory_readable import (
    memory_payload_readable_zh_auto,
    memory_payload_to_readable_zh,
)
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_repo import (
    chapter_content_metrics,
    format_approved_chapters_summary,
    format_continuity_excerpts,
    format_recent_approved_fulltext_context,
    format_volume_event_summary,
    format_volume_progress_anchor,
    latest_memory_json,
    next_chapter_no_from_approved,
    _select_arc_for_chapter,
)
from app.models.volume import NovelChapterPlan
from app.services.memory_normalize_sync import (
    normalized_memory_to_dict,
    replace_normalized_from_payload,
    sync_json_snapshot_from_normalized,
)
from app.services.novel_storage import ensure_local_novel_dir, save_novel_reference
from app.tasks.novel_tasks import (
    novel_consolidate_memory,
    novel_refresh_memory_for_novel,
    novel_sync_json_snapshot,
)

router = APIRouter(prefix="/api/novels", tags=["novels"])
logger = logging.getLogger(__name__)


def _build_chapter_plan_hint(
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
    added: list[Any],
    resolved: list[Any],
) -> str:
    """
    构建"执行清单"格式的章节计划提示词。

    将原本自由的 plot_summary 转化为结构化的场景清单（如有），
    并明确每个章节的执行检查点，确保LLM按步骤完成而非跳过。
    """
    lines: list[str] = [
        "【本章执行清单（逐项勾选，禁止跳过）】",
        f"计划章名：{plan_title}",
        "",
        "=== 执行检查点（完成后勾选） ===",
    ]

    # 核心 beats 转化为检查点
    goal = beats.get("goal", "")
    conflict = beats.get("conflict", "")
    turn = beats.get("turn", "")
    hook = beats.get("hook", "")

    if isinstance(goal, str) and goal.strip():
        lines.append(f"[ ] 开局目标：{goal.strip()}")
    if isinstance(conflict, str) and conflict.strip():
        lines.append(f"[ ] 核心冲突：{conflict.strip()}")
    if isinstance(turn, str) and turn.strip():
        lines.append(f"[ ] 情节转折：{turn.strip()}")
    if isinstance(hook, str) and hook.strip():
        lines.append(f"[ ] 结尾钩子：{hook.strip()}")

    lines.append("")

    # 剧情梗概 - 支持 scene list 结构
    ps = beats.get("plot_summary")
    scenes: list[dict[str, Any]] = []
    if isinstance(ps, list):
        scenes = [s for s in ps if isinstance(s, dict)]
    elif isinstance(ps, str) and ps.strip():
        lines.append(f"=== 本章剧情梗概 ===\n{ps.strip()}")

    if scenes:
        lines.append("=== 场景分解（必须按顺序完成，每场景约500-800字） ===")
        total_words = 0
        for i, scene in enumerate(scenes, 1):
            if not isinstance(scene, dict):
                continue
            scene_goal = scene.get("goal", "")
            scene_content = scene.get("content", "")
            scene_words = scene.get("words", 600)
            if isinstance(scene_words, int) and scene_words > 0:
                total_words += scene_words
            else:
                total_words += 600

            lines.append(f"\n场景{i}:")
            if scene_goal:
                lines.append(f"  [ ] 目标：{scene_goal}")
            if scene_content:
                lines.append(f"  内容：{scene_content}")
            lines.append(f"  建议字数：约{scene_words}字")
        lines.append(f"\n本章建议总字数：{total_words}字")

    lines.append("")

    # 进度边界
    pa = beats.get("progress_allowed")
    if isinstance(pa, str) and pa.strip():
        lines.append(f"=== 进度边界·允许推进 ===\n{pa.strip()}")
    elif isinstance(pa, list) and pa:
        bullets = "\n".join(f"  · {x}" for x in pa if str(x).strip())
        if bullets:
            lines.append(f"=== 进度边界·允许推进 ===\n{bullets}")

    # 绝对禁止
    mn = beats.get("must_not")
    if isinstance(mn, list) and mn:
        bullets = "\n".join(f"  [ ] 禁止：{x}" for x in mn if str(x).strip())
        if bullets:
            lines.append(f"\n=== 绝对禁止（违反视为不合格） ===\n{bullets}")

    # 延后解锁
    rsv = beats.get("reserved_for_later")
    if isinstance(rsv, list) and rsv:
        parts: list[str] = []
        for it in rsv:
            if not isinstance(it, dict):
                continue
            item = it.get("item")
            nb = it.get("not_before_chapter")
            if not (isinstance(item, str) and item.strip()):
                continue
            item_s = item.strip()
            if isinstance(nb, int):
                parts.append(
                    f"  [ ] 禁写「{item_s}」——须在第{nb}章及之后才可出现"
                )
            else:
                parts.append(f"  [ ] 禁写「{item_s}」——留待后续章")
        if parts:
            lines.append("\n=== 延后解锁（当前章不得写出） ===\n" + "\n".join(parts))

    lines.append("")

    # open_plots 意图
    if added:
        lines.append(f"=== Open Plots 新增意图 ===")
        for item in added:
            lines.append(f"  [ ] 可引入：{item}")
    if resolved:
        lines.append(f"=== Open Plots 收束意图（最多1条） ===")
        for item in resolved[:1]:
            lines.append(f"  [ ] 可收束：{item}")

    lines.append("")

    # 交付要求
    lines.append(
        "=== 交付要求 ===\n"
        "1. 必须按【场景分解】顺序写作，禁止跳过或合并场景\n"
        "2. 每个场景必须包含：可视化行动/对话/观察，禁止总结性叙述\n"
        "3. 结尾必须留下明确的【钩子】，使下一章立即可写\n"
        "4. 禁止在单章内完成多个关键事件（发现→验证→解决不得连跳）\n"
        "5. 角色动机必须在场景中自然落地，而非通过旁白说明"
    )

    return "\n".join(lines)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class NovelCreate(BaseModel):
    title: str
    intro: str = ""
    background: str = ""
    style: str = ""
    target_chapters: int = Field(default=300, ge=1, le=20000)
    daily_auto_chapters: int = Field(default=0, ge=0, le=20)


class NovelPatch(BaseModel):
    title: str | None = None
    intro: str | None = None
    background: str | None = None
    style: str | None = None
    target_chapters: int | None = None
    daily_auto_chapters: int | None = None
    status: str | None = None


class ConfirmFrameworkBody(BaseModel):
    framework_markdown: str
    framework_json: str = "{}"


class FrameworkUpdateBody(BaseModel):
    """
    仅更新 novels.framework_json/framework_markdown，不重置章节、不写入初始记忆。
    用于在已有写作进度下迭代大纲与节拍（例如补齐 arcs 范围与 beats）。
    """

    framework_markdown: str | None = None
    framework_json: str = Field(..., min_length=2)
    auto_fill_arcs: bool = True
    auto_fill_beats: bool = True


class ChapterFeedbackBody(BaseModel):
    body: str


class GenerateChapterBody(BaseModel):
    title_hint: str = ""
    count: int = Field(default=1, ge=1, le=5)
    use_cold_recall: bool = False
    cold_recall_items: int = Field(default=5, ge=1, le=12)
    auto_consistency_check: bool = False
    # 按卷驱动：允许生成指定章（用于点击章计划条目生成正文）
    chapter_no: int | None = Field(default=None, ge=1, le=20000)


class ChapterReviseBody(BaseModel):
    user_prompt: str = Field(..., min_length=1)


class ChapterUpdateBody(BaseModel):
    title: str | None = None
    content: str = Field(..., min_length=1)


class ManualFixMemoryCanonicalLast(BaseModel):
    key_facts: list[str] = Field(default_factory=list)
    causal_results: list[str] = Field(default_factory=list)
    open_plots_added: list[str] = Field(default_factory=list)
    open_plots_resolved: list[str] = Field(default_factory=list)


class ManualFixMemoryBody(BaseModel):
    open_plots: list[str] = Field(default_factory=list)
    canonical_last: ManualFixMemoryCanonicalLast = Field(
        default_factory=ManualFixMemoryCanonicalLast
    )
    notes_hint: str = ""


class MemorySaveBody(BaseModel):
    """可选：整包替换 payload_json；可选：写入/清除 readable_zh_override（人工中文阅读）。"""

    payload_json: str | None = None
    readable_zh_override: str | None = None


class InspirationChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str = Field(..., min_length=1, max_length=48_000)


class InspirationChatBody(BaseModel):
    messages: list[InspirationChatMessage] = Field(..., min_length=1, max_length=40)


class ChapterContextChatBody(BaseModel):
    messages: list[InspirationChatMessage] = Field(..., min_length=1, max_length=40)


def _append_generation_log(
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


def _extract_title_from_generated_content(chapter_no: int, content: str) -> str:
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


def _ensure_chapter_heading(
    chapter_no: int, content: str, *, title_hint: str = ""
) -> tuple[str, str]:
    """
    兜底：保证正文首行为 `第N章《章名》`，并返回可用于落库的章节标题。
    """
    raw = (content or "").strip()
    title = (title_hint or "").strip() or _extract_title_from_generated_content(chapter_no, raw)
    if title.startswith(f"第{chapter_no}章"):
        title = title.replace(f"第{chapter_no}章", "").strip(" 《》:：-—\t")
    if not title:
        # 最后兜底，确保永远有章名
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
        # 已有标题行时，仅规范为统一格式
        body = "\n".join(raw.splitlines()[1:]).strip()
        return title, (f"{heading}\n\n{body}" if body else heading)

    return title, f"{heading}\n\n{raw}"


def _enqueue_auto_refresh_memory_from_approved(
    db: Session, novel_id: str, *, reason: str
) -> tuple[str, str | None, str | None]:
    """
    审定相关操作后异步刷新记忆，避免阻塞 HTTP 请求。
    返回：(status, task_id, batch_id)；status: queued | skipped
    """
    try:
        batch_id = f"mem-refresh-{int(time.time())}-{novel_id[:8]}"
        task = novel_refresh_memory_for_novel.delay(novel_id, reason, batch_id)
        task_id = getattr(task, "id", None)
        if batch_id:
            _append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="memory_refresh_queued",
                message="已入队后台记忆刷新",
                meta={"reason": reason, "task_id": task_id},
            )
        return "queued", task_id, batch_id
    except Exception:
        logger.exception(
            "enqueue memory refresh failed | novel_id=%s reason=%s",
            novel_id,
            reason,
        )
        _append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=f"mem-refresh-{int(time.time())}-{novel_id[:8]}",
            event="memory_refresh_enqueue_failed",
            level="error",
            message="后台记忆刷新入队失败",
            meta={"reason": reason},
        )
        return "skipped", None, None


@router.post("/inspiration-chat")
async def novel_inspiration_chat(
    body: InspirationChatBody, db: Session = Depends(get_db)
) -> dict[str, str]:
    """新建小说：多轮对话 + 联网搜索，获取创作灵感（302 Chat web-search）。"""
    llm = NovelLLMService()
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        reply = await llm.inspiration_chat(msgs, db=db)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    return {"reply": reply}


@router.post("/inspiration-chat/stream")
async def novel_inspiration_chat_stream(
    body: InspirationChatBody, db: Session = Depends(get_db)
) -> StreamingResponse:
    llm = NovelLLMService()
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]

    async def event_iter():
        try:
            async for evt in llm.inspiration_chat_stream(msgs, db=db):
                et = evt.get("type", "text")
                delta = evt.get("delta", "")
                if not isinstance(delta, str) or not delta:
                    continue
                if et == "think":
                    yield _sse("think", {"delta": delta})
                else:
                    yield _sse("text", {"delta": delta})
            yield _sse("done", {"ok": True})
        except RuntimeError as e:
            yield _sse("error", {"message": str(e)})
        except Exception:
            logger.exception("inspiration-chat stream failed")
            yield _sse("error", {"message": "流式对话失败"})

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.post("/{novel_id}/chapter-chat")
async def chapter_context_chat(
    novel_id: str, body: ChapterContextChatBody, db: Session = Depends(get_db)
) -> dict[str, str]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    mem = latest_memory_json(db, novel_id)
    approved = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .order_by(Chapter.chapter_no.asc())
        .all()
    )
    approved_summary = format_approved_chapters_summary(
        approved,
        settings.novel_chapter_summary_tail_chars,
        head_chars=settings.novel_chapter_summary_head_chars,
        mode=settings.novel_chapter_summary_mode,
        max_chapters=settings.novel_memory_refresh_chapters,
    )
    continuity = format_continuity_excerpts(db, novel_id, approved_only=True)
    llm = NovelLLMService()
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        reply = await llm.chapter_context_chat(
            n,
            memory_json=mem,
            approved_chapters_summary=approved_summary,
            continuity_excerpt=continuity,
            messages=msgs,
            db=db,
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    return {"reply": reply}


@router.post("/{novel_id}/chapter-chat/stream")
async def chapter_context_chat_stream(
    novel_id: str, body: ChapterContextChatBody, db: Session = Depends(get_db)
) -> StreamingResponse:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    mem = latest_memory_json(db, novel_id)
    approved = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .order_by(Chapter.chapter_no.asc())
        .all()
    )
    approved_summary = format_approved_chapters_summary(
        approved,
        settings.novel_chapter_summary_tail_chars,
        head_chars=settings.novel_chapter_summary_head_chars,
        mode=settings.novel_chapter_summary_mode,
        max_chapters=settings.novel_memory_refresh_chapters,
    )
    continuity = format_continuity_excerpts(db, novel_id, approved_only=True)
    llm = NovelLLMService()
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]

    async def event_iter():
        try:
            async for evt in llm.chapter_context_chat_stream(
                n,
                memory_json=mem,
                approved_chapters_summary=approved_summary,
                continuity_excerpt=continuity,
                messages=msgs,
                db=db,
            ):
                et = evt.get("type", "text")
                delta = evt.get("delta", "")
                if not isinstance(delta, str) or not delta:
                    continue
                if et == "think":
                    yield _sse("think", {"delta": delta})
                else:
                    yield _sse("text", {"delta": delta})
            yield _sse("done", {"ok": True})
        except RuntimeError as e:
            yield _sse("error", {"message": str(e)})
        except Exception:
            logger.exception("chapter-chat stream failed | novel_id=%s", novel_id)
            yield _sse("error", {"message": "章节助手流式对话失败"})

    return StreamingResponse(event_iter(), media_type="text/event-stream")


@router.get("")
def list_novels(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(Novel).order_by(Novel.updated_at.desc()).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "intro": n.intro,
            "status": n.status,
            "framework_confirmed": n.framework_confirmed,
            "daily_auto_chapters": n.daily_auto_chapters,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
        }
        for n in rows
    ]


@router.post("")
def create_novel(body: NovelCreate, db: Session = Depends(get_db)) -> dict[str, str]:
    n = Novel(
        title=body.title,
        intro=body.intro,
        background=body.background,
        style=body.style,
        target_chapters=body.target_chapters,
        daily_auto_chapters=body.daily_auto_chapters,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return {"id": n.id}


@router.get("/{novel_id}")
def get_novel(novel_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {
        "id": n.id,
        "title": n.title,
        "intro": n.intro,
        "background": n.background,
        "style": n.style,
        "target_chapters": n.target_chapters,
        "daily_auto_chapters": n.daily_auto_chapters,
        "reference_filename": n.reference_filename,
        "reference_public_url": n.reference_public_url,
        "framework_confirmed": n.framework_confirmed,
        "framework_markdown": n.framework_markdown,
        "framework_json": n.framework_json,
        "status": n.status,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.patch("/{novel_id}")
def patch_novel(
    novel_id: str, body: NovelPatch, db: Session = Depends(get_db)
) -> dict[str, str]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(n, k, v)
    db.commit()
    return {"status": "ok"}


@router.delete("/{novel_id}")
def delete_novel(novel_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    # 注意：部分表（如 novel_generation_logs / novel_volumes / novel_chapter_plans）
    # 通过外键引用 novels，但未配置数据库级联删除；这里按顺序手动清理避免外键错误。
    try:
        deleted_plans = (
            db.query(NovelChapterPlan)
            .filter(NovelChapterPlan.novel_id == novel_id)
            .delete(synchronize_session=False)
        )
        deleted_vols = (
            db.query(NovelVolume)
            .filter(NovelVolume.novel_id == novel_id)
            .delete(synchronize_session=False)
        )
        deleted_logs = (
            db.query(NovelGenerationLog)
            .filter(NovelGenerationLog.novel_id == novel_id)
            .delete(synchronize_session=False)
        )
        # chapters/memories 由 ORM relationship cascade 处理
        db.delete(n)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("delete_novel failed | novel_id=%s err=%s", novel_id, e)
        raise
    return {
        "status": "ok",
        "deleted_generation_logs": str(deleted_logs),
        "deleted_volumes": str(deleted_vols),
        "deleted_chapter_plans": str(deleted_plans),
    }


@router.post("/{novel_id}/reference")
async def upload_reference(
    novel_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    data = await file.read()
    if len(data) > settings.reference_txt_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"参考 txt 单文件最大 {settings.reference_txt_max_bytes // (1024 * 1024)}MB",
        )
    key, url = await save_novel_reference(novel_id, data, file.filename or "reference.txt")
    n.reference_storage_key = key
    n.reference_public_url = url
    n.reference_filename = file.filename or "reference.txt"
    db.commit()
    return {"storage_key": key, "public_url": url}


@router.get("/{novel_id}/reference/file")
def download_local_reference(novel_id: str, db: Session = Depends(get_db)):
    n = db.get(Novel, novel_id)
    if not n or not n.reference_storage_key.startswith("local:"):
        raise HTTPException(404, "无本地参考文件")
    part = n.reference_storage_key.removeprefix("local:")
    path = Path(settings.novel_local_upload_dir).resolve() / part
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=n.reference_filename or "reference.txt")


@router.post("/{novel_id}/generate-framework")
async def generate_framework(novel_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    llm = NovelLLMService()
    md, fj = await llm.generate_framework(n, db=db)
    n.framework_markdown = md
    n.framework_json = fj
    n.framework_confirmed = False
    db.commit()
    return {"status": "ok"}


@router.post("/{novel_id}/confirm-framework")
def confirm_framework(
    novel_id: str, body: ConfirmFrameworkBody, db: Session = Depends(get_db)
) -> dict[str, str]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    try:
        json.loads(body.framework_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "framework_json 不是合法 JSON")
    n.framework_markdown = body.framework_markdown
    n.framework_json = body.framework_json
    n.framework_confirmed = True
    n.status = "active"
    # 初始记忆：先落规范化表，再由分表派生 JSON 快照（单一真源）
    ver = (
        db.query(func.max(NovelMemory.version)).filter(NovelMemory.novel_id == novel_id).scalar()
        or 0
    )
    new_ver = ver + 1
    replace_normalized_from_payload(db, novel_id, new_ver, body.framework_json)
    sync_json_snapshot_from_normalized(db, novel_id, summary="自确认框架初始化")
    db.commit()
    return {"status": "ok"}


def _parse_range_text(v: Any) -> tuple[int | None, int | None]:
    if v is None:
        return None, None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        try:
            return int(v[0]), int(v[1])
        except Exception:
            return None, None
    if isinstance(v, str):
        m = re.search(r"(\d+)\s*[-~—–]\s*(\d+)", v)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def _default_beats_for_arc(name: str, summary: str) -> list[dict[str, str]]:
    """
    生成“可导航但不过度写死”的节拍：用来控制一章只走一小步，避免跨弧快进。
    beats 以 10 个节拍为主，后续你也可以再手动细化/替换。
    """
    n = (name or "").strip()
    s = (summary or "").strip()

    # 通用骨架（不依赖具体设定）
    beats: list[dict[str, str]] = [
        {"goal": "立下阶段目标与底线", "conflict": "规则/代价初次显形", "hook": "出现一个不可忽视的异常线索"},
        {"goal": "锁定一个可执行的小目标", "conflict": "第一次行动受阻", "hook": "线索指向更大的局"},
        {"goal": "用交易/规则推进一步", "conflict": "资源不足或信息误读", "hook": "必须付出代价换证据"},
        {"goal": "验证线索真伪", "conflict": "关系摩擦或内部阻碍", "hook": "暴露一个新的风险点"},
        {"goal": "拿到关键拼图的一角", "conflict": "对手先手/局内掣肘", "hook": "被迫改计划"},
        {"goal": "第二次尝试（更接近真相）", "conflict": "代价递增（失去/暴露/欠债）", "hook": "留下‘未完结线’"},
        {"goal": "阶段性对抗/破局", "conflict": "胜利不完整、留下伤口", "hook": "更大的敌意或诅咒降临"},
        {"goal": "善后与追责", "conflict": "后果落地（通缉/名声/污染）", "hook": "新任务或新期限"},
        {"goal": "局势升级（更高层规则出现）", "conflict": "必须做艰难选择", "hook": "选择带来不可逆后果"},
        {"goal": "本卷小高潮/转折", "conflict": "赢了但更像输了", "hook": "自然引入下一卷入口"},
    ]

    # 轻定制：让节拍更贴合每卷摘要关键词（仍保持宽松）
    if "迷雾" in n or "初醒" in n:
        beats[0]["hook"] = "触发厉鬼/规则的开局异常"
        beats[1]["goal"] = "摸清一条杀人规律（只摸到一半）"
        beats[6]["goal"] = "完成第一场‘鬼对鬼’破局（险胜）"
        beats[9]["hook"] = "正式入局：被收编/被盯上/被迫站队"
    if "深渊" in n or "凝视" in n:
        beats[0]["hook"] = "出现‘水/声音’相关的反常迹象"
        beats[4]["conflict"] = "对手组织或内斗逼近"
        beats[9]["goal"] = "本卷高潮：被迫拼接/融合，污染上升"
        beats[9]["hook"] = "力量变强，但人性/记忆出现裂口"
    if "百花" in n:
        beats[0]["hook"] = "大型公共事件变成灵异场域"
        beats[5]["goal"] = "多方势力混战中拿到关键线索"
        beats[9]["hook"] = "揭示更古老的周期性/祭坛真相"
    if "历史" in n or "修正" in n:
        beats[0]["hook"] = "出现可篡改叙事/历史的‘媒介’"
        beats[3]["goal"] = "在幻境/文本里验证真相碎片"
        beats[9]["hook"] = "获得‘规则层’能力，但代价更重"
    if "无间" in n or "地狱" in n:
        beats[2]["conflict"] = "城市级崩坏，普通规则失效"
        beats[6]["goal"] = "全面战争中守住一个关键底线"
        beats[9]["goal"] = "本卷悲剧性转折：牺牲/异变/封印人性"
    if "第零" in n or "法则" in n:
        beats[0]["goal"] = "收集终局所需的最后筹码"
        beats[4]["goal"] = "理解‘鬼’的本质与世界底层逻辑"
        beats[9]["goal"] = "终局对决：定义新规则"
        beats[9]["hook"] = "尾声：胜利的代价被看见"

    # 兜底：若摘要为空，仍给通用节拍
    if not s:
        return beats
    return beats


def _auto_fill_framework_arcs(framework: dict[str, Any], *, fill_beats: bool) -> dict[str, Any]:
    arcs = framework.get("arcs")
    if not isinstance(arcs, list):
        return framework
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        # 1) from/to：优先现有字段，否则从 chapters/chapter_range 解析
        lo = arc.get("from_chapter") or arc.get("from")
        hi = arc.get("to_chapter") or arc.get("to")
        lo_i = lo if isinstance(lo, int) else None
        hi_i = hi if isinstance(hi, int) else None
        if lo_i is None or hi_i is None:
            rng = arc.get("chapter_range") or arc.get("chapters") or arc.get("chapter_nos")
            rlo, rhi = _parse_range_text(rng)
            if lo_i is None and isinstance(rlo, int):
                arc["from_chapter"] = rlo
            if hi_i is None and isinstance(rhi, int):
                arc["to_chapter"] = rhi

        # 2) chapter_range：若缺失，补一个文本范围（便于人读）
        if not arc.get("chapter_range"):
            rlo = arc.get("from_chapter")
            rhi = arc.get("to_chapter")
            if isinstance(rlo, int) and isinstance(rhi, int):
                arc["chapter_range"] = f"{rlo}-{rhi}"

        # 3) beats：若缺失且允许自动填充
        if fill_beats and not (arc.get("beats") or arc.get("outline")):
            name = str(arc.get("title") or arc.get("name") or "").strip()
            summary = str(arc.get("summary") or "").strip()
            arc["beats"] = _default_beats_for_arc(name, summary)
    return framework


@router.post("/{novel_id}/framework/update")
def update_framework(
    novel_id: str, body: FrameworkUpdateBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    try:
        fw = json.loads(body.framework_json)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"framework_json 不是合法 JSON：{e}") from e
    if not isinstance(fw, dict):
        raise HTTPException(400, "framework_json 顶层必须是 JSON 对象")

    if body.auto_fill_arcs:
        fw = _auto_fill_framework_arcs(fw, fill_beats=bool(body.auto_fill_beats))

    n.framework_json = json.dumps(fw, ensure_ascii=False)
    if body.framework_markdown is not None:
        n.framework_markdown = body.framework_markdown
    db.commit()
    return {
        "status": "ok",
        "framework_confirmed": n.framework_confirmed,
        "framework_json_chars": len(n.framework_json or ""),
        "arcs_count": len(fw.get("arcs") or []) if isinstance(fw.get("arcs"), list) else 0,
    }


@router.get("/{novel_id}/chapters")
def list_chapters(novel_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_no.asc(), Chapter.updated_at.desc())
        .all()
    )
    # 同章号优先展示 approved；否则展示最新一条，避免目录里出现重复章号
    chosen: dict[int, Chapter] = {}
    for c in rows:
        old = chosen.get(c.chapter_no)
        if old is None:
            chosen[c.chapter_no] = c
            continue
        if old.status != "approved" and c.status == "approved":
            chosen[c.chapter_no] = c
    uniq_rows = [chosen[k] for k in sorted(chosen.keys())]
    return [
        {
            "id": c.id,
            "chapter_no": c.chapter_no,
            "title": c.title,
            "content": c.content,
            "pending_content": c.pending_content,
            "pending_revision_prompt": c.pending_revision_prompt,
            "status": c.status,
            "source": c.source,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in uniq_rows
    ]


@router.post("/{novel_id}/chapters/generate")
async def generate_chapters(
    novel_id: str, body: GenerateChapterBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    started = time.perf_counter()
    batch_id = f"gen-{int(time.time())}-{novel_id[:8]}"
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    if not n.framework_confirmed:
        raise HTTPException(400, "请先确认小说框架后再生成章节")
    mem = latest_memory_json(db, novel_id)
    llm = NovelLLMService()
    created: list[str] = []
    base_no = next_chapter_no_from_approved(db, novel_id)
    if body.chapter_no is not None:
        # 指定章：只生成这一章
        if body.count != 1:
            raise HTTPException(400, "指定 chapter_no 时 count 必须为 1")
        base_no = int(body.chapter_no)
    do_consistency_check = bool(body.auto_consistency_check)
    logger.info(
        "generate_chapters start | novel_id=%s title=%r count=%s base_no=%s cold_recall=%s cold_items=%s consistency_check=%s mem_chars=%s",
        novel_id,
        n.title,
        body.count,
        base_no,
        body.use_cold_recall,
        body.cold_recall_items,
        do_consistency_check,
        len(mem or ""),
    )
    _append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="batch_start",
        message=f"开始生成 {body.count} 章（从第 {base_no} 章起）",
        meta={
            "count": body.count,
            "base_no": base_no,
            "use_cold_recall": body.use_cold_recall,
            "cold_recall_items": body.cold_recall_items,
            "consistency_check": do_consistency_check,
        },
    )
    try:
        for idx in range(body.count):
            step_start = time.perf_counter()
            continuity = format_continuity_excerpts(db, novel_id, approved_only=True)
            full_context = format_recent_approved_fulltext_context(
                db,
                novel_id,
                max_chapters=max(1, settings.novel_recent_full_context_chapters),
            )
            no = base_no + idx
            # 若存在章计划，注入本章计划作为强约束（按卷驱动）
            chapter_plan_hint = ""
            plan = (
                db.query(NovelChapterPlan)
                .filter(NovelChapterPlan.novel_id == novel_id, NovelChapterPlan.chapter_no == no)
                .order_by(NovelChapterPlan.updated_at.desc())
                .first()
            )
            if plan:
                try:
                    beats = json.loads(plan.beats_json or "{}")
                except Exception:
                    beats = {}
                try:
                    added = json.loads(plan.open_plots_intent_added_json or "[]")
                except Exception:
                    added = []
                try:
                    resolved = json.loads(plan.open_plots_intent_resolved_json or "[]")
                except Exception:
                    resolved = []
                chapter_plan_hint = _build_chapter_plan_hint(
                    no, plan.chapter_title, beats, added, resolved
                )
            logger.info(
                "generate_chapters step start | novel_id=%s chapter_no=%s idx=%s/%s continuity_chars=%s",
                novel_id,
                no,
                idx + 1,
                body.count,
                len(continuity or ""),
            )
            _append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="chapter_start",
                chapter_no=no,
                message=f"第 {no} 章开始生成（{idx + 1}/{body.count}）",
                meta={"continuity_chars": len(continuity or "")},
            )
            raw_content = await llm.generate_chapter(
                n,
                no,
                (plan.chapter_title if plan and plan.chapter_title else body.title_hint),
                mem,
                continuity,
                full_context,
                chapter_plan_hint=chapter_plan_hint,
                db=db,
                use_cold_recall=body.use_cold_recall,
                cold_recall_items=body.cold_recall_items,
            )
            content = raw_content
            draft_metrics = chapter_content_metrics(raw_content)
            logger.info(
                "generate_chapters step draft done | novel_id=%s chapter_no=%s raw_chars=%s body_chars=%s paragraphs=%s",
                novel_id,
                no,
                len(raw_content or ""),
                draft_metrics["body_chars"],
                draft_metrics["paragraph_count"],
            )
            _append_generation_log(
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
            if do_consistency_check:
                try:
                    content = await llm.check_and_fix_chapter(
                        n, no, body.title_hint, mem, continuity, raw_content, db=db
                    )
                    fixed_metrics = chapter_content_metrics(content)
                    logger.info(
                        "generate_chapters step consistency done | novel_id=%s chapter_no=%s fixed_chars=%s body_chars=%s paragraphs=%s",
                        novel_id,
                        no,
                        len(content or ""),
                        fixed_metrics["body_chars"],
                        fixed_metrics["paragraph_count"],
                    )
                    _append_generation_log(
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
                except Exception:
                    logger.exception(
                        "generate_chapters step consistency failed, fallback raw | novel_id=%s chapter_no=%s",
                        novel_id,
                        no,
                    )
                    _append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_consistency_failed",
                        chapter_no=no,
                        level="error",
                        message=f"第 {no} 章一致性修订失败，已回退初稿",
                    )
                    content = raw_content
            normalized_title, normalized_content = _ensure_chapter_heading(
                no, content, title_hint=body.title_hint
            )
            content = normalized_content
            try:
                memory_delta_result = await llm.propose_memory_update_from_chapter(
                    n,
                    chapter_no=no,
                    chapter_title=normalized_title,
                    chapter_text=content,
                    prev_memory=mem,
                    db=db,
                )
                if memory_delta_result.get("ok"):
                    mem = str(memory_delta_result.get("payload_json") or mem)
                    _append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_memory_delta_applied",
                        chapter_no=no,
                        message=f"第 {no} 章工作记忆已更新",
                        meta=memory_delta_result.get("stats") or {},
                    )
                else:
                    _append_generation_log(
                        db,
                        novel_id=novel_id,
                        batch_id=batch_id,
                        event="chapter_memory_delta_failed",
                        chapter_no=no,
                        level="error",
                        message=f"第 {no} 章工作记忆更新失败，已保留旧记忆",
                        meta={"errors": memory_delta_result.get("errors") or []},
                    )
            except Exception:
                logger.exception(
                    "generate_chapters memory delta failed | novel_id=%s chapter_no=%s",
                    novel_id,
                    no,
                )
                _append_generation_log(
                    db,
                    novel_id=novel_id,
                    batch_id=batch_id,
                    event="chapter_memory_delta_failed",
                    chapter_no=no,
                    level="error",
                    message=f"第 {no} 章工作记忆更新异常，已保留旧记忆",
                )
            saved_metrics = chapter_content_metrics(content)
            ch = (
                db.query(Chapter)
                .filter(Chapter.novel_id == novel_id, Chapter.chapter_no == no)
                .order_by(Chapter.updated_at.desc())
                .first()
            )
            if ch and ch.status != "approved":
                ch.title = normalized_title
                ch.content = content
                ch.pending_content = ""
                ch.pending_revision_prompt = ""
                ch.status = "pending_review"
                ch.source = "manual"
            else:
                ch = Chapter(
                    novel_id=novel_id,
                    chapter_no=no,
                    title=normalized_title,
                    content=content,
                    status="pending_review",
                    source="manual",
                )
                db.add(ch)
                db.flush()
            created.append(ch.id)
            logger.info(
                "generate_chapters step saved | novel_id=%s chapter_no=%s chapter_id=%s body_chars=%s paragraphs=%s elapsed=%.2fs",
                novel_id,
                no,
                ch.id,
                saved_metrics["body_chars"],
                saved_metrics["paragraph_count"],
                time.perf_counter() - step_start,
            )
            _append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="chapter_saved",
                chapter_no=no,
                message=f"第 {no} 章已保存（待审，正文约 {saved_metrics['body_chars']} 字）",
                meta={
                    "chapter_id": ch.id,
                    **saved_metrics,
                    "elapsed_seconds": round(time.perf_counter() - step_start, 2),
                },
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "generate_chapters failed | novel_id=%s count=%s elapsed=%.2fs",
            novel_id,
            body.count,
            time.perf_counter() - started,
        )
        try:
            _append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="batch_failed",
                level="error",
                message="批量生成失败，请查看服务日志堆栈",
                meta={"elapsed_seconds": round(time.perf_counter() - started, 2)},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise
    _append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="batch_done",
        message=f"批量生成完成，共 {len(created)} 章",
        meta={"elapsed_seconds": round(time.perf_counter() - started, 2)},
    )
    db.commit()
    logger.info(
        "generate_chapters done | novel_id=%s count=%s created=%s elapsed=%.2fs",
        novel_id,
        body.count,
        len(created),
        time.perf_counter() - started,
    )
    return {"chapter_ids": created, "batch_id": batch_id}


@router.post("/chapters/{chapter_id}/consistency-fix")
async def consistency_fix_chapter(
    chapter_id: str, db: Session = Depends(get_db)
) -> dict[str, str]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    n = db.get(Novel, c.novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    if not n.framework_confirmed:
        raise HTTPException(400, "请先确认小说框架")
    if not (c.content or "").strip():
        raise HTTPException(400, "当前无正式正文，无法一致性修订")

    llm = NovelLLMService()
    mem = latest_memory_json(db, c.novel_id)
    continuity = format_continuity_excerpts(db, c.novel_id, approved_only=True)
    try:
        fixed_text = await llm.check_and_fix_chapter(
            n, c.chapter_no, c.title or "", mem, continuity, c.content, db=db
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e

    c.pending_content = fixed_text
    c.pending_revision_prompt = "一致性修订（手动触发）"
    c.status = "pending_review"
    db.commit()
    return {"status": "ok"}


@router.get("/{novel_id}/generation-logs")
def list_generation_logs(
    novel_id: str,
    db: Session = Depends(get_db),
    batch_id: str | None = None,
    level: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    lim = max(1, min(limit, 500))
    q = db.query(NovelGenerationLog).filter(NovelGenerationLog.novel_id == novel_id)
    if batch_id:
        q = q.filter(NovelGenerationLog.batch_id == batch_id)
    if level:
        q = q.filter(NovelGenerationLog.level == level)
    rows = q.order_by(NovelGenerationLog.created_at.desc()).limit(lim).all()
    out = []
    for r in reversed(rows):
        try:
            meta = json.loads(r.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        out.append(
            {
                "id": r.id,
                "batch_id": r.batch_id,
                "level": r.level,
                "event": r.event,
                "chapter_no": r.chapter_no,
                "message": r.message,
                "meta": meta,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    latest_batch_id = out[-1]["batch_id"] if out else None
    # 记忆刷新批次状态摘要（供前端进度条）
    all_rows = (
        db.query(NovelGenerationLog)
        .filter(NovelGenerationLog.novel_id == novel_id)
        .order_by(NovelGenerationLog.created_at.desc())
        .limit(1000)
        .all()
    )
    latest_refresh_batch_id: str | None = None
    for r in all_rows:
        if (r.event or "").startswith("memory_refresh_"):
            latest_refresh_batch_id = r.batch_id
            break

    refresh_status = "idle"
    refresh_progress = 0
    refresh_last_message = ""
    refresh_updated_at: str | None = None
    refresh_started_at: str | None = None
    refresh_elapsed_seconds: int | None = None
    latest_refresh_success_version: int | None = None
    if latest_refresh_batch_id:
        rb = (
            db.query(NovelGenerationLog)
            .filter(
                NovelGenerationLog.novel_id == novel_id,
                NovelGenerationLog.batch_id == latest_refresh_batch_id,
            )
            .order_by(NovelGenerationLog.created_at.asc())
            .all()
        )
        events = {x.event for x in rb}
        last_row = rb[-1] if rb else None
        started_row = next((x for x in rb if x.event == "memory_refresh_started"), None)
        if started_row and started_row.created_at:
            refresh_started_at = started_row.created_at.isoformat()
        if started_row and started_row.created_at and last_row and last_row.created_at:
            refresh_elapsed_seconds = max(
                0, int((last_row.created_at - started_row.created_at).total_seconds())
            )
        refresh_last_message = (last_row.message if last_row else "") or ""
        refresh_updated_at = (
            last_row.created_at.isoformat() if last_row and last_row.created_at else None
        )
        done_row = next((x for x in reversed(rb) if x.event == "memory_refresh_done"), None)
        if done_row:
            try:
                done_meta = json.loads(done_row.meta_json or "{}")
            except json.JSONDecodeError:
                done_meta = {}
            ver = done_meta.get("version")
            if isinstance(ver, int):
                latest_refresh_success_version = ver
        if "memory_refresh_failed" in events or "memory_refresh_validation_failed" in events:
            refresh_status = "failed"
            refresh_progress = 100
        elif "memory_refresh_done" in events:
            refresh_status = "done"
            refresh_progress = 100
        elif "memory_refresh_started" in events:
            refresh_status = "started"
            refresh_progress = 60
        elif "memory_refresh_queued" in events:
            refresh_status = "queued"
            refresh_progress = 25
        else:
            refresh_status = "idle"
            refresh_progress = 0

    return {
        "items": out,
        "latest_batch_id": latest_batch_id,
        "latest_refresh_batch_id": latest_refresh_batch_id,
        "refresh_status": refresh_status,
        "refresh_progress": refresh_progress,
        "refresh_last_message": refresh_last_message,
        "refresh_updated_at": refresh_updated_at,
        "refresh_started_at": refresh_started_at,
        "refresh_elapsed_seconds": refresh_elapsed_seconds,
        "latest_refresh_success_version": latest_refresh_success_version,
    }


@router.post("/chapters/{chapter_id}/revise")
async def revise_chapter(
    chapter_id: str, body: ChapterReviseBody, db: Session = Depends(get_db)
) -> dict[str, str]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    n = db.get(Novel, c.novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    if not n.framework_confirmed:
        raise HTTPException(400, "请先确认小说框架")
    if not (c.content or "").strip():
        raise HTTPException(400, "当前无正式正文，无法按意见改稿")
    mem = latest_memory_json(db, c.novel_id)
    fbs = (
        db.query(ChapterFeedback)
        .filter(ChapterFeedback.chapter_id == chapter_id)
        .order_by(ChapterFeedback.created_at.asc())
        .all()
    )
    bodies = [x.body for x in fbs]
    llm = NovelLLMService()
    try:
        new_text = await llm.revise_chapter(
            n, c, mem, bodies, body.user_prompt.strip(), db=db
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    c.pending_content = new_text
    c.pending_revision_prompt = body.user_prompt.strip()
    c.status = "pending_review"
    db.commit()
    return {"status": "ok"}


@router.post("/chapters/{chapter_id}/apply-revision")
async def apply_chapter_revision(
    chapter_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    if not (c.pending_content or "").strip():
        raise HTTPException(400, "暂无待确认的修订稿")
    c.content = c.pending_content
    c.pending_content = ""
    c.pending_revision_prompt = ""
    refresh_status = "none"
    refresh_task_id: str | None = None
    refresh_batch_id: str | None = None
    if c.status == "approved":
        refresh_status, refresh_task_id, refresh_batch_id = _enqueue_auto_refresh_memory_from_approved(
            db, c.novel_id, reason="后台自动合并：已审定章节应用修订后同步记忆"
        )
    db.commit()
    return {
        "status": "ok",
        "memory_refresh_status": refresh_status,
        "memory_refresh_task_id": refresh_task_id,
        "memory_refresh_batch_id": refresh_batch_id,
    }


@router.post("/chapters/{chapter_id}/discard-revision")
def discard_chapter_revision(chapter_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    c.pending_content = ""
    c.pending_revision_prompt = ""
    db.commit()
    return {"status": "ok"}


@router.post("/chapters/{chapter_id}/feedback")
def add_feedback(
    chapter_id: str, body: ChapterFeedbackBody, db: Session = Depends(get_db)
) -> dict[str, str]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    fb = ChapterFeedback(chapter_id=chapter_id, body=body.body)
    db.add(fb)
    c.status = "pending_review"
    db.commit()
    return {"id": fb.id}


@router.post("/chapters/{chapter_id}/approve")
async def approve_chapter(chapter_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    n = db.get(Novel, c.novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    if settings.novel_setting_audit_on_approve:
        llm_audit = NovelLLMService()
        audit = llm_audit.audit_chapter_against_constraints_sync(
            n, c.content or "", db
        )
        if not audit.get("ok") and settings.novel_setting_audit_block_on_violation:
            raise HTTPException(
                400,
                "设定审计未通过："
                + "；".join(audit.get("violations") or [])[:2000],
            )
    c.status = "approved"
    c.pending_content = ""
    c.pending_revision_prompt = ""
    # 同章号只保留当前这条（避免出现「第1章 pending + 第1章 approved」并存）
    dups = (
        db.query(Chapter)
        .filter(
            Chapter.novel_id == c.novel_id,
            Chapter.chapter_no == c.chapter_no,
            Chapter.id != c.id,
        )
        .all()
    )
    for d in dups:
        db.delete(d)
    incremental_memory_status = "none"
    incremental_memory_version: int | None = None
    approve_batch_id = f"chapter-approve-{int(time.time())}-{c.novel_id[:8]}"
    try:
        prev_memory = latest_memory_json(db, c.novel_id)
        llm = NovelLLMService()
        delta_result = await llm.propose_memory_update_from_chapter(
            n,
            chapter_no=c.chapter_no,
            chapter_title=c.title or "",
            chapter_text=c.content or "",
            prev_memory=prev_memory,
            db=db,
        )
        if delta_result.get("ok"):
            incremental_memory_status = "applied"
            incremental_memory_version = delta_result.get("version") # NovelLLMService should return this if possible
            # 如果 result 没返回 version，我们自己查一下最新的
            if not incremental_memory_version:
                incremental_memory_version = db.query(func.max(NovelMemory.version)).filter(
                    NovelMemory.novel_id == c.novel_id
                ).scalar()

            _append_generation_log(
                db,
                novel_id=c.novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_applied",
                chapter_no=c.chapter_no,
                message=f"第 {c.chapter_no} 章审定后已增量写入规范化存储 v{incremental_memory_version}",
                meta={
                    **(delta_result.get("stats") or {}),
                    "memory_version": incremental_memory_version,
                    "source": "approve_chapter",
                },
            )
        else:
            incremental_memory_status = "failed"
            _append_generation_log(
                db,
                novel_id=c.novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_failed",
                chapter_no=c.chapter_no,
                level="error",
                message=f"第 {c.chapter_no} 章审定后增量写入记忆失败，已保留旧记忆",
                meta={
                    "errors": delta_result.get("errors") or [],
                    "source": "approve_chapter",
                },
            )
    except Exception:
        incremental_memory_status = "failed"
        logger.exception(
            "approve_chapter memory delta failed | chapter_id=%s novel_id=%s chapter_no=%s",
            chapter_id,
            c.novel_id,
            c.chapter_no,
        )
        _append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=approve_batch_id,
            event="chapter_memory_delta_failed",
            chapter_no=c.chapter_no,
            level="error",
            message=f"第 {c.chapter_no} 章审定后增量写入记忆异常，已保留旧记忆",
            meta={"source": "approve_chapter"},
        )
    # 审定已通过单章增量写入正式记忆；不再自动排队「最近 N 章」批量刷新，避免重复调用。
    # 需要跨章对齐或补漏时在记忆页手动刷新（或编辑/删除已审定章仍会触发后台刷新）。
    db.commit()
    consolidate_memory_task_id: str | None = None
    n_every = max(0, int(settings.novel_memory_consolidate_every_n_chapters or 0))
    if n_every > 0 and c.chapter_no > 0 and c.chapter_no % n_every == 0:
        try:
            t = novel_consolidate_memory.delay(c.novel_id)
            consolidate_memory_task_id = getattr(t, "id", None)
        except Exception:
            logger.exception(
                "enqueue novel.consolidate_memory failed | novel_id=%s chapter_no=%s",
                c.novel_id,
                c.chapter_no,
            )
    return {
        "status": "ok",
        "incremental_memory_status": incremental_memory_status,
        "incremental_memory_version": incremental_memory_version,
        "incremental_memory_batch_id": approve_batch_id,
        "memory_refresh_status": "none",
        "memory_refresh_task_id": None,
        "memory_refresh_batch_id": None,
        "consolidate_memory_task_id": consolidate_memory_task_id,
    }


@router.patch("/chapters/{chapter_id}")
async def patch_chapter(
    chapter_id: str, body: ChapterUpdateBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    if body.title is not None:
        c.title = body.title.strip() or c.title
    c.content = body.content
    c.pending_content = ""
    c.pending_revision_prompt = ""
    refresh_status = "none"
    refresh_task_id: str | None = None
    refresh_batch_id: str | None = None
    if c.status == "approved":
        refresh_status, refresh_task_id, refresh_batch_id = _enqueue_auto_refresh_memory_from_approved(
            db, c.novel_id, reason="后台自动合并：手动编辑已审定章节后同步记忆"
        )
    db.commit()
    return {
        "status": "ok",
        "memory_refresh_status": refresh_status,
        "memory_refresh_task_id": refresh_task_id,
        "memory_refresh_batch_id": refresh_batch_id,
    }


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")

    is_approved = c.status == "approved"
    novel_id = c.novel_id
    chapter_no = c.chapter_no
    refresh_status = "none"
    refresh_task_id: str | None = None
    refresh_batch_id: str | None = None

    db.delete(c)
    if is_approved:
        refresh_status, refresh_task_id, refresh_batch_id = _enqueue_auto_refresh_memory_from_approved(
            db, novel_id, reason="后台自动合并：删除已审定章节后同步记忆"
        )
    db.commit()
    return {
        "status": "ok",
        "deleted_chapter_id": chapter_id,
        "deleted_chapter_no": chapter_no,
        "was_approved": is_approved,
        "memory_refresh_status": refresh_status,
        "memory_refresh_task_id": refresh_task_id,
        "memory_refresh_batch_id": refresh_batch_id,
    }


@router.get("/{novel_id}/memory")
def get_memory(novel_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    if not row:
        empty = "{}"
        return {
            "version": 0,
            "payload_json": empty,
            "readable_zh": memory_payload_to_readable_zh(empty),
            "readable_zh_auto": memory_payload_readable_zh_auto(empty),
            "has_readable_override": False,
            "summary": "",
        }
    pj = row.payload_json
    try:
        parsed = json.loads(pj or "{}")
    except json.JSONDecodeError:
        parsed = {}
    has_override = (
        isinstance(parsed, dict)
        and isinstance(parsed.get("readable_zh_override"), str)
        and (parsed.get("readable_zh_override") or "").strip() != ""
    )
    
    # 规范化表为真源；仅当尚无结构化行且存在 JSON 时，从快照补建一次（旧数据迁移）
    normalized = normalized_memory_to_dict(db, novel_id)
    if normalized is None and pj and pj != "{}":
        try:
            replace_normalized_from_payload(db, novel_id, row.version, pj)
            db.commit()
            normalized = normalized_memory_to_dict(db, novel_id)
        except Exception:
            logger.exception("Failed to auto-bootstrap normalized memory in get_memory")

    return {
        "version": row.version,
        "payload_json": pj,
        "readable_zh": memory_payload_to_readable_zh(pj),
        "readable_zh_auto": memory_payload_readable_zh_auto(pj),
        "has_readable_override": has_override,
        "summary": row.summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "normalized": normalized,
    }


@router.get("/{novel_id}/memory/normalized")
def get_memory_normalized(novel_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """规范化落表后的记忆分块（真源）；表空时从最新快照补建一次（迁移/兼容）。"""
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    data = normalized_memory_to_dict(db, novel_id)
    if data is None:
        mem_row = (
            db.query(NovelMemory)
            .filter(NovelMemory.novel_id == novel_id)
            .order_by(NovelMemory.version.desc())
            .first()
        )
        if not mem_row:
            return {"status": "empty", "data": None}
        replace_normalized_from_payload(
            db, novel_id, mem_row.version, mem_row.payload_json or "{}"
        )
        db.commit()
        data = normalized_memory_to_dict(db, novel_id)
    return {"status": "ok", "data": data}


@router.post("/{novel_id}/memory/rebuild-normalized")
def rebuild_memory_normalized(novel_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    灾难恢复/导入：用当前最新快照 JSON 覆盖并重写规范化表，再派生新快照与分表对齐。
    日常请以结构化数据为准；勿与「仅改快照」混用。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    mem_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    if not mem_row:
        raise HTTPException(400, "尚无记忆快照可同步")
    next_ver = mem_row.version + 1
    replace_normalized_from_payload(
        db, novel_id, next_ver, mem_row.payload_json or "{}"
    )
    sync_json_snapshot_from_normalized(
        db, novel_id, summary="从快照导入后派生快照（与结构化对齐）"
    )
    db.commit()
    data = normalized_memory_to_dict(db, novel_id)
    return {"status": "ok", "data": data}


@router.post("/{novel_id}/memory/save")
def save_memory_payload(
    novel_id: str, body: MemorySaveBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    人工保存记忆（API）：先写入规范化表，再由分表派生 NovelMemory 快照。
    - payload_json：整包导入为真源并重建分表
    - readable_zh_override：合并进待生成快照（经 sync 保留）
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(400, "请至少提供 payload_json 或 readable_zh_override")

    mem_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    prev_json = mem_row.payload_json if mem_row else "{}"
    try:
        payload = json.loads(prev_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    summary_bits: list[str] = []

    if "payload_json" in patch:
        raw = patch["payload_json"]
        if raw is None or not str(raw).strip():
            raise HTTPException(400, "payload_json 不能为空")
        try:
            new_payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"payload_json 不是合法 JSON：{e}") from e
        if not isinstance(new_payload, dict):
            raise HTTPException(400, "payload_json 顶层必须是 JSON 对象")
        payload = new_payload
        summary_bits.append("payload")

    if "readable_zh_override" in patch:
        ov = patch["readable_zh_override"]
        if ov is None or (isinstance(ov, str) and not ov.strip()):
            payload.pop("readable_zh_override", None)
        else:
            payload["readable_zh_override"] = str(ov).strip()
        summary_bits.append("中文阅读")

    new_json = json.dumps(payload, ensure_ascii=False)
    ver = (
        db.query(func.max(NovelMemory.version))
        .filter(NovelMemory.novel_id == novel_id)
        .scalar()
        or 0
    )
    new_ver = ver + 1
    replace_normalized_from_payload(db, novel_id, new_ver, new_json)
    snap_ver = sync_json_snapshot_from_normalized(
        db,
        novel_id,
        summary="人工保存：" + ("+".join(summary_bits) if summary_bits else "记忆"),
    )
    db.commit()
    out_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    out_json = out_row.payload_json if out_row else new_json
    try:
        out_p = json.loads(out_json or "{}")
    except json.JSONDecodeError:
        out_p = {}
    return {
        "version": snap_ver or (out_row.version if out_row else new_ver),
        "payload_json": out_json,
        "readable_zh": memory_payload_to_readable_zh(out_json),
        "readable_zh_auto": memory_payload_readable_zh_auto(out_json),
        "has_readable_override": bool(
            isinstance(out_p.get("readable_zh_override"), str)
            and (out_p.get("readable_zh_override") or "").strip() != ""
        ),
    }


@router.post("/{novel_id}/memory/sync-json")
def trigger_sync_json_snapshot(
    novel_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    手动触发：将规范化存储中的数据反向同步到 NovelMemory (JSON 快照) 中。
    """
    task = novel_sync_json_snapshot.delay(novel_id)
    return {"status": "queued", "task_id": getattr(task, "id", None)}


@router.post("/{novel_id}/memory/consolidate")
def trigger_memory_consolidate(
    novel_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    手动触发：后台记忆压缩（早期章节 key_facts → timeline_archive，并裁剪过久条目）。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    task = novel_consolidate_memory.delay(novel_id)
    return {"status": "queued", "task_id": getattr(task, "id", None)}


@router.get("/{novel_id}/metrics")
def get_novel_metrics(novel_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    观察指标仪表盘数据：
    - 指标：open_plots / canonical_timeline 覆盖、章节状态分布、连续性简评
    - 当前设定：连贯性策略与一致性核对开关/温度（只返回非敏感配置）
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")

    chapters: list[Chapter] = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_no.asc())
        .all()
    )
    approved = [c for c in chapters if c.status == "approved"]
    pending_review = [c for c in chapters if c.status == "pending_review"]

    # 最近两条“已审定章节”用于连续性启发式判断
    approved_nos = [c.chapter_no for c in approved if c.chapter_no is not None]
    approved_nos_sorted = sorted(approved_nos)
    last_two = approved_nos_sorted[-2:]
    is_consecutive = (
        len(last_two) == 2 and (last_two[1] - last_two[0]) == 1
    )  # 简单启发式

    mem_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    payload_json = mem_row.payload_json if mem_row else "{}"
    memory_version = mem_row.version if mem_row else 0

    data: dict[str, Any] = {}
    try:
        parsed = json.loads(payload_json or "{}")
        if isinstance(parsed, dict):
            data = parsed
    except json.JSONDecodeError:
        data = {}

    def _count_open_plots(op: Any) -> tuple[int, list[str]]:
        if op is None or op == "" or op == []:
            return 0, []
        if isinstance(op, list):
            preview: list[str] = []
            for x in op[:6]:
                preview.append(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))
            return len(op), preview
        if isinstance(op, str):
            return 1, [op]
        return 1, [json.dumps(op, ensure_ascii=False)]

    open_plots_count, open_plots_preview = _count_open_plots(data.get("open_plots"))
    open_plots_editable: list[str] = []
    try:
        op_raw = data.get("open_plots")
        if isinstance(op_raw, list):
            for x in op_raw:
                if isinstance(x, str):
                    if x.strip():
                        open_plots_editable.append(x.strip())
                else:
                    open_plots_editable.append(
                        json.dumps(x, ensure_ascii=False)[:200]
                    )
        elif isinstance(op_raw, str):
            if op_raw.strip():
                open_plots_editable = [op_raw.strip()]
    except Exception:
        open_plots_editable = open_plots_preview

    canonical = data.get("canonical_timeline")
    canonical_count = len(canonical) if isinstance(canonical, list) else 0

    canonical_last_chapter_no = None
    canonical_preview: list[str] = []
    canonical_last_editable = {
        "key_facts": [],
        "causal_results": [],
        "open_plots_added": [],
        "open_plots_resolved": [],
    }
    canonical_last_resolved_n = 0
    canonical_last_added_n = 0
    if isinstance(canonical, list):
        last_cn: int | None = None
        for x in canonical:
            if isinstance(x, dict):
                cn = x.get("chapter_no")
                if isinstance(cn, int):
                    last_cn = cn
        canonical_last_chapter_no = last_cn

        # 末尾预览：用于前端可视化展示（限制长度，避免太长）
        def _to_str_list(v: Any, limit: int) -> list[str]:
            if isinstance(v, list):
                out: list[str] = []
                for i in v[:limit]:
                    if isinstance(i, str):
                        if i.strip():
                            out.append(i.strip()[:120])
                    else:
                        try:
                            out.append(json.dumps(i, ensure_ascii=False)[:120])
                        except Exception:
                            pass
                return out
            return []

        for x in canonical[-5:]:
            if isinstance(x, dict):
                cn = x.get("chapter_no")
                title = x.get("chapter_title")
                key_facts = _to_str_list(x.get("key_facts"), 3)
                causal_results = _to_str_list(x.get("causal_results"), 2)
                added = _to_str_list(x.get("open_plots_added"), 2)
                resolved = _to_str_list(x.get("open_plots_resolved"), 2)
                head = f"第{cn}章" if isinstance(cn, int) else "时间线条目"
                if isinstance(title, str) and title.strip():
                    head += f"《{title.strip()[:40]}》"
                bits: list[str] = []
                if key_facts:
                    bits.append("关键：" + "；".join(key_facts))
                if causal_results:
                    bits.append("因果：" + "；".join(causal_results))
                if added:
                    bits.append("新增坑：" + "；".join(added))
                if resolved:
                    bits.append("收束：" + "；".join(resolved))
                canonical_preview.append(head + ("（" + "｜".join(bits) + "）" if bits else ""))
            elif isinstance(x, str) and x.strip():
                canonical_preview.append(x.strip()[:160])

        # 最近一条可编辑字段：表单只改这一条，尽量降低风险
        last_item = canonical[-1] if canonical else None
        if isinstance(last_item, dict):
            def _read_str_arr(key: str, limit: int) -> list[str]:
                v = last_item.get(key)
                if isinstance(v, list):
                    out: list[str] = []
                    for i in v[:limit]:
                        if isinstance(i, str) and i.strip():
                            out.append(i.strip())
                        elif not isinstance(i, str):
                            try:
                                out.append(json.dumps(i, ensure_ascii=False)[:200])
                            except Exception:
                                continue
                    return out
                return []

            canonical_last_editable = {
                "key_facts": _read_str_arr("key_facts", 80),
                "causal_results": _read_str_arr("causal_results", 80),
                "open_plots_added": _read_str_arr("open_plots_added", 80),
                "open_plots_resolved": _read_str_arr(
                    "open_plots_resolved", 80
                ),
            }
            canonical_last_added_n = len(canonical_last_editable.get("open_plots_added") or [])
            canonical_last_resolved_n = len(
                canonical_last_editable.get("open_plots_resolved") or []
            )

    # 节奏对齐：基于 framework_json.arcs 推导当前弧线（以“下一章”作为写作目标）
    next_no = next_chapter_no_from_approved(db, novel_id)
    arc = _select_arc_for_chapter(n.framework_json or "", next_no)
    arc_title = ""
    arc_from = None
    arc_to = None
    arc_has_beats = False
    if isinstance(arc, dict):
        arc_title = str(arc.get("title") or arc.get("name") or "").strip()
        arc_from = arc.get("from_chapter") or arc.get("from")
        arc_to = arc.get("to_chapter") or arc.get("to")
        arc_has_beats = bool(arc.get("beats") or arc.get("outline") or arc.get("summary"))

    pacing_flags: list[str] = []
    if not arc:
        pacing_flags.append("未命中 arcs：请在框架 JSON 的 arcs 中补充章节范围（from/to 或 chapter_range）")
    if arc and not arc_has_beats:
        pacing_flags.append("弧线缺少 beats/outline/summary：建议补充，以便系统给出更准的节拍导航")
    # 启发式：上一章一次性收束太多坑，往往意味着推进过快
    if canonical_last_resolved_n >= 3:
        pacing_flags.append("上一条时间线一次性收束过多 open_plots（>=3），可能推进过快/清坑过猛")

    # ===== 按卷计划覆盖率与快进预警（Volume QC）=====
    volumes_count = (
        db.query(func.count(NovelVolume.id))
        .filter(NovelVolume.novel_id == novel_id)
        .scalar()
        or 0
    )
    planned_chapters_count = (
        db.query(func.count(NovelChapterPlan.id))
        .filter(NovelChapterPlan.novel_id == novel_id)
        .scalar()
        or 0
    )
    # 下一章是否有章计划（硬对齐信号）
    has_next_plan = (
        db.query(NovelChapterPlan)
        .filter(NovelChapterPlan.novel_id == novel_id, NovelChapterPlan.chapter_no == next_no)
        .first()
        is not None
    )
    if volumes_count > 0 and not has_next_plan:
        pacing_flags.append("下一章缺少章计划：建议先在“卷与章计划”生成本卷章计划，再逐章生成正文")

    return {
        "novel": {
            "id": n.id,
            "title": n.title,
            "framework_confirmed": n.framework_confirmed,
            "status": n.status,
        },
        "config": {
            "novel_memory_refresh_chapters": settings.novel_memory_refresh_chapters,
            "novel_chapter_summary_mode": settings.novel_chapter_summary_mode,
            "novel_chapter_summary_tail_chars": settings.novel_chapter_summary_tail_chars,
            "novel_chapter_summary_head_chars": settings.novel_chapter_summary_head_chars,
            "novel_consistency_check_chapter": settings.novel_consistency_check_chapter,
            "novel_consistency_check_temperature": settings.novel_consistency_check_temperature,
        },
        "summary": {
            "memory_version": memory_version,
            "open_plots_count": open_plots_count,
            "open_plots_preview": open_plots_preview,
            "open_plots_editable": open_plots_editable,
            "canonical_timeline_count": canonical_count,
            "canonical_timeline_last_chapter_no": canonical_last_chapter_no,
            "canonical_timeline_last_editable": canonical_last_editable,
            "canonical_timeline_last_resolved_n": canonical_last_resolved_n,
            "canonical_timeline_last_added_n": canonical_last_added_n,
            "canonical_timeline_preview": canonical_preview,
            "approved_count": len(approved),
            "pending_review_count": len(pending_review),
            "last_approved_chapter_no": approved_nos_sorted[-1] if approved_nos_sorted else None,
            "prev_approved_chapter_no": approved_nos_sorted[-2] if len(approved_nos_sorted) >= 2 else None,
            "is_consecutive_last_two_approved": is_consecutive,
            "next_chapter_no": next_no,
            "current_arc_title": arc_title,
            "current_arc_from": arc_from,
            "current_arc_to": arc_to,
            "current_arc_has_beats": arc_has_beats,
            "pacing_flags": pacing_flags,
            "volumes_count": int(volumes_count),
            "planned_chapters_count": int(planned_chapters_count),
            "has_next_chapter_plan": bool(has_next_plan),
        },
    }


@router.post("/{novel_id}/memory/refresh")
async def refresh_memory(novel_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")
    chapters = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .order_by(Chapter.chapter_no.asc())
        .all()
    )
    if not chapters:
        raise HTTPException(400, "暂无已审定章节可用于汇总记忆")
    summary = format_approved_chapters_summary(
        chapters,
        settings.novel_chapter_summary_tail_chars,
        head_chars=settings.novel_chapter_summary_head_chars,
        mode=settings.novel_chapter_summary_mode,
        max_chapters=settings.novel_memory_refresh_chapters,
    )
    prev = latest_memory_json(db, novel_id)
    llm = NovelLLMService()
    result = await llm.refresh_memory_from_chapters(n, summary, prev, db=db)
    if not result.get("ok"):
        ver = (
            db.query(func.max(NovelMemory.version)).filter(NovelMemory.novel_id == novel_id).scalar()
            or 0
        )
        candidate_json = str(result.get("candidate_json") or "{}")
        return {
            "status": "validation_failed",
            "version": ver,
            "payload_json": prev,
            "readable_zh": memory_payload_to_readable_zh(prev),
            "candidate_json": candidate_json,
            "candidate_readable_zh": memory_payload_to_readable_zh(candidate_json),
            "errors": result.get("errors") or [],
        }
    new_json = result.get("payload_json") or prev
    return {
        "status": "ok",
        "version": result.get("version"),
        "payload_json": new_json,
        "readable_zh": memory_payload_to_readable_zh(new_json),
    }


@router.post("/{novel_id}/memory/manual-fix")
async def manual_fix_memory(
    novel_id: str, body: ManualFixMemoryBody, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    手动纠偏（低风险）：只覆盖
    - open_plots
    - canonical_timeline 最后一条的 key_facts/causal_results/open_plots_added/open_plots_resolved
    并写入新版本的 NovelMemory。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise HTTPException(404, "小说不存在")

    mem_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    prev_json = mem_row.payload_json if mem_row else "{}"
    try:
        payload = json.loads(prev_json or "{}")
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    # 1) open_plots 替换
    open_plots_clean = [x.strip() for x in (body.open_plots or []) if x and x.strip()]
    payload["open_plots"] = open_plots_clean

    # 2) canonical_timeline_hot 最后一条替换（尽量保留其它字段）
    ct = payload.get("canonical_timeline_hot")
    if not isinstance(ct, list):
        ct = payload.get("canonical_timeline")
    if not isinstance(ct, list):
        ct = []

    # 找到最近已审定章节号，用于新条目的 chapter_no（低风险；可追溯）
    last_approved = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .order_by(Chapter.chapter_no.desc())
        .first()
    )
    last_approved_no = last_approved.chapter_no if last_approved else 0

    canonical_last = body.canonical_last.model_dump()
    canonical_last_clean = {
        "key_facts": [x.strip() for x in (canonical_last.get("key_facts") or []) if x and x.strip()],
        "causal_results": [
            x.strip()
            for x in (canonical_last.get("causal_results") or [])
            if x and x.strip()
        ],
        "open_plots_added": [
            x.strip()
            for x in (canonical_last.get("open_plots_added") or [])
            if x and x.strip()
        ],
        "open_plots_resolved": [
            x.strip()
            for x in (canonical_last.get("open_plots_resolved") or [])
            if x and x.strip()
        ],
    }

    if not ct:
        ct.append({"chapter_no": last_approved_no, **canonical_last_clean})
    else:
        if isinstance(ct[-1], dict):
            # 只替换目标字段
            for k, v in canonical_last_clean.items():
                ct[-1][k] = v
        else:
            ct[-1] = {"chapter_no": last_approved_no, **canonical_last_clean}
    payload["canonical_timeline"] = ct
    payload["canonical_timeline_hot"] = ct

    # open_plots 活跃线自动维护：移除 resolved，补入 added
    resolved_set = {x.strip() for x in canonical_last_clean["open_plots_resolved"] if x.strip()}
    added_set = [x.strip() for x in canonical_last_clean["open_plots_added"] if x.strip()]
    active = [x for x in payload.get("open_plots", []) if isinstance(x, str)]
    active = [x for x in active if x.strip() and x.strip() not in resolved_set]
    for x in added_set:
        if x not in active:
            active.append(x)
    payload["open_plots"] = active

    if body.notes_hint and body.notes_hint.strip():
        hint = f"人工纠偏：{body.notes_hint.strip()}"
        old_notes = payload.get("notes")
        if isinstance(old_notes, str) and old_notes.strip():
            payload["notes"] = f"{old_notes.strip()}\\n{hint}"
        else:
            payload["notes"] = hint

    new_json = json.dumps(payload, ensure_ascii=False)
    ver = (
        db.query(func.max(NovelMemory.version))
        .filter(NovelMemory.novel_id == novel_id)
        .scalar()
        or 0
    )
    new_ver = ver + 1
    replace_normalized_from_payload(db, novel_id, new_ver, new_json)
    snap_ver = sync_json_snapshot_from_normalized(
        db, novel_id, summary="人工纠偏：更新 open_plots 与 canonical_timeline 最后一条"
    )
    db.commit()

    # 返回简要信息，供前端刷新指标
    return {
        "version": snap_ver or new_ver,
        "open_plots_count": len(open_plots_clean),
        "canonical_timeline_count": len(ct),
        "canonical_timeline_last_chapter_no": last_approved_no if ct else None,
    }
