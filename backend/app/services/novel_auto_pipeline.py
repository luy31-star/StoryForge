from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.novel import Novel
from app.models.volume import NovelChapterPlan, NovelVolume
from app.services.novel_repo import next_chapter_no_from_approved
from app.services.novel_chapter_generate_batch import run_generate_chapters_batch_sync
from app.services.novel_volume_plan_batch import run_volume_chapter_plan_batch_sync
from app.services.novel_generation_common import append_generation_log
from app.services.novel_llm_service import _novel_llm_for_novel, generate_novel_framework_sync
import json

logger = logging.getLogger(__name__)

def run_ai_create_and_start_sync(
    db: Session,
    novel_id: str,
    style: str,
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

    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="ai_create_brainstorming",
        message=f"正在构思小说设定（题材：{style}，篇幅：{length_type}）",
    )
    db.commit()

    llm = _novel_llm_for_novel(n)
    
    # 篇幅提示
    length_hint = "中篇约20-50万字（约100-250章）"
    if length_type == "long":
        length_hint = "长篇约100万字以上（约500章以上）"
    elif length_type == "short":
        length_hint = "短篇约10万字以内（约50-100章）"

    prompt = (
        f"你是一个专业的小说架构师。现在用户要求以【{style}】为题材，写一本小说。\n"
        f"篇幅要求：{length_hint}。\n"
        "请构思：\n"
        "1. 书名 (title)\n"
        "2. 简介 (intro)\n"
        "3. 背景设定与世界观 (background)\n"
        "4. 写作风格提示 (style)\n"
        "5. 目标总章节数 (target_chapters) - 请给出一个合理的整数\n\n"
        "请务必返回合法的 JSON 格式，包含 title, intro, background, style, target_chapters 五个字段。不要返回 markdown 代码块，只返回纯 JSON。"
    )

    import asyncio
    
    # 包装一个同步调用
    def _run_chat(messages, web_search=False):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                llm._router(db=db).chat_text(
                    messages=messages,
                    temperature=0.8,
                    web_search=web_search,
                    timeout=180.0,
                    **llm._bill_kw(db, llm._billing_user_id),
                )
            )
        finally:
            loop.close()

    try:
        reply = _run_chat([
            {"role": "system", "content": "你是网络小说策划专家，严格输出 JSON。"},
            {"role": "user", "content": prompt}
        ])
        
        # 尝试解析 JSON
        text = reply.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        data = json.loads(text)
        
        n.title = data.get("title", f"{style}小说")
        n.intro = data.get("intro", "")
        n.background = data.get("background", "")
        n.style = data.get("style", "")
        n.target_chapters = int(data.get("target_chapters", 300))
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
        generate_novel_framework_sync(db, novel_id, billing_user_id)
        # 自动确认框架
        db.refresh(n)
        n.framework_confirmed = True
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

    # 1. 自动补齐卷
    existing_vols = (
        db.query(NovelVolume)
        .filter(NovelVolume.novel_id == novel_id)
        .order_by(NovelVolume.volume_no.asc())
        .all()
    )
    
    max_vol_to_chapter = 0
    if existing_vols:
        max_vol_to_chapter = max(v.to_chapter for v in existing_vols)
        
    vol_no = len(existing_vols) + 1
    ch_start = max(max_vol_to_chapter + 1, 1)
    
    while ch_start <= end_no:
        hi = min(n.target_chapters, ch_start + 50 - 1)
        v = NovelVolume(
            novel_id=novel_id,
            volume_no=vol_no,
            title=f"第{vol_no}卷",
            summary="",
            from_chapter=ch_start,
            to_chapter=hi,
            status="draft",
        )
        db.add(v)
        vol_no += 1
        ch_start = hi + 1
    db.commit()

    # 2. 自动补齐章计划
    volumes = (
        db.query(NovelVolume)
        .filter(
            NovelVolume.novel_id == novel_id,
            NovelVolume.from_chapter <= end_no,
            NovelVolume.to_chapter >= next_no
        )
        .order_by(NovelVolume.volume_no.asc())
        .all()
    )
    
    for v in volumes:
        while True:
            planned_count = (
                db.query(func.count(NovelChapterPlan.id))
                .filter(NovelChapterPlan.volume_id == v.id)
                .scalar() or 0
            )
            expected_count = v.to_chapter - v.from_chapter + 1
            if planned_count >= expected_count:
                break
            
            append_generation_log(
                db,
                novel_id=novel_id,
                batch_id=batch_id,
                event="auto_pipeline_plan_batch",
                message=f"正在为第{v.volume_no}卷自动生成章计划",
                meta={"volume_id": v.id}
            )
            db.commit()
            
            plan_res = run_volume_chapter_plan_batch_sync(
                db=db,
                novel_id=novel_id,
                billing_user_id=billing_user_id,
                volume_id=v.id,
                batch_id=batch_id,
                force_regen=False,
                batch_size=10,
                from_chapter=None
            )
            if plan_res.get("saved", 0) == 0 and plan_res.get("done"):
                # 防死循环：如果认为已完成但数量没对上，则跳出
                break

    # 3. 串行生成正文
    chapter_nos = list(range(next_no, end_no + 1))
    
    append_generation_log(
        db,
        novel_id=novel_id,
        batch_id=batch_id,
        event="auto_pipeline_chapters",
        message="计划就绪，开始生成正文",
        meta={"chapter_nos": chapter_nos}
    )
    db.commit()

    res = run_generate_chapters_batch_sync(
        db=db,
        novel_id=novel_id,
        billing_user_id=billing_user_id,
        title_hint="",
        chapter_nos=chapter_nos,
        use_cold_recall=use_cold_recall,
        cold_recall_items=cold_recall_items,
        auto_consistency_check=auto_consistency_check,
        batch_id=batch_id,
        source="auto_pipeline",
    )
    
    return {
        "status": "ok",
        "chapter_ids": res.get("chapter_ids", []),
        "batch_id": batch_id,
        "chapters_generated": len(res.get("chapter_ids", []))
    }
