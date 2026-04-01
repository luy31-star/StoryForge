from __future__ import annotations

import hmac
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
from app.core.deps import get_current_user, require_chapter_access, require_novel_access
from app.models.user import User
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
    build_memory_health_summary,
    build_memory_schema_guide,
    chapter_content_metrics,
    chapter_plan_exists,
    format_approved_chapters_summary,
    format_continuity_excerpts,
    format_recent_approved_fulltext_context,
    format_volume_event_summary,
    format_volume_progress_anchor,
    has_any_chapter_plan,
    latest_memory_json,
    next_chapter_no_from_approved,
    planned_chapter_numbers_needing_body,
    _select_arc_for_chapter,
)
from app.services.memory_normalize_sync import (
    normalized_memory_to_dict,
    replace_normalized_from_payload,
    sync_json_snapshot_from_normalized,
)
from app.services.novel_storage import ensure_local_novel_dir, save_novel_reference
from app.services.novel_generation_common import (
    append_generation_log as _append_generation_log,
    build_chapter_plan_hint as _build_chapter_plan_hint,
    ensure_chapter_heading as _ensure_chapter_heading,
    has_pending_chapter_consistency_batch,
    has_pending_chapter_generation_batch,
    has_pending_chapter_revise_batch,
    has_pending_memory_refresh_batch,
    memory_refresh_confirmation_token,
)
from app.tasks.novel_tasks import (
    novel_chapter_approve_memory_delta,
    novel_chapter_consistency_fix,
    novel_chapter_revise,
    novel_consolidate_memory,
    novel_generate_chapters_for_novel,
    novel_refresh_memory_for_novel,
    novel_sync_json_snapshot,
)

router = APIRouter(prefix="/api/novels", tags=["novels"])
logger = logging.getLogger(__name__)


def _novel_llm(user: User) -> NovelLLMService:
    return NovelLLMService(billing_user_id=user.id)


class ApplyMemoryRefreshCandidateBody(BaseModel):
    current_version: int = Field(..., ge=0)
    candidate_json: str = Field(..., min_length=2)
    confirmation_token: str = Field(..., min_length=16)


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
    source: str | None = Field(default=None, description="章节来源，如 manual 或 batch_auto")


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


def _resolve_chapter_nos_for_generate(
    db: Session, novel_id: str, body: GenerateChapterBody
) -> tuple[list[int], int]:
    """
    解析本次要生成的章号列表（须每章在章计划中已有条目）。
    批量：按章号升序取前 count 个「有计划且尚缺正文」的章；单章：指定 chapter_no。
    返回 (chapter_nos, requested_cap)；批量时实际章数可能少于 requested_cap。
    """
    requested_cap = max(1, min(body.count, 5))
    if body.chapter_no is not None:
        if body.count != 1:
            raise HTTPException(400, "指定 chapter_no 时 count 必须为 1")
        cn = int(body.chapter_no)
        if not chapter_plan_exists(db, novel_id, cn):
            raise HTTPException(
                400,
                "请先在卷章计划中生成该章计划，再生成正文",
            )
        return [cn], requested_cap
    chapter_nos = planned_chapter_numbers_needing_body(db, novel_id, requested_cap)
    if not chapter_nos:
        if not has_any_chapter_plan(db, novel_id):
            raise HTTPException(
                400,
                "请先在卷章计划中生成计划，再批量生成正文",
            )
        raise HTTPException(
            400,
            "章计划中待生成正文的章节已全部完成，请先补充卷章计划或审定已有章节",
        )
    return chapter_nos, requested_cap


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
    body: InspirationChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """新建小说：多轮对话 + 联网搜索，获取创作灵感（302 Chat web-search）。"""
    llm = _novel_llm(user)
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        reply = await llm.inspiration_chat(msgs, db=db)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    return {"reply": reply}


@router.post("/inspiration-chat/stream")
async def novel_inspiration_chat_stream(
    body: InspirationChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    llm = _novel_llm(user)
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
    novel_id: str,
    body: ChapterContextChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = require_novel_access(db, novel_id, user)
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
    llm = _novel_llm(user)
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
    novel_id: str,
    body: ChapterContextChatBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    n = require_novel_access(db, novel_id, user)
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
    llm = _novel_llm(user)
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
def list_novels(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    q = db.query(Novel)
    if not user.is_admin:
        q = q.filter(Novel.user_id == user.id)
    rows = q.order_by(Novel.updated_at.desc()).all()
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
def create_novel(
    body: NovelCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = Novel(
        title=body.title,
        intro=body.intro,
        background=body.background,
        style=body.style,
        target_chapters=body.target_chapters,
        daily_auto_chapters=body.daily_auto_chapters,
        user_id=user.id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return {"id": n.id}


@router.get("/{novel_id}")
def get_novel(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    n = require_novel_access(db, novel_id, user)
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
    novel_id: str,
    body: NovelPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = require_novel_access(db, novel_id, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(n, k, v)
    db.commit()
    return {"status": "ok"}


@router.delete("/{novel_id}")
def delete_novel(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = require_novel_access(db, novel_id, user)
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
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = require_novel_access(db, novel_id, user)
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
def download_local_reference(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = require_novel_access(db, novel_id, user)
    if not n.reference_storage_key.startswith("local:"):
        raise HTTPException(404, "无本地参考文件")
    part = n.reference_storage_key.removeprefix("local:")
    path = Path(settings.novel_local_upload_dir).resolve() / part
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=n.reference_filename or "reference.txt")


@router.post("/{novel_id}/generate-framework")
async def generate_framework(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = require_novel_access(db, novel_id, user)
    llm = _novel_llm(user)
    md, fj = await llm.generate_framework(n, db=db)
    n.framework_markdown = md
    n.framework_json = fj
    n.framework_confirmed = False
    db.commit()
    return {"status": "ok"}


@router.post("/{novel_id}/confirm-framework")
def confirm_framework(
    novel_id: str,
    body: ConfirmFrameworkBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    n = require_novel_access(db, novel_id, user)
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
    novel_id: str,
    body: FrameworkUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    n = require_novel_access(db, novel_id, user)
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
def list_chapters(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    require_novel_access(db, novel_id, user)
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
    novel_id: str,
    body: GenerateChapterBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """入队后台批量生成章节；逻辑在 Celery worker 中执行。"""
    n = require_novel_access(db, novel_id, user)
    if not n.framework_confirmed:
        raise HTTPException(400, "请先确认小说框架后再生成章节")
    if has_pending_chapter_generation_batch(db, novel_id):
        raise HTTPException(
            409,
            "当前已有章节生成任务进行中，请在「生成日志」中查看进度后再试",
        )
    chapter_nos, requested_cap = _resolve_chapter_nos_for_generate(db, novel_id, body)
    batch_id = f"gen-{int(time.time())}-{novel_id[:8]}"
    
    # 确定来源：如果 body 中有指定则用指定的，否则根据是否是单章生成来判断
    source = body.source
    if not source:
        source = "manual" if body.chapter_no is not None else "batch_auto"

    payload: dict[str, Any] = {
        "title_hint": body.title_hint,
        "chapter_nos": chapter_nos,
        "requested_count": requested_cap,
        "use_cold_recall": body.use_cold_recall,
        "cold_recall_items": body.cold_recall_items,
        "auto_consistency_check": body.auto_consistency_check,
        "source": source,
    }
    logger.info(
        "generate_chapters enqueue | novel_id=%s count=%s chapter_nos=%s batch_id=%s",
        novel_id,
        len(chapter_nos),
        chapter_nos,
        batch_id,
    )
    _append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="chapter_generation_queued",
        message=f"已入队后台串行生成 {len(chapter_nos)} 章（章号：{', '.join(str(x) for x in chapter_nos)}）",
        meta={
            "requested_count": requested_cap,
            "actual_count": len(chapter_nos),
            "chapter_nos": chapter_nos,
            **payload,
        },
    )
    db.commit()
    try:
        task = novel_generate_chapters_for_novel.delay(
            novel_id, str(user.id), batch_id, payload
        )
        task_id = getattr(task, "id", None)
    except Exception as e:
        logger.exception("generate_chapters enqueue failed | novel_id=%s", novel_id)
        try:
            _append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="chapter_generation_enqueue_failed",
                level="error",
                message=f"后台任务入队失败：{e}",
                meta={"error": str(e)},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(503, f"后台任务入队失败：{e}") from e
    _append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="chapter_generation_task_accepted",
        message="后台任务已接收",
        meta={"task_id": task_id},
    )
    db.commit()
    return {
        "status": "queued",
        "batch_id": batch_id,
        "task_id": task_id,
        "chapter_nos": chapter_nos,
        "requested_count": requested_cap,
        "actual_count": len(chapter_nos),
        "message": "章节将按章计划在后台串行生成，可在生成日志中查看进度",
    }


@router.post("/chapters/{chapter_id}/consistency-fix")
def consistency_fix_chapter(
    chapter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    c = require_chapter_access(db, chapter_id, user)
    n = require_novel_access(db, c.novel_id, user)
    if not n.framework_confirmed:
        raise HTTPException(400, "请先确认小说框架")
    if not (c.content or "").strip():
        raise HTTPException(400, "当前无正式正文，无法一致性修订")
    if has_pending_chapter_consistency_batch(db, c.novel_id, chapter_id):
        raise HTTPException(
            409,
            "当前章节一致性修订任务进行中，请在「生成日志」中查看进度后再试",
        )
    batch_id = f"consist-{chapter_id}-{int(time.time())}"
    try:
        task = novel_chapter_consistency_fix.delay(
            chapter_id, str(user.id), batch_id
        )
        task_id = getattr(task, "id", None)
    except Exception as e:
        logger.exception("consistency_fix enqueue failed | chapter_id=%s", chapter_id)
        raise HTTPException(503, f"后台任务入队失败：{e}") from e
    _append_generation_log(
        db,
        novel_id=c.novel_id,
        batch_id=batch_id,
        event="chapter_consistency_queued",
        message="已入队后台一致性修订",
        chapter_no=c.chapter_no,
        meta={"chapter_id": chapter_id, "task_id": task_id},
    )
    db.commit()
    return {
        "status": "queued",
        "batch_id": batch_id,
        "task_id": task_id,
        "message": "一致性修订已在后台执行，可在生成日志中查看进度",
    }


@router.get("/{novel_id}/generation-logs")
def list_generation_logs(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    batch_id: str | None = None,
    level: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
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
        elif "memory_refresh_warning" in events:
            refresh_status = "done"
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

    latest_chapter_gen_batch_id: str | None = None
    chapter_generation_status = "idle"
    for r in all_rows:
        bid = r.batch_id or ""
        if bid.startswith("gen-"):
            latest_chapter_gen_batch_id = bid
            break
    if latest_chapter_gen_batch_id:
        cg = (
            db.query(NovelGenerationLog)
            .filter(
                NovelGenerationLog.novel_id == novel_id,
                NovelGenerationLog.batch_id == latest_chapter_gen_batch_id,
            )
            .order_by(NovelGenerationLog.created_at.asc())
            .all()
        )
        ev_cg = {x.event for x in cg}
        if "batch_failed" in ev_cg:
            chapter_generation_status = "failed"
        elif "batch_done" in ev_cg:
            chapter_generation_status = "done"
        elif "batch_start" in ev_cg:
            chapter_generation_status = "started"
        elif "chapter_generation_queued" in ev_cg:
            chapter_generation_status = "queued"

    refresh_outcome: str = "idle"
    memory_refresh_preview: dict[str, Any] | None = None
    if latest_refresh_batch_id:
        rb2 = (
            db.query(NovelGenerationLog)
            .filter(
                NovelGenerationLog.novel_id == novel_id,
                NovelGenerationLog.batch_id == latest_refresh_batch_id,
            )
            .order_by(NovelGenerationLog.created_at.asc())
            .all()
        )
        ev_rb = {x.event for x in rb2}
        if "memory_refresh_failed" in ev_rb:
            refresh_outcome = "failed"
        elif "memory_refresh_validation_failed" in ev_rb:
            refresh_outcome = "blocked"
        elif "memory_refresh_warning" in ev_rb:
            refresh_outcome = "warning"
            for x in reversed(rb2):
                if x.event == "memory_refresh_warning":
                    try:
                        wm = json.loads(x.meta_json or "{}")
                    except json.JSONDecodeError:
                        wm = {}
                    memory_refresh_preview = {
                        "tier": "warning",
                        "current_version": wm.get("current_version"),
                        "candidate_json": wm.get("candidate_json"),
                        "candidate_readable_zh": wm.get("candidate_readable_zh"),
                        "warnings": wm.get("warnings") or [],
                        "auto_pass_notes": wm.get("auto_pass_notes") or [],
                        "confirmation_token": wm.get("confirmation_token"),
                    }
                    break
        elif "memory_refresh_done" in ev_rb:
            refresh_outcome = "ok"
        if refresh_outcome == "blocked":
            for x in reversed(rb2):
                if x.event == "memory_refresh_validation_failed":
                    try:
                        bm = json.loads(x.meta_json or "{}")
                    except json.JSONDecodeError:
                        bm = {}
                    memory_refresh_preview = {
                        "tier": "blocked",
                        "current_version": bm.get("current_version"),
                        "candidate_json": bm.get("candidate_json"),
                        "candidate_readable_zh": bm.get("candidate_readable_zh"),
                        "errors": bm.get("errors") or [],
                        "warnings": bm.get("warnings") or [],
                        "auto_pass_notes": bm.get("auto_pass_notes") or [],
                    }
                    break

    latest_volume_plan_batch_id: str | None = None
    volume_plan_status = "idle"
    for r in all_rows:
        bid = r.batch_id or ""
        if bid.startswith("vol-plan-"):
            latest_volume_plan_batch_id = bid
            break
    if latest_volume_plan_batch_id:
        vp = (
            db.query(NovelGenerationLog)
            .filter(
                NovelGenerationLog.novel_id == novel_id,
                NovelGenerationLog.batch_id == latest_volume_plan_batch_id,
            )
            .order_by(NovelGenerationLog.created_at.asc())
            .all()
        )
        ev_vp = {x.event for x in vp}
        if "volume_plan_failed" in ev_vp or "volume_plan_enqueue_failed" in ev_vp:
            volume_plan_status = "failed"
        elif "volume_plan_done" in ev_vp:
            volume_plan_status = "done"
        elif "volume_plan_started" in ev_vp:
            volume_plan_status = "started"
        elif "volume_plan_queued" in ev_vp:
            volume_plan_status = "queued"

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
        "latest_chapter_gen_batch_id": latest_chapter_gen_batch_id,
        "chapter_generation_status": chapter_generation_status,
        "refresh_outcome": refresh_outcome,
        "memory_refresh_preview": memory_refresh_preview,
        "latest_volume_plan_batch_id": latest_volume_plan_batch_id,
        "volume_plan_status": volume_plan_status,
    }


@router.post("/{novel_id}/logs/clear")
def clear_generation_logs(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
    db.query(NovelGenerationLog).filter(NovelGenerationLog.novel_id == novel_id).delete(
        synchronize_session=False
    )
    db.commit()
    return {"status": "ok", "message": "生成日志已清空"}


@router.post("/chapters/{chapter_id}/revise")
def revise_chapter(
    chapter_id: str,
    body: ChapterReviseBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    c = require_chapter_access(db, chapter_id, user)
    n = require_novel_access(db, c.novel_id, user)
    if not n.framework_confirmed:
        raise HTTPException(400, "请先确认小说框架")
    if not (c.content or "").strip():
        raise HTTPException(400, "当前无正式正文，无法按意见改稿")
    if has_pending_chapter_revise_batch(db, c.novel_id, chapter_id):
        raise HTTPException(
            409,
            "当前章节改稿任务进行中，请在「生成日志」中查看进度后再试",
        )
    batch_id = f"revise-{chapter_id}-{int(time.time())}"
    try:
        task = novel_chapter_revise.delay(
            chapter_id, str(user.id), batch_id, body.user_prompt.strip()
        )
        task_id = getattr(task, "id", None)
    except Exception as e:
        logger.exception("revise_chapter enqueue failed | chapter_id=%s", chapter_id)
        raise HTTPException(503, f"后台任务入队失败：{e}") from e
    _append_generation_log(
        db,
        novel_id=c.novel_id,
        batch_id=batch_id,
        event="chapter_revise_queued",
        message="已入队后台按意见改稿",
        chapter_no=c.chapter_no,
        meta={"chapter_id": chapter_id, "task_id": task_id},
    )
    db.commit()
    return {
        "status": "queued",
        "batch_id": batch_id,
        "task_id": task_id,
        "message": "改稿已在后台执行，可在生成日志中查看进度",
    }


@router.post("/chapters/{chapter_id}/apply-revision")
async def apply_chapter_revision(
    chapter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    c = require_chapter_access(db, chapter_id, user)
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
def discard_chapter_revision(
    chapter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    c = require_chapter_access(db, chapter_id, user)
    c.pending_content = ""
    c.pending_revision_prompt = ""
    db.commit()
    return {"status": "ok"}


@router.post("/chapters/{chapter_id}/feedback")
def add_feedback(
    chapter_id: str,
    body: ChapterFeedbackBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    c = require_chapter_access(db, chapter_id, user)
    fb = ChapterFeedback(chapter_id=chapter_id, body=body.body)
    db.add(fb)
    c.status = "pending_review"
    db.commit()
    return {"id": fb.id}


@router.post("/chapters/{chapter_id}/approve")
async def approve_chapter(
    chapter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    c = require_chapter_access(db, chapter_id, user)
    n = require_novel_access(db, c.novel_id, user)
    if c.status == "approved":
        return {
            "status": "ok",
            "already_approved": True,
            "incremental_memory_status": "none",
            "incremental_memory_version": None,
            "incremental_memory_batch_id": None,
            "incremental_memory_task_id": None,
            "memory_refresh_status": "none",
            "memory_refresh_task_id": None,
            "memory_refresh_batch_id": None,
            "consolidate_memory_task_id": None,
        }
    if settings.novel_setting_audit_on_approve:
        llm_audit = _novel_llm(user)
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
    approve_batch_id = f"chapter-approve-{int(time.time())}-{c.novel_id[:8]}"
    # 先提交审定状态，再由 Celery 后台执行单章增量记忆，避免阻塞 HTTP。
    db.commit()
    incremental_memory_task_id: str | None = None
    incremental_memory_status: Literal["queued", "enqueue_failed"] = "enqueue_failed"
    try:
        t = novel_chapter_approve_memory_delta.delay(
            c.novel_id,
            chapter_id,
            approve_batch_id,
            int(c.chapter_no) if c.chapter_no is not None else 0,
        )
        incremental_memory_task_id = getattr(t, "id", None)
        incremental_memory_status = "queued"
    except Exception:
        logger.exception(
            "enqueue novel.chapter_approve_memory_delta failed | novel_id=%s chapter_id=%s",
            c.novel_id,
            chapter_id,
        )
    # commit 后仍使用同一 session 写入入队日志
    try:
        if incremental_memory_status == "queued":
            _append_generation_log(
                db,
                novel_id=c.novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_queued",
                chapter_no=c.chapter_no,
                message="审定已通过：单章增量记忆已入队后台执行",
                meta={
                    "source": "approve_chapter",
                    "task_id": incremental_memory_task_id,
                },
            )
        else:
            _append_generation_log(
                db,
                novel_id=c.novel_id,
                batch_id=approve_batch_id,
                event="chapter_memory_delta_enqueue_failed",
                chapter_no=c.chapter_no,
                level="error",
                message="审定已通过：单章增量记忆入队失败，请稍后重试或在记忆页手动刷新",
                meta={"source": "approve_chapter"},
            )
        db.commit()
    except Exception:
        logger.exception(
            "approve_chapter post-commit log failed | novel_id=%s chapter_id=%s",
            c.novel_id,
            chapter_id,
        )
        db.rollback()
    # 审定后增量记忆在后台完成；周期性归档合并由后台任务在成功写入后触发。
    return {
        "status": "ok",
        "incremental_memory_status": incremental_memory_status,
        "incremental_memory_version": None,
        "incremental_memory_batch_id": approve_batch_id,
        "incremental_memory_task_id": incremental_memory_task_id,
        "memory_refresh_status": "none",
        "memory_refresh_task_id": None,
        "memory_refresh_batch_id": None,
        "consolidate_memory_task_id": None,
    }


@router.patch("/chapters/{chapter_id}")
async def patch_chapter(
    chapter_id: str,
    body: ChapterUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    c = require_chapter_access(db, chapter_id, user)
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


@router.post("/chapters/{chapter_id}/memory-retry")
def retry_chapter_memory(
    chapter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """手动重试单章增量记忆写入：即使章节已审定，也重新入队执行记忆抽取。"""
    c = require_chapter_access(db, chapter_id, user)
    
    # 产生一个新的 batch_id 用于日志
    retry_batch_id = f"retry_mem_{int(time.time())}"
    
    try:
        t = novel_chapter_approve_memory_delta.delay(
            c.novel_id,
            chapter_id,
            retry_batch_id,
            int(c.chapter_no) if c.chapter_no is not None else 0,
        )
        task_id = getattr(t, "id", None)
        
        _append_generation_log(
            db,
            novel_id=c.novel_id,
            batch_id=retry_batch_id,
            event="chapter_memory_retry_queued",
            chapter_no=c.chapter_no,
            message="手动触发：章节增量记忆写入已入队后台执行",
            meta={"task_id": task_id},
        )
        db.commit()
        
        return {
            "status": "queued",
            "batch_id": retry_batch_id,
            "task_id": task_id,
        }
    except Exception as e:
        logger.exception("retry_chapter_memory failed | chapter_id=%s", chapter_id)
        raise HTTPException(500, f"入队失败：{e}")


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(
    chapter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    c = require_chapter_access(db, chapter_id, user)

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
def get_memory(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
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
            "schema_guide": build_memory_schema_guide(),
            "health": build_memory_health_summary(db, novel_id),
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
        "schema_guide": build_memory_schema_guide(),
        "health": build_memory_health_summary(db, novel_id),
    }


@router.get("/{novel_id}/memory/normalized")
def get_memory_normalized(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """规范化落表后的记忆分块（真源）；表空时从最新快照补建一次（迁移/兼容）。"""
    require_novel_access(db, novel_id, user)
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
    return {
        "status": "ok",
        "data": data,
        "schema_guide": build_memory_schema_guide(),
        "health": build_memory_health_summary(db, novel_id),
    }


@router.post("/{novel_id}/memory/rebuild-normalized")
def rebuild_memory_normalized(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    灾难恢复/导入：用当前最新快照 JSON 覆盖并重写规范化表，再派生新快照与分表对齐。
    日常请以结构化数据为准；勿与「仅改快照」混用。
    """
    require_novel_access(db, novel_id, user)
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
    return {
        "status": "ok",
        "data": data,
        "schema_guide": build_memory_schema_guide(),
        "health": build_memory_health_summary(db, novel_id),
    }


@router.post("/{novel_id}/memory/save")
def save_memory_payload(
    novel_id: str,
    body: MemorySaveBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    人工保存记忆（API）：先写入规范化表，再由分表派生 NovelMemory 快照。
    - payload_json：整包导入为真源并重建分表
    - readable_zh_override：合并进待生成快照（经 sync 保留）
    """
    require_novel_access(db, novel_id, user)

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
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    手动触发：将规范化存储中的数据反向同步到 NovelMemory (JSON 快照) 中。
    """
    require_novel_access(db, novel_id, user)
    task = novel_sync_json_snapshot.delay(novel_id)
    return {"status": "queued", "task_id": getattr(task, "id", None)}


@router.post("/{novel_id}/memory/consolidate")
def trigger_memory_consolidate(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    手动触发：后台记忆压缩（早期章节 key_facts → timeline_archive，并裁剪过久条目）。
    """
    require_novel_access(db, novel_id, user)
    task = novel_consolidate_memory.delay(novel_id)
    return {"status": "queued", "task_id": getattr(task, "id", None)}


@router.get("/{novel_id}/memory/history")
def get_memory_history(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """获取记忆版本历史列表。"""
    require_novel_access(db, novel_id, user)
    rows = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .all()
    )
    return [
        {
            "version": r.version,
            "summary": r.summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/{novel_id}/memory/clear")
def clear_memory(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """一键清空记忆：清空规范化表并产生一个空快照，同时将所有章节状态重置为待审。"""
    require_novel_access(db, novel_id, user)
    
    # 1. 产生新版本号
    ver = (
        db.query(func.max(NovelMemory.version))
        .filter(NovelMemory.novel_id == novel_id)
        .scalar()
        or 0
    )
    new_ver = ver + 1
    
    # 2. 用空 JSON 覆盖记忆
    empty_payload = "{}"
    replace_normalized_from_payload(db, novel_id, new_ver, empty_payload)
    
    # 强制 flush 以确保 normalized_memory_to_dict 能读到新 outline
    db.flush()
    
    sync_json_snapshot_from_normalized(db, novel_id, summary="管理员一键清空记忆")
    
    # 3. 重置所有章节状态为 pending_review
    db.query(Chapter).filter(Chapter.novel_id == novel_id).update(
        {"status": "pending_review"}, synchronize_session=False
    )
    
    db.commit()
    
    return {"status": "ok", "version": new_ver}


@router.post("/{novel_id}/memory/rollback/{version}")
def rollback_memory_version(
    novel_id: str,
    version: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """回退到指定的记忆版本：将该版本的快照应用到规范化表，并派生新快照。"""
    require_novel_access(db, novel_id, user)
    
    target_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id, NovelMemory.version == version)
        .first()
    )
    if not target_row:
        raise HTTPException(404, f"未找到版本号为 {version} 的记忆快照")
        
    ver = (
        db.query(func.max(NovelMemory.version))
        .filter(NovelMemory.novel_id == novel_id)
        .scalar()
        or 0
    )
    new_ver = ver + 1
    
    replace_normalized_from_payload(db, novel_id, new_ver, target_row.payload_json or "{}")
    sync_json_snapshot_from_normalized(db, novel_id, summary=f"回退到版本 v{version}")
    db.commit()
    
    return {"status": "ok", "new_version": new_ver}


@router.get("/{novel_id}/metrics")
def get_novel_metrics(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    观察指标仪表盘数据：
    - 指标：open_plots / canonical_timeline 覆盖、章节状态分布、连续性简评
    - 当前设定：连贯性策略与一致性核对开关/温度（只返回非敏感配置）
    """
    n = require_novel_access(db, novel_id, user)

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
            "memory_health": build_memory_health_summary(db, novel_id),
        },
        "schema_guide": build_memory_schema_guide(),
    }


@router.post("/{novel_id}/memory/refresh")
def refresh_memory(
    novel_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
    chapters = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .order_by(Chapter.chapter_no.asc())
        .all()
    )
    if not chapters:
        raise HTTPException(400, "暂无已审定章节可用于汇总记忆")
    if has_pending_memory_refresh_batch(db, novel_id):
        raise HTTPException(
            409,
            "当前已有记忆刷新任务进行中，请在「生成日志」中查看进度后再试",
        )
    batch_id = f"mem-refresh-{int(time.time())}-{novel_id[:8]}"
    try:
        task = novel_refresh_memory_for_novel.delay(
            novel_id, "手动：记忆页刷新", batch_id
        )
        task_id = getattr(task, "id", None)
    except Exception as e:
        logger.exception("refresh_memory enqueue failed | novel_id=%s", novel_id)
        raise HTTPException(503, f"后台任务入队失败：{e}") from e
    _append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="memory_refresh_queued",
        message="已入队手动记忆刷新",
        meta={"reason": "手动：记忆页刷新", "task_id": task_id},
    )
    db.commit()
    return {
        "status": "queued",
        "batch_id": batch_id,
        "task_id": task_id,
        "message": "记忆刷新已在后台执行，可在生成日志中查看进度",
    }


@router.post("/{novel_id}/memory/refresh/apply")
async def apply_refresh_memory_candidate(
    novel_id: str,
    body: ApplyMemoryRefreshCandidateBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    require_novel_access(db, novel_id, user)
    current_version = (
        db.query(func.max(NovelMemory.version)).filter(NovelMemory.novel_id == novel_id).scalar()
        or 0
    )
    if current_version != body.current_version:
        raise HTTPException(409, "当前记忆版本已变化，请重新刷新候选记忆")
    expected = memory_refresh_confirmation_token(
        novel_id, body.current_version, body.candidate_json
    )
    if not hmac.compare_digest(expected, body.confirmation_token):
        raise HTTPException(400, "候选记忆确认令牌无效，请重新刷新记忆")
    try:
        parsed = json.loads(body.candidate_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "候选记忆不是合法 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(400, "候选记忆不是合法 JSON 对象")

    next_ver = current_version + 1
    replace_normalized_from_payload(db, novel_id, next_ver, body.candidate_json)
    sync_json_snapshot_from_normalized(
        db,
        novel_id,
        summary="人工确认应用 warning 候选记忆",
    )
    db.commit()
    latest_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    payload_json = latest_row.payload_json if latest_row else body.candidate_json
    return {
        "status": "ok",
        "version": latest_row.version if latest_row else next_ver,
        "payload_json": payload_json,
        "readable_zh": memory_payload_to_readable_zh(payload_json),
    }


@router.post("/{novel_id}/memory/manual-fix")
async def manual_fix_memory(
    novel_id: str,
    body: ManualFixMemoryBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    手动纠偏（低风险）：只覆盖
    - open_plots
    - canonical_timeline 最后一条的 key_facts/causal_results/open_plots_added/open_plots_resolved
    并写入新版本的 NovelMemory。
    """
    require_novel_access(db, novel_id, user)

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
    prev_open_plot_map: dict[str, dict[str, Any]] = {}
    prev_open_plots = payload.get("open_plots")
    if isinstance(prev_open_plots, list):
        for item in prev_open_plots:
            if not isinstance(item, dict):
                continue
            body_text = str(item.get("body") or item.get("text") or "").strip()
            if body_text:
                prev_open_plot_map[body_text] = dict(item)
    payload["open_plots"] = [
        prev_open_plot_map.get(text, {"body": text}) for text in open_plots_clean
    ]

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
    active_rows: list[dict[str, Any]] = []
    for item in payload.get("open_plots", []) if isinstance(payload.get("open_plots"), list) else []:
        if isinstance(item, dict):
            body_text = str(item.get("body") or item.get("text") or "").strip()
            if body_text and body_text not in resolved_set:
                active_rows.append(item)
        elif isinstance(item, str) and item.strip() and item.strip() not in resolved_set:
            active_rows.append({"body": item.strip()})
    active_bodies = {
        str((item.get("body") if isinstance(item, dict) else item) or "").strip()
        for item in active_rows
    }
    for x in added_set:
        if x not in active_bodies:
            active_rows.append(prev_open_plot_map.get(x, {"body": x}))
    payload["open_plots"] = active_rows

    if body.notes_hint and body.notes_hint.strip():
        hint = f"人工纠偏：{body.notes_hint.strip()}"
        old_notes = payload.get("notes")
        if isinstance(old_notes, list):
            payload["notes"] = [*old_notes, hint]
        elif isinstance(old_notes, str) and old_notes.strip():
            payload["notes"] = [old_notes.strip(), hint]
        else:
            payload["notes"] = [hint]

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
