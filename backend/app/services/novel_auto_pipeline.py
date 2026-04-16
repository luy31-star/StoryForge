from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.novel import Novel, NovelMemory
from app.models.writing_style import WritingStyle
from app.models.volume import NovelChapterPlan, NovelVolume
from app.services.memory_normalize_sync import (
    replace_normalized_from_payload,
    sync_json_snapshot_from_normalized,
)
from app.services.novel_generation_common import append_generation_log
from app.services.novel_repo import (
    chapter_needs_body_per_plan,
    chapter_plan_exists,
    next_chapter_no_from_approved,
)
from app.services.novel_chapter_generate_batch import run_generate_chapters_batch_sync
from app.services.novel_llm_service import NovelLLMService
from app.services.novel_volume_plan_batch import run_volume_chapter_plan_batch_sync
from app.services.task_cancel import is_cancel_requested

logger = logging.getLogger(__name__)


def _generate_framework_sync(
    llm: NovelLLMService, novel: Novel, db: Session
) -> tuple[str, str]:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(llm.generate_framework(novel, db=db))
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _confirm_framework_with_memory(
    db: Session,
    novel: Novel,
    *,
    framework_markdown: str,
    framework_json: str,
    summary: str,
) -> None:
    try:
        json.loads(framework_json)
    except json.JSONDecodeError as exc:
        raise ValueError("AI 生成的 framework_json 不是合法 JSON") from exc

    novel.framework_markdown = framework_markdown
    novel.framework_json = framework_json
    novel.framework_confirmed = True
    novel.status = "active"

    ver = (
        db.query(func.max(NovelMemory.version))
        .filter(NovelMemory.novel_id == novel.id)
        .scalar()
        or 0
    )
    new_ver = ver + 1
    replace_normalized_from_payload(db, novel.id, new_ver, framework_json)
    sync_json_snapshot_from_normalized(db, novel.id, summary=summary)


def _normalize_json_like_text(text: str) -> str:
    return (
        str(text or "")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
        .strip()
    )


def _extract_brainstorm_payload(raw: str) -> dict[str, Any] | None:
    text = _normalize_json_like_text(raw)
    candidates: list[str] = []
    if text:
        candidates.append(text)

    # 尝试提取代码块
    fence_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    candidates.extend(block.strip() for block in fence_blocks if block.strip())

    # 尝试提取第一个 { 到最后一个 }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1].strip())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                # 再次清理标题中的引号
                if "title" in data:
                    data["title"] = str(data["title"]).strip("《》\"' ")
                return data
        except Exception:
            pass
        try:
            data = ast.literal_eval(candidate)
            if isinstance(data, dict):
                if "title" in data:
                    data["title"] = str(data["title"]).strip("《》\"' ")
                return data
        except Exception:
            pass

    # 如果解析失败，尝试基于行正则提取（增加对 JSON 键引号的支持）
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    extracted: dict[str, Any] = {}
    label_map = {
        "title": ["书名", "标题", "title"],
        "intro": ["简介", "内容简介", "故事简介", "intro"],
        "background": ["背景设定", "世界观", "背景", "设定", "background"],
        "style": ["文风", "风格", "写作风格", "style"],
    }
    for field, labels in label_map.items():
        for line in lines:
            # 清理行首的项目符号等，同时也要允许引号开头（针对 JSON 失败后的行解析）
            clean = re.sub(r"^[\-*#\d\.\)\s]+", "", line).strip()
            for label in labels:
                # 兼容 "title": "xxx", title: xxx, "书名": "xxx" 等多种写法
                m = re.search(
                    rf'["\']?(?:{re.escape(label)})["\']?\s*[:：]\s*["\']?([^"\',}}]+)["\']?',
                    clean,
                    re.IGNORECASE,
                )
                if m and m.group(1).strip():
                    extracted[field] = m.group(1).strip("《》\"' ")
                    break
            if field in extracted:
                break

    chapter_patterns = [
        r"目标总章节数\s*[:：]?\s*(\d+)",
        r"目标章节数\s*[:：]?\s*(\d+)",
        r"预计章节数\s*[:：]?\s*(\d+)",
        r"章节数\s*[:：]?\s*(\d+)",
        r"target_chapters\s*[:=：]?\s*(\d+)",
    ]
    for pat in chapter_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            extracted["target_chapters"] = int(m.group(1))
            break

    if {"title", "intro", "background", "style"} & extracted.keys():
        extracted.setdefault("title", "未命名小说")
        extracted.setdefault("intro", "")
        extracted.setdefault("background", "")
        extracted.setdefault("style", "")
        if "target_chapters" not in extracted:
            nums = [int(x) for x in re.findall(r"\b(\d{2,4})\b", text)]
            if nums:
                extracted["target_chapters"] = nums[0]
        return extracted
    return None


def _build_brainstorm_fallback_payload(
    *,
    raw_reply: str,
    repaired_reply: str,
    clean_styles: list[str],
    notes_text: str,
    length_min: int,
) -> dict[str, Any]:
    source = _normalize_json_like_text(repaired_reply or raw_reply)
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    plain_lines = [
        re.sub(r"^[#>*\-\d\.\)\s]+", "", line).strip()
        for line in lines
    ]
    plain_lines = [line for line in plain_lines if line]

    title = ""
    # 优先在文本块中找看起来像书名的内容（不超过 15 字，不含关键描述词）
    for line in plain_lines[:12]:
        line_clean = line.strip("《》\"' ")
        # 排除包含“章”或者字数描述的行，这些通常是备注
        if "章" in line_clean or "字" in line_clean or "篇幅" in line_clean:
            continue
        if len(line_clean) <= 15 and not any(key in line_clean for key in ["简介", "背景", "设定", "风格", "{", "}", ":"]):
            title = line_clean
            break
            
    # 如果没找到，尝试从备注提取标题，但要过滤掉“章、字”等描述
    if not title and notes_text:
        # 寻找备注中不含“章、字”的第一句话
        parts = re.split(r"[，。；\n]", notes_text)
        for part in parts:
            p = part.strip()
            if p and "章" not in p and "字" not in p and len(p) <= 20:
                title = f"{clean_styles[0]}：{p}"
                break
                
    if not title:
        title = f"{clean_styles[0]}小说"

    # 过滤掉明显的 JSON/代码块行，提取正文块作为简介
    text_blocks = [
        line for line in plain_lines 
        if len(line) >= 8 and not line.startswith(("{", "[", '"', "'"))
    ]
    intro = text_blocks[0] if text_blocks else f"这是一部以{ '、'.join(clean_styles[:3]) }为核心标签的小说。"
    background_parts = text_blocks[1:4]
    background = "\n".join(background_parts).strip()
    if not background:
        background = notes_text or f"围绕{ '、'.join(clean_styles[:3]) }展开，世界观与冲突由 AI 自动延展。"

    style = "、".join(clean_styles[:4])
    if notes_text:
        style = f"{style}；{notes_text[:120]}"

    return {
        "title": title[:80],
        "intro": intro[:1200],
        "background": background[:4000],
        "style": style[:255],
        "target_chapters": length_min,
    }

def run_ai_create_and_start_sync(
    db: Session,
    novel_id: str,
    styles: list[str],
    notes: str,
    length_type: str,
    target_generate_chapters: int,
    target_chapters: int | None,
    billing_user_id: str | None,
    batch_id: str,
) -> dict[str, Any]:
    """
    一键AI建书（仅生成设定与大纲草案）：
    1. 调用大模型生成书名、简介、背景、目标章节数等。
    2. 更新小说信息。
    3. 调用大模型生成框架草案（不自动确认、不写正文）。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise ValueError("小说不存在")

    if is_cancel_requested(batch_id):
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="ai_create_cancelled",
            level="warning",
            message="任务已取消",
        )
        db.commit()
        return {"status": "cancelled", "batch_id": batch_id, "chapters_generated": 0}

    clean_styles = [str(x).strip() for x in styles if str(x).strip()]
    if not clean_styles:
        raise ValueError("至少需要一个题材或风格")
    styles_text = "、".join(clean_styles)
    notes_text = (notes or "").strip()

    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="ai_create_brainstorming",
        message=f"正在构思小说设定（题材/风格：{styles_text}，篇幅：{length_type}）",
    )
    db.commit()

    if is_cancel_requested(batch_id):
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="ai_create_cancelled",
            level="warning",
            message="任务已取消",
        )
        db.commit()
        return {"status": "cancelled", "batch_id": batch_id, "chapters_generated": 0}

    llm = NovelLLMService(billing_user_id=billing_user_id)

    # 0. 准备文风约束
    style_hint = ""
    if n.writing_style_id:
        from app.services.novel_llm_service import _writing_style_block
        ws = db.get(WritingStyle, n.writing_style_id)
        if ws:
            style_hint = f"\n【特定文风深度定制要求】\n{_writing_style_block(ws)}\n"

    # 1. 先根据 length_type 确定篇幅风格描述
    if length_type == "long":
        length_hint = "长篇约100-150万字（约300-800章），需要宏大的世界观和多线并行的复杂情节"
        base_min, base_max = 300, 800
    elif length_type == "short":
        length_hint = "短篇约15-50章（通常 10 万字以内），节奏极快，冲突集中，适合快节奏阅读"
        base_min, base_max = 15, 50
    else:
        length_hint = "中篇约20-50万字（约100-250章），结构稳健，情节起伏有致"
        base_min, base_max = 100, 250

    # 2. 如果提供了具体的 target_chapters，则以此为准，但保留上面的篇幅风格描述
    if isinstance(target_chapters, int) and target_chapters > 0:
        length_min = max(1, min(5000, int(target_chapters)))
        length_max = length_min
        # 附加具体章节信息
        length_hint = f"{length_hint}。本次具体目标为：{length_min} 章"
    else:
        length_min, length_max = base_min, base_max

    prompt = (
        "你是一个顶级的网络小说架构师与畅销书策划编辑，擅长构思极具吸引力的书名和宏大且逻辑严密的设定。\n"
        f"用户提供的题材/风格标签：{styles_text}\n"
        f"篇幅要求：{length_hint}。\n"
        f"目标总章节数要求在 {length_min}-{length_max} 章之间。\n"
        f"用户创作初衷/补充备注：{notes_text or '（无）'}\n"
        f"{style_hint}\n"
        "任务：请基于上述输入，头脑风暴并输出一部原创小说的核心构思。\n"
        "【关键：书名必须具有商业吸引力，不要直接照抄用户的备注。】\n\n"
        "请只输出一个严格合法、可直接 json.loads() 的 JSON 对象，禁止输出任何其他文字或 Markdown 格式。\n"
        "JSON 必须且只能包含以下五个键：\n"
        f'- title: 字符串，书名（4-20 字），要新颖且贴合题材。\n'
        f'- intro: 字符串，1-3 段吸引读者的简介，描述核心冲突和看点。\n'
        f'- background: 字符串，详细的背景设定、力量体系或世界观细节。\n'
        f'- style: 字符串，描述文风的关键词，如“快节奏、反转多、细腻描写”。\n'
        f'- target_chapters: 整数，必须在 {length_min} 到 {length_max} 之间。\n\n'
        "输出示例：\n"
        "{\n"
        '  "title": "万古剑尊",\n'
        '  "intro": "这是一个关于背叛与复仇的故事...",\n'
        '  "background": "在这个名为九州的大陆上，修行者以剑入道...",\n'
        '  "style": "热血、快节奏、升级、爽文",\n'
        f'  "target_chapters": {max(length_min, min(length_max, 150))}\n'
        "}\n"
    )

    def _run_chat(
        messages: list[dict[str, str]],
        web_search: bool = False,
        temperature: float = 0.8,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                llm._router(db=db).chat_text(
                    messages=messages,
                    temperature=temperature,
                    web_search=web_search,
                    timeout=180.0,
                    response_format=response_format,
                    **llm._bill_kw(db, llm._billing_user_id),
                )
            )
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    try:
        reply = _run_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是结构化小说策划输出器。"
                        "你的唯一任务是输出一个可被 Python json.loads() 直接解析的 JSON 对象。"
                        "禁止输出 JSON 之外的任何字符。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        data = _extract_brainstorm_payload(reply)
        repaired = ""
        if data is None:
            repair_prompt = (
                "请将下面这段内容整理为严格合法的 JSON，且只能返回 JSON 本体。"
                "必须包含 title, intro, background, style, target_chapters 五个字段。"
                '示例：{"title":"书名","intro":"简介","background":"背景设定","style":"文风","target_chapters":120}'
            )
            repaired = _run_chat(
                [
                    {"role": "system", "content": "你是 JSON 修复助手，只输出严格 JSON。"},
                    {"role": "user", "content": f"{repair_prompt}\n\n原始内容如下：\n{reply}"},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = _extract_brainstorm_payload(repaired)
        if data is None:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="ai_create_brainstorm_parse_failed",
                level="error",
                message="AI 建书构思结果无法解析为结构化字段",
                meta={
                    "raw_reply_preview": (reply or "")[:2000],
                    "repair_reply_preview": (repaired or "")[:2000],
                },
            )
            db.commit()
            data = _build_brainstorm_fallback_payload(
                raw_reply=reply,
                repaired_reply=repaired,
                clean_styles=clean_styles,
                notes_text=notes_text,
                length_min=length_min,
            )
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="ai_create_brainstorm_fallback_used",
                level="warning",
                message="AI 建书构思解析失败，已使用启发式兜底字段继续流程",
                meta={
                    "fallback_title": data.get("title"),
                    "fallback_target_chapters": data.get("target_chapters"),
                },
            )
            db.commit()

        n.title = data.get("title", f"{clean_styles[0]}小说")
        n.intro = data.get("intro", "")
        n.background = data.get("background", "")
        n.style = data.get("style", "")
        raw_target = int(data.get("target_chapters", length_min))
        n.target_chapters = max(length_min, min(length_max, raw_target))
        n.status = "draft"
        db.commit()
        
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="ai_create_brainstorm_done",
            message=f"设定构思完成：书名《{n.title}》，预计{n.target_chapters}章",
        )
        db.commit()
        
    except Exception as e:
        logger.exception("ai_create brainstorm failed | novel_id=%s", novel_id)
        raise ValueError(f"AI 构思设定失败: {str(e)}")

    # 触发异步生成大纲框架
    from app.tasks.novel_tasks import novel_generate_framework_task
    fw_batch_id = f"fw-gen-{int(time.time())}-{novel_id[:8]}"
    novel_generate_framework_task.delay(novel_id, billing_user_id, fw_batch_id)

    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="ai_create_framework_queued",
        message="小说构思已完成，大纲框架生成任务已入队异步执行。",
    )
    db.commit()

    return {"status": "ok", "message": "设定已构思，大纲正在后台生成中", "chapters_generated": 0}


def _ensure_volumes_cover(db: Session, novel: Novel, end_no: int) -> None:
    existing_vols = (
        db.query(NovelVolume)
        .filter(NovelVolume.novel_id == novel.id)
        .order_by(NovelVolume.volume_no.asc())
        .all()
    )

    max_vol_to_chapter = 0
    if existing_vols:
        max_vol_to_chapter = max(v.to_chapter for v in existing_vols)

    vol_no = len(existing_vols) + 1
    ch_start = max(max_vol_to_chapter + 1, 1)
    while ch_start <= end_no:
        hi = min(novel.target_chapters, ch_start + 50 - 1)
        db.add(
            NovelVolume(
                novel_id=novel.id,
                volume_no=vol_no,
                title=f"第{vol_no}卷",
                summary="",
                from_chapter=ch_start,
                to_chapter=hi,
                status="draft",
            )
        )
        vol_no += 1
        ch_start = hi + 1
    db.commit()


def _find_volume_for_chapter(db: Session, novel_id: str, chapter_no: int) -> NovelVolume | None:
    return (
        db.query(NovelVolume)
        .filter(
            NovelVolume.novel_id == novel_id,
            NovelVolume.from_chapter <= chapter_no,
            NovelVolume.to_chapter >= chapter_no,
        )
        .order_by(NovelVolume.volume_no.asc())
        .first()
    )


def _next_consecutive_planned_body_chunk(
    db: Session, novel_id: str, start_no: int, end_no: int
) -> list[int]:
    rows = (
        db.query(NovelChapterPlan.chapter_no)
        .filter(
            NovelChapterPlan.novel_id == novel_id,
            NovelChapterPlan.chapter_no >= start_no,
            NovelChapterPlan.chapter_no <= end_no,
        )
        .distinct()
        .order_by(NovelChapterPlan.chapter_no.asc())
        .all()
    )

    out: list[int] = []
    expected = start_no
    for (raw_no,) in rows:
        no = int(raw_no)
        if no != expected:
            break
        if chapter_needs_body_per_plan(db, novel_id, no):
            out.append(no)
            expected += 1
            continue
        break
    return out


def run_full_auto_generation_sync(
    db: Session,
    novel_id: str,
    target_count: int,
    billing_user_id: str | None,
    batch_id: str,
    use_cold_recall: bool = False,
    cold_recall_items: int = 5,
    auto_consistency_check: bool | None = None,
    auto_plan_guard_check: bool | None = None,
    auto_plan_guard_fix: bool | None = None,
    auto_style_polish: bool | None = None,
) -> dict[str, Any]:
    """
    全自动 Pipeline：补齐卷 -> 补齐章计划 -> 串行生成正文。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise ValueError("小说不存在")
    if not n.framework_confirmed:
        raise ValueError("框架未确认，无法全自动生成")
    resolved_auto_consistency_check = (
        bool(getattr(n, "auto_consistency_check", False))
        if auto_consistency_check is None
        else bool(auto_consistency_check)
    )
    resolved_auto_plan_guard_fix = (
        bool(getattr(n, "auto_plan_guard_fix", False))
        if auto_plan_guard_fix is None
        else bool(auto_plan_guard_fix)
    )
    resolved_auto_plan_guard_check = (
        bool(getattr(n, "auto_plan_guard_check", False))
        if auto_plan_guard_check is None
        else bool(auto_plan_guard_check)
    )
    resolved_auto_plan_guard_check = bool(
        resolved_auto_plan_guard_check or resolved_auto_plan_guard_fix
    )
    resolved_auto_style_polish = (
        bool(getattr(n, "auto_style_polish", False))
        if auto_style_polish is None
        else bool(auto_style_polish)
    )

    next_no = next_chapter_no_from_approved(db, novel_id)
    end_no = min(next_no + target_count - 1, n.target_chapters)
    
    if next_no > end_no:
        return {"status": "ok", "message": "已达到目标字数或设定章节数上限，无需生成", "chapters_generated": 0}

    logger.info(
        "auto_pipeline start | novel_id=%s next_no=%s end_no=%s target_count=%s",
        novel_id, next_no, end_no, target_count
    )
    
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="auto_pipeline_start",
        message=f"开始全自动生成 Pipeline（目标：第{next_no}章 - 第{end_no}章）",
        meta={"next_no": next_no, "end_no": end_no, "target_count": target_count}
    )
    db.commit()

    if is_cancel_requested(batch_id):
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="auto_pipeline_cancelled",
            level="warning",
            message="任务已取消",
        )
        db.commit()
        return {
            "status": "cancelled",
            "batch_id": batch_id,
            "chapters_generated": 0,
            "chapter_ids": [],
        }

    _ensure_volumes_cover(db, n, end_no)

    created_ids: list[str] = []
    current_no = next_no
    plan_batch_size = 5

    while current_no <= end_no:
        if is_cancel_requested(batch_id):
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_cancelled",
                level="warning",
                message="任务已取消",
                meta={"chapters_generated": len(created_ids), "stopped_at": current_no},
            )
            db.commit()
            return {
                "status": "cancelled",
                "chapter_ids": created_ids,
                "batch_id": batch_id,
                "chapters_generated": len(created_ids),
            }

        planned_body_chunk = _next_consecutive_planned_body_chunk(
            db, novel_id, current_no, end_no
        )
        if planned_body_chunk:
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_chapters",
                message=f"开始生成已有章计划对应正文（第{planned_body_chunk[0]}章 - 第{planned_body_chunk[-1]}章）",
                meta={"chapter_nos": planned_body_chunk},
            )
            db.commit()

            res = run_generate_chapters_batch_sync(
                db=db,
                novel_id=novel_id,
                billing_user_id=billing_user_id,
                title_hint="",
                chapter_nos=planned_body_chunk,
                use_cold_recall=use_cold_recall,
                cold_recall_items=cold_recall_items,
                auto_consistency_check=resolved_auto_consistency_check,
                auto_plan_guard_check=resolved_auto_plan_guard_check,
                auto_plan_guard_fix=resolved_auto_plan_guard_fix,
                auto_style_polish=resolved_auto_style_polish,
                batch_id=batch_id,
                source="auto_pipeline",
            )
            created_ids.extend(res.get("chapter_ids", []))
            if str(res.get("status") or "") == "blocked":
                return {
                    "status": "blocked",
                    "batch_id": batch_id,
                    "chapter_ids": created_ids,
                    "chapters_generated": len(created_ids),
                    "blocked_chapter_no": res.get("blocked_chapter_no"),
                    "blocked_issues": res.get("blocked_issues") or [],
                }
            current_no = planned_body_chunk[-1] + 1
            continue

        if chapter_plan_exists(db, novel_id, current_no) and not chapter_needs_body_per_plan(
            db, novel_id, current_no
        ):
            raise ValueError(
                f"第{current_no}章已有待审或已存在正文，请先处理该章后再继续 AI 一键续写"
            )

        volume = _find_volume_for_chapter(db, novel_id, current_no)
        if not volume:
            raise ValueError(f"第{current_no}章未归属任何卷，无法自动补齐章计划")

        plan_to_no = min(end_no, current_no + plan_batch_size - 1, volume.to_chapter)
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="auto_pipeline_plan_batch",
            message=f"正在为第{volume.volume_no}卷生成章计划（第{current_no}章 - 第{plan_to_no}章）",
            meta={
                "volume_id": volume.id,
                "from_chapter": current_no,
                "to_chapter": plan_to_no,
                "batch_size": plan_batch_size,
            },
        )
        db.commit()

        if is_cancel_requested(batch_id):
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_cancelled",
                level="warning",
                message="任务已取消",
                meta={"chapters_generated": len(created_ids), "stopped_at": current_no},
            )
            db.commit()
            return {
                "status": "cancelled",
                "chapter_ids": created_ids,
                "batch_id": batch_id,
                "chapters_generated": len(created_ids),
            }

        plan_res = run_volume_chapter_plan_batch_sync(
            db=db,
            novel_id=novel_id,
            billing_user_id=billing_user_id,
            volume_id=volume.id,
            batch_id=batch_id,
            force_regen=False,
            batch_size=plan_batch_size,
            from_chapter=current_no,
        )
        if not chapter_plan_exists(db, novel_id, current_no):
            raise ValueError(
                f"第{current_no}章计划生成失败，未产出可用章计划（结果：{plan_res}）"
            )

    return {
        "status": "ok",
        "chapter_ids": created_ids,
        "batch_id": batch_id,
        "chapters_generated": len(created_ids),
    }
