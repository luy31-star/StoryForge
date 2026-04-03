from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.novel import Novel, NovelMemory
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

    fence_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    candidates.extend(block.strip() for block in fence_blocks if block.strip())

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
                return data
        except Exception:
            pass
        try:
            data = ast.literal_eval(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
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
            clean = re.sub(r"^[\-*#\d\.\)\s]+", "", line)
            for label in labels:
                m = re.match(
                    rf"^(?:{re.escape(label)})(?:\s*[:：]\s*|\s+)(.+)$",
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
    for line in plain_lines[:8]:
        if len(line) <= 30 and not any(key in line for key in ["简介", "背景", "文风", "{", "}", ":"]):
            title = line.strip("《》\"' ")
            break
    if not title:
        if notes_text:
            first_note = re.split(r"[，。；\n]", notes_text, maxsplit=1)[0].strip()
            if first_note:
                title = f"{clean_styles[0]}：{first_note[:16]}"
    if not title:
        title = f"{clean_styles[0]}小说"

    text_blocks = [line for line in plain_lines if len(line) >= 8]
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
    billing_user_id: str | None,
    batch_id: str,
) -> dict[str, Any]:
    """
    一键AI建书及全流程：
    1. 调用大模型生成书名、简介、背景、目标字数等。
    2. 更新小说信息。
    3. 调用大模型生成框架，并自动确认。
    4. 触发全自动 Pipeline（补卷 -> 补章计划 -> 正文）。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise ValueError("小说不存在")

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

    llm = NovelLLMService(billing_user_id=billing_user_id)

    length_hint = "中篇约20-50万字（约100-250章）"
    length_min, length_max = 100, 250
    if length_type == "long":
        length_hint = "长篇约100-150万字（约300-800章）"
        length_min, length_max = 300, 800
    elif length_type == "short":
        length_hint = "短篇约15-50章（通常 10 万字以内）"
        length_min, length_max = 15, 50

    prompt = (
        "你是一个专业的网络小说架构师与畅销书策划编辑。\n"
        f"用户选择的题材/风格标签：{styles_text}\n"
        f"篇幅要求：{length_hint}。\n"
        f"目标总章节数必须落在 {length_min}-{length_max} 章之间。\n"
        f"用户补充备注：{notes_text or '（无）'}\n"
        "现在请只做一件事：输出一个严格合法、可直接 json.loads() 的 JSON 对象。\n"
        "禁止输出任何解释、前言、后记、Markdown 代码块、项目符号、注释或多余文字。\n"
        "必须且只能包含以下五个键：title, intro, background, style, target_chapters。\n"
        "字段规则：\n"
        f'- title: 字符串，书名，长度 4-30 字。\n'
        f'- intro: 字符串，简介，1-3 段。\n'
        f'- background: 字符串，背景设定与世界观。\n'
        f'- style: 字符串，文风和创作风格关键词，用顿号或逗号连接。\n'
        f'- target_chapters: 整数，必须在 {length_min} 到 {length_max} 之间。\n'
        "如果某个字段拿不准，也必须给出合理默认值，不允许省略键，不允许返回 null。\n"
        "输出示例（请严格模仿这个 JSON 结构，只替换内容，不要照抄）：\n"
        "{\n"
        '  "title": "《雾海修途》",\n'
        '  "intro": "少年误入雾海禁区，得到残缺古卷，从此踏上一条以小博大的修行路。...",\n'
        '  "background": "天下宗门林立，海雾之下埋藏远古遗迹，修行资源被门阀垄断。主角所在的边陲小城表面平静，实则暗潮涌动。...",\n'
        '  "style": "热血、升级流、悬念推进、群像伏笔",\n'
        f'  "target_chapters": {max(length_min, min(length_max, 120))}\n'
        "}\n"
        "再次强调：最终回答必须是纯 JSON 对象本体，首字符是 { ，末字符是 } 。"
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
        n.status = "active"
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

    # 生成大纲框架
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="ai_create_framework",
        message="正在生成小说大纲框架...",
    )
    db.commit()
    
    try:
        framework_markdown, framework_json = _generate_framework_sync(llm, n, db)
        db.refresh(n)
        _confirm_framework_with_memory(
            db,
            n,
            framework_markdown=framework_markdown,
            framework_json=framework_json,
            summary="AI 建书自动确认框架初始化",
        )
        db.commit()
        
        append_generation_log(
            db,
            novel_id=novel_id,
            batch_id=batch_id,
            event="ai_create_framework_done",
            message="框架生成完毕并已自动确认。",
        )
        db.commit()
    except Exception as e:
        logger.exception("ai_create framework failed | novel_id=%s", novel_id)
        raise ValueError(f"AI 生成大纲失败: {str(e)}")

    # 如果需要初始生成正文，调用全自动管线
    if target_generate_chapters > 0:
        return run_full_auto_generation_sync(
            db=db,
            novel_id=novel_id,
            target_count=target_generate_chapters,
            billing_user_id=billing_user_id,
            batch_id=batch_id,
            use_cold_recall=False,
            cold_recall_items=5,
            auto_consistency_check=False,
        )
    
    return {"status": "ok", "message": "建书完成", "chapters_generated": 0}


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
    auto_consistency_check: bool = False,
) -> dict[str, Any]:
    """
    全自动 Pipeline：补齐卷 -> 补齐章计划 -> 串行生成正文。
    """
    n = db.get(Novel, novel_id)
    if not n:
        raise ValueError("小说不存在")
    if not n.framework_confirmed:
        raise ValueError("框架未确认，无法全自动生成")

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

    _ensure_volumes_cover(db, n, end_no)

    created_ids: list[str] = []
    current_no = next_no
    plan_batch_size = 5

    while current_no <= end_no:
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
                auto_consistency_check=auto_consistency_check,
                batch_id=batch_id,
                source="auto_pipeline",
            )
            created_ids.extend(res.get("chapter_ids", []))
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
