from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re

import httpx
from json_repair import loads as json_repair_loads
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from app.core.config import settings
from app.core.database import SessionLocal
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.novel import Chapter, Novel, NovelMemory
from app.models.volume import NovelChapterPlan
from app.models.writing_style import WritingStyle
from app.models.novel_memory_norm import (
    NovelMemoryNormChapter,
    NovelMemoryNormCharacter,
    NovelMemoryNormItem,
    NovelMemoryNormOutline,
    NovelMemoryNormPet,
    NovelMemoryNormPlot,
    NovelMemoryNormRelation,
    NovelMemoryNormSkill,
)
from app.services.memory_normalize_sync import sync_json_snapshot_from_normalized
from app.services.ai302_client import AI302Client
from app.services.chapter_plan_schema import (
    chapter_plan_guard_payload,
    chapter_plan_has_guardrails,
    chapter_plan_hook,
    chapter_plan_execution_card,
    chapter_plan_plot_summary,
    normalize_beats_to_v2,
)
from app.services.llm_router import LLMRouter
from app.services.novel_repo import (
    arc_bounds_from_dict,
    build_hot_memory_for_prompt,
    build_hot_memory_from_db,
    format_chapter_continuity_bridge_from_db,
    format_cold_recall_block,
    format_cold_recall_from_db,
    format_constraints_block,
    format_entity_recall_block,
    format_entity_recall_from_db,
    format_open_plots_block,
    format_volume_progress_anchor,
    chapter_content_metrics,
    chapter_execution_rules_block,
    effective_framework_json_for_prompt,
    forbidden_future_arcs_block,
    format_available_entities_for_chapter,
    format_previous_chapter_fulltext,
    format_stage_aware_framework_bible,
    framework_json_base_str,
    outline_beat_hint,
    pacing_guard_block,
    truncate_framework_json,
    truncate_framework_json_stage_aware,
)
from app.services.runtime_llm_config import get_runtime_web_search_config
from app.services.novel_quasi_graph_service import build_quasi_graph_context_block
from app.services.novel_retrieval_service import retrieve_relevant_context_block
from app.services.novel_storage import load_reference_text_for_llm
from app.services.memory_schema import (
    clamp_int,
    coerce_int,
    dedupe_clean_strs,
    extract_aliases,
    is_irreversible_fact,
    normalize_plot_type,
)
from app.services.novel_entity_lifecycle import infer_lifecycle_state

logger = logging.getLogger(__name__)


# ---------- 通用「去AI味」语言风格约束 ----------
# 所有面向用户的生成节点（大纲/arcs/执行卡/正文）均需注入此约束，
# 避免 LLM 输出带有技术分析腔、学术腔或程式化修辞。
_ANTI_AI_FLAVOR_BLOCK = (
    "【语言风格硬约束·去AI味】\n"
    "你必须使用自然的人类语言写作，像有经验的网文作者一样思考和表达。严禁以下AI味表达模式：\n"
    "1. 禁用技术/分析/学术术语代替自然叙事，包括但不限于：\n"
    "   熵增、锚点、bug、漏洞、轨道、降维、信息量、噪声、优化、迭代、闭环、链路、\n"
    "   触底反弹、临界点、自洽、逻辑链、坍缩、极化、对冲、溢出、耦合、\n"
    "   维度打击、升维、降维、信息茧房、破壁、底层逻辑、顶层设计、\n"
    "   结构性、系统性、全局性、根本性（作形容词时）、颗粒度、灰度。\n"
    "   这些词必须替换为对应的日常/文学表达：如「越来越乱」代替「熵增」，\n"
    "   「关键线索/转折点」代替「锚点」，「破绽/弱点」代替「漏洞」，\n"
    "   「道路/方向/路子」代替「轨道」，「越来越糟」代替「坍缩」等。\n"
    "2. 禁用过于抽象的概括式叙述：如「局势发生了变化」「矛盾进一步激化」「双方进行了博弈」\n"
    "   ——必须写出具体发生了什么事、谁说了什么话、产生了什么后果。\n"
    "3. 禁用程式化空洞修辞：如「命运的齿轮开始转动」「一切都在朝着不可预知的方向发展」\n"
    "   「时间仿佛在这一刻凝固」「空气中弥漫着不安的气息」。\n"
    "4. 人物对话和内心独白必须像真人说话——短句、口语、犹豫、情绪化，\n"
    "   不要用逻辑严密但毫无感情的长句。\n"
    "5. 描写要有画面感而非概念感：用「她攥紧拳头，指甲嵌进掌心」\n"
    "   而非「她的情绪达到了临界点」；用「他咬着牙，眼睛死死盯着前方」\n"
    "   而非「他的决心完成了迭代」。\n"
    "6. 剧情梗概和大纲描述也要用说书人语气而非论文语气：\n"
    "   用「主角撞破了对方的骗局，却被更大的阴谋反噬」\n"
    "   而非「主角识别了信息漏洞，但触发了系统性反制」。"
)


def _short_id(content: str) -> str:
    """基于内容的确定性短 ID（4位），用于 LLM 引用条目。"""
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:4].upper()


def _dedupe_str_list(items: list[Any], *, max_items: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if max_items is not None and len(out) >= max_items:
            break
    return out


def _safe_json_dict(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


_CHARACTER_INACTIVE_STATUS_KEYWORDS = (
    "死亡",
    "身亡",
    "牺牲",
    "退场",
    "下线",
    "离队",
    "离开主线",
    "失踪",
    "封印",
)


def _status_implies_inactive(status: Any) -> bool:
    raw = str(status or "").strip()
    if not raw:
        return False
    return any(token in raw for token in _CHARACTER_INACTIVE_STATUS_KEYWORDS)


def _relation_identity(src: str, dst: str) -> str:
    return _short_id(f"{src}->{dst}")


def _canonical_entries_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    hot = data.get("canonical_timeline_hot")
    cold = data.get("canonical_timeline_cold")
    full = data.get("canonical_timeline")
    entries: list[dict[str, Any]] = []
    for seq in (cold, hot):
        if not isinstance(seq, list):
            continue
        for item in seq:
            if isinstance(item, dict):
                entries.append(item)
    if not entries and isinstance(full, list):
        for item in full:
            if isinstance(item, dict):
                entries.append(item)
    return entries


def _chapter_target_words(novel: Novel) -> int:
    return max(300, int(getattr(novel, "chapter_target_words", 3000) or 3000))


def _chapter_word_tolerance(target_words: int) -> int:
    return max(30, min(150, int(round(target_words * 0.05))))


def _strong_chapter_word_rule(target_words: int) -> str:
    tolerance = _chapter_word_tolerance(target_words)
    lower = max(1, target_words - tolerance)
    upper = target_words + tolerance
    return (
        f"正文（不含标题行）必须严格围绕目标字数 {target_words} 字来写。"
        f"这是硬性要求，不是建议；正文必须控制在 {lower}～{upper} 字之间。"
        f"该范围只允许轻微浮动（上下 {tolerance} 字），绝不能明显偏短，也绝不能明显超长。"
        "字数按去除空白后的正文字符数计算。"
    )


def _writing_style_block(style: WritingStyle | None) -> str:
    if not style:
        return ""
    
    parts = ["【文风与写作要求】"]
    
    # 词库
    lex = style.lexicon or {}
    tags = lex.get("tags", [])
    if tags:
        parts.append(f"- 词汇标签：[{']、['.join(tags)}]")
    lex_rules = lex.get("rules", [])
    if lex_rules:
        parts.append("- 词汇要求：" + "；".join(lex_rules))
        
    # 结构
    struc = style.structure or {}
    if struc.get("sentence_length"):
        parts.append(f"- 句子长度：平均约 {struc.get('sentence_length')} 字")
    if struc.get("complexity"):
        parts.append(f"- 复杂度：{struc['complexity']}")
    if struc.get("line_break"):
        parts.append(f"- 换行频率：{struc['line_break']}")
    if struc.get("punctuation"):
        parts.append(f"- 标点使用：{struc['punctuation']}")
    struc_rules = struc.get("rules", [])
    if struc_rules:
        parts.append("- 结构要求：" + "；".join(struc_rules))
        
    # 语气
    tone = style.tone or {}
    primary = tone.get("primary", [])
    if primary:
        parts.append(f"- 主要语气：{'、'.join(primary)}")
    if tone.get("description"):
        parts.append(f"- 语气分析：{tone['description']}")
    tone_rules = tone.get("rules", [])
    if tone_rules:
        parts.append("- 语气要求：" + "；".join(tone_rules))
        
    # 修辞
    rhet = style.rhetoric or {}
    types = rhet.get("types", {})
    if types:
        rhet_str = "、".join([f"{k}(频率:{v})" for k, v in types.items()])
        parts.append(f"- 主要修辞：{rhet_str}")
    rhet_rules = rhet.get("rules", [])
    if rhet_rules:
        parts.append("- 修辞要求：" + "；".join(rhet_rules))
        
    # 负面
    if style.negative_prompts:
        parts.append("- 禁止生成的文本案例：" + "；".join(style.negative_prompts))
        
    # 代表段落
    if style.snippets:
        parts.append("\n【文风代表段落（参考Few-shot）】")
        for i, s in enumerate(style.snippets[:3]):
            parts.append(f"段落{i+1}：\n{s}")
            
    return "\n".join(parts)


def _trim_prompt_text(text: str, max_chars: int) -> str:
    raw = str(text or "").strip()
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    if max_chars < 120:
        return raw[:max_chars]
    return raw[: max_chars - 12].rstrip() + "\n…（已裁剪）"


def _compact_query_text(text: str, *, max_chars: int = 1200) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:max_chars]


def _string_list_summary(values: Any, *, max_items: int, item_max_chars: int) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for item in values:
        s = str(item or "").strip()
        if not s:
            continue
        out.append(s[:item_max_chars])
        if len(out) >= max_items:
            break
    return out


def _render_hot_memory_prompt_block(
    hot_memory_json: str,
    *,
    include_entities: bool,
) -> str:
    data = _safe_json_dict(hot_memory_json)
    if not data:
        return ""

    lines = ["【当前叙事状态（热层摘要）】"]
    volume_context = str(data.get("volume_context_text") or "").strip()
    if volume_context:
        lines.append(volume_context)

    main_plot = str(data.get("main_plot_hot") or "").strip()
    if main_plot:
        lines.append(f"- 当前主线焦点：{main_plot[:220]}")

    timeline = data.get("canonical_timeline_hot")
    if isinstance(timeline, list) and timeline:
        lines.append("- 最近关键因果：")
        for entry in timeline[-3:]:
            if not isinstance(entry, dict):
                continue
            chapter_no = entry.get("chapter_no")
            title = str(entry.get("chapter_title") or "").strip()
            key_facts = _string_list_summary(entry.get("key_facts"), max_items=2, item_max_chars=80)
            results = _string_list_summary(
                entry.get("causal_results"), max_items=1, item_max_chars=80
            )
            hooks = _string_list_summary(
                entry.get("unresolved_hooks"), max_items=1, item_max_chars=80
            )
            facts = "；".join([*key_facts, *results, *hooks]).strip()
            head = f"第{chapter_no}章" if isinstance(chapter_no, int) else "最近章节"
            if title:
                head += f"《{title[:24]}》"
            if facts:
                lines.append(f"  · {head}：{facts}")

    open_plots = data.get("open_plots_hot")
    if isinstance(open_plots, list) and open_plots:
        lines.append("- 当前必须承接的活跃线索：")
        for plot in open_plots[:5]:
            if not isinstance(plot, dict):
                continue
            body = str(plot.get("body") or "").strip()
            if not body:
                continue
            stage = str(plot.get("current_stage") or "").strip()
            resolve_when = str(plot.get("resolve_when") or "").strip()
            extras: list[str] = []
            if stage:
                extras.append(f"阶段:{stage[:48]}")
            if resolve_when:
                extras.append(f"收束:{resolve_when[:48]}")
            suffix = f"（{'；'.join(extras)}）" if extras else ""
            lines.append(f"  · {body[:96]}{suffix}")

    characters = data.get("characters_hot")
    if isinstance(characters, list) and characters:
        lines.append("- 当前高影响角色状态：")
        for char in characters[:4]:
            if not isinstance(char, dict):
                continue
            name = str(char.get("name") or "").strip()
            if not name:
                continue
            role = str(char.get("role") or "").strip()
            state = str(char.get("state") or "").strip()
            traits = _string_list_summary(char.get("traits"), max_items=2, item_max_chars=24)
            bits = [bit for bit in [role[:40] if role else "", state[:60] if state else ""] if bit]
            if traits:
                bits.append("特征:" + "、".join(traits))
            lines.append(f"  · {name}" + (f"｜{'｜'.join(bits)}" if bits else ""))

    relations = data.get("relations_hot")
    if isinstance(relations, list) and relations:
        lines.append("- 当前关键关系：")
        for rel in relations[:4]:
            if not isinstance(rel, dict):
                continue
            src = str(rel.get("from") or "").strip()
            dst = str(rel.get("to") or "").strip()
            relation = str(rel.get("relation") or "").strip()
            if src and dst and relation:
                lines.append(f"  · {src} -> {dst}：{relation[:72]}")

    if include_entities:
        inventory = data.get("inventory_hot")
        skills = data.get("skills_hot")
        pets = data.get("pets_hot")
        entity_lines: list[str] = []
        if isinstance(inventory, list):
            labels = [
                str(item.get("label") or "").strip()
                for item in inventory[:4]
                if isinstance(item, dict) and str(item.get("label") or "").strip()
            ]
            if labels:
                entity_lines.append("物品：" + "、".join(labels))
        if isinstance(skills, list):
            labels = [
                str(item.get("name") or "").strip()
                for item in skills[:4]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            if labels:
                entity_lines.append("技能：" + "、".join(labels))
        if isinstance(pets, list):
            labels = [
                str(item.get("name") or "").strip()
                for item in pets[:3]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            if labels:
                entity_lines.append("同伴/宠物：" + "、".join(labels))
        if entity_lines:
            lines.append("- 高影响实体：" + "；".join(entity_lines))

    return "\n".join(lines)


def _build_chapter_recall_query(
    *,
    chapter_no: int,
    chapter_title_hint: str,
    chapter_plan_hint: str,
) -> str:
    parts = [
        f"第{chapter_no}章",
        _compact_query_text(chapter_title_hint, max_chars=80),
        _compact_query_text(chapter_plan_hint, max_chars=1000),
    ]
    return "\n".join(part for part in parts if part).strip()


def _should_include_recent_full_context(
    *,
    chapter_no: int,
    continuity_excerpt: str,
    recent_full_context: str,
    chapter_plan_hint: str,
) -> bool:
    if not str(recent_full_context or "").strip():
        return False
    if chapter_no <= 3:
        return True
    if len(str(continuity_excerpt or "").strip()) < 900:
        return True
    hint = str(chapter_plan_hint or "")
    high_risk_tokens = (
        "上一卷",
        "卷首",
        "开卷",
        "承接",
        "真相",
        "身份",
        "觉醒",
        "首次",
        "获得",
        "习得",
        "回收",
        "反转",
    )
    return any(token in hint for token in high_risk_tokens)


def _build_chapter_context_bundle(
    *,
    memory_json: str,
    chapter_no: int,
    chapter_title_hint: str,
    chapter_plan_hint: str,
    use_cold_recall: bool,
    cold_recall_items: int,
    db: Session | None = None,
    novel_id: str | None = None,
    include_entity_recall: bool = True,
    include_rag: bool = True,
    include_constraints: bool = True,
    include_continuity_bridge: bool = True,
) -> list[str]:
    if db and novel_id:
        hot_memory_json = build_hot_memory_from_db(
            db,
            novel_id,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
            chapter_no=chapter_no,
        )
        recall_query = _build_chapter_recall_query(
            chapter_no=chapter_no,
            chapter_title_hint=chapter_title_hint,
            chapter_plan_hint=chapter_plan_hint,
        )
    else:
        hot_memory_json = build_hot_memory_for_prompt(
            memory_json,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
        )
        recall_query = _build_chapter_recall_query(
            chapter_no=chapter_no,
            chapter_title_hint=chapter_title_hint,
            chapter_plan_hint=chapter_plan_hint,
        )

    blocks: list[str] = []
    hot_block = _render_hot_memory_prompt_block(
        hot_memory_json,
        include_entities=not bool(db and novel_id and chapter_no > 0),
    )
    if hot_block:
        blocks.append(hot_block)
    if db and novel_id and include_constraints:
        cons = format_constraints_block(db, novel_id)
        if cons:
            blocks.append(cons)
    if db and novel_id and include_continuity_bridge:
        bridge = format_chapter_continuity_bridge_from_db(db, novel_id, chapter_no)
        if bridge:
            blocks.append(bridge)
    if include_entity_recall and recall_query:
        entity_recall = (
            format_entity_recall_from_db(
                db,
                novel_id,
                recall_query,
                max_items=max(2, settings.novel_memory_entity_recall_max_items),
            )
            if (db and novel_id)
            else format_entity_recall_block(
                memory_json,
                recall_query,
                max_items=max(2, settings.novel_memory_entity_recall_max_items),
            )
        )
        if entity_recall:
            blocks.append(entity_recall)
    if include_rag and db and novel_id and settings.novel_rag_enabled and recall_query:
        try:
            rag_block = retrieve_relevant_context_block(
                db,
                novel_id,
                recall_query,
                top_k=settings.novel_retrieval_top_k,
                chapter_no=chapter_no,
            )
        except Exception:
            logger.exception(
                "build chapter rag context failed | novel_id=%s chapter_no=%s",
                novel_id,
                chapter_no,
            )
            rag_block = ""
        if rag_block:
            blocks.append(rag_block)
    if db and novel_id and settings.novel_quasi_graph_enabled and settings.novel_story_bible_enabled:
        try:
            qg = build_quasi_graph_context_block(
                db, novel_id, chapter_no=chapter_no, plan_hint=chapter_plan_hint
            )
            if qg:
                blocks.append(qg)
        except Exception:
            logger.exception(
                "quasi graph context failed | novel_id=%s chapter_no=%s",
                novel_id,
                chapter_no,
            )
    if use_cold_recall:
        if db and novel_id:
            cold_block = format_cold_recall_from_db(
                db, novel_id, max_items=max(1, min(cold_recall_items, 12))
            )
        else:
            cold_block = format_cold_recall_block(
                memory_json, max_items=max(1, min(cold_recall_items, 12))
            )
        if cold_block:
            blocks.append(cold_block)
    return blocks


def _format_character_voice_profiles_for_prompt(
    db: Any,
    novel_id: str,
    chapter_no: int,
    *,
    max_items: int = 6,
) -> str:
    if not db:
        return ""
    rows = (
        db.query(NovelMemoryNormCharacter)
        .filter(
            NovelMemoryNormCharacter.novel_id == novel_id,
            NovelMemoryNormCharacter.introduced_chapter <= chapter_no,
        )
        .order_by(
            NovelMemoryNormCharacter.influence_score.desc(),
            NovelMemoryNormCharacter.sort_order.asc(),
        )
        .limit(max_items)
        .all()
    )
    lines: list[str] = ["【角色语音档案（对白与视角必须贴合）】"]
    used = 0
    for row in rows:
        expired = getattr(row, "expired_chapter", None)
        if isinstance(expired, int) and expired and expired <= chapter_no:
            continue
        try:
            detail = json.loads(getattr(row, "detail_json", "") or "{}")
        except Exception:
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        voice = detail.get("voice_profile") if isinstance(detail.get("voice_profile"), dict) else {}
        speech_style = str(
            voice.get("speech_style")
            or detail.get("speech_style")
            or detail.get("speaking_style")
            or ""
        ).strip()
        emotional_trigger = str(
            voice.get("emotional_trigger")
            or detail.get("emotional_trigger")
            or detail.get("emotion_trigger")
            or ""
        ).strip()
        address_habit = str(
            voice.get("address_habit")
            or detail.get("address_habit")
            or detail.get("forms_of_address")
            or ""
        ).strip()
        taboo = str(
            voice.get("taboo_expression")
            or detail.get("taboo_expression")
            or detail.get("speech_taboo")
            or ""
        ).strip()
        sample = str(
            voice.get("sample_line")
            or detail.get("sample_line")
            or detail.get("voice_sample")
            or ""
        ).strip()
        if not any([speech_style, emotional_trigger, address_habit, taboo, sample]):
            continue
        name = str(getattr(row, "name", "") or "").strip() or "角色"
        bits = [f"- {name}"]
        if speech_style:
            bits.append(f"说话方式：{speech_style}")
        if emotional_trigger:
            bits.append(f"情绪触发：{emotional_trigger}")
        if address_habit:
            bits.append(f"称呼习惯：{address_habit}")
        if taboo:
            bits.append(f"禁用表达：{taboo}")
        if sample:
            bits.append(f"语气样例：{sample}")
        lines.append("；".join(bits))
        used += 1
    return "\n".join(lines) if used else ""


def _format_state_snapshot_for_prompt(db: Any, novel_id: str, chapter_no: int) -> str:
    if not db or chapter_no <= 1:
        return ""
    row = (
        db.query(NovelMemoryNormChapter)
        .filter(
            NovelMemoryNormChapter.novel_id == novel_id,
            NovelMemoryNormChapter.chapter_no == chapter_no - 1,
        )
        .first()
    )
    if not row:
        return ""
    try:
        snapshot = json.loads(getattr(row, "state_snapshot_json", None) or "{}")
    except Exception:
        snapshot = {}
    try:
        transitions = json.loads(getattr(row, "state_transition_summary_json", None) or "[]")
    except Exception:
        transitions = []
    parts: list[str] = []
    if isinstance(snapshot, dict) and snapshot:
        counts = snapshot.get("counts")
        if isinstance(counts, dict) and counts:
            bits: list[str] = []
            for key, label in (
                ("characters", "角色"),
                ("relations", "关系"),
                ("items", "物品"),
                ("skills", "技能"),
                ("pets", "宠物"),
            ):
                val = counts.get(key)
                if isinstance(val, int):
                    bits.append(f"{label}{val}")
            if bits:
                parts.append("上一章收束时可延续状态：" + "，".join(bits))
    if isinstance(transitions, list) and transitions:
        cleaned = [str(x).strip() for x in transitions if str(x).strip()]
        if cleaned:
            parts.append("上一章关键状态变更：\n" + "\n".join(f"- {x}" for x in cleaned[:8]))
    if not parts:
        return ""
    return "【章节状态快照（承接上一章）】\n" + "\n".join(parts)


def _chapter_messages(
    novel: Novel,
    chapter_no: int,
    chapter_title_hint: str,
    memory_json: str,
    continuity_excerpt: str,
    recent_full_context: str = "",
    chapter_plan_hint: str = "",
    db: Any = None,
    *,
    use_cold_recall: bool = False,
    cold_recall_items: int = 5,
) -> list[dict[str, str]]:
    efw = effective_framework_json_for_prompt(db, novel)
    bible = (
        format_stage_aware_framework_bible(novel, chapter_no, framework_json_for_arcs=efw)
        if db
        else (novel.framework_markdown[:6000] if novel.framework_markdown else novel.background or "")
    )
    fj_block = (
        truncate_framework_json_stage_aware(efw, chapter_no)
        if db
        else truncate_framework_json(efw, 6000)
    )
    beat = outline_beat_hint(chapter_no, efw)
    memory_blocks = _build_chapter_context_bundle(
        memory_json=memory_json,
        chapter_no=chapter_no,
        chapter_title_hint=chapter_title_hint,
        chapter_plan_hint=chapter_plan_hint,
        use_cold_recall=use_cold_recall,
        cold_recall_items=cold_recall_items,
        db=db,
        novel_id=novel.id,
    )
    pacing_guard = pacing_guard_block(chapter_no, efw, memory_json)
    future_arc_guard = forbidden_future_arcs_block(chapter_no, efw)
    chapter_rules = chapter_execution_rules_block(chapter_no)
    style_block = _writing_style_block(getattr(novel, "writing_style", None))

    # 新增：卷进度锚点和卷事件摘要 + 可用物品/技能清单
    volume_progress = ""
    available_entities = ""
    voice_profiles = ""
    state_snapshot = ""
    if db:
        try:
            volume_progress = format_volume_progress_anchor(db, novel.id, chapter_no, efw)
            available_entities = format_available_entities_for_chapter(db, novel.id, chapter_no)
            voice_profiles = _format_character_voice_profiles_for_prompt(
                db, novel.id, chapter_no
            )
            state_snapshot = _format_state_snapshot_for_prompt(db, novel.id, chapter_no)
        except Exception:
            # 如果失败，不影响主流程
            pass

    sys = (
        "你是小说作者。世界观、人物与已定设定以【框架 Markdown / 框架 JSON / 结构化记忆】为准，不得无故改写或吃书；"
        "world_rules 与框架 JSON 中明确写死的规则优先于自由发挥。"
        "结构化记忆里的 canonical_timeline 为规范因果链，写作时以它为准对齐关键事实。"
        "若记忆 JSON 与更早正文冲突，以记忆与最近章节为准；若与框架 world_rules 冲突，仍以框架为准并自然收束。"
        "若用户消息中含【本章计划】且列有禁止项（must_not）或延后解锁（reserved_for_later），其优先级高于自由发挥，正文中不得违反。"
        "若用户消息中含【后续阶段（严禁提前推进/剧透）】，你必须遵守：不得让本章实质进入所列更后阶段的核心事件，不得提前揭露真相/身份/能力结果。"
        f"{_ANTI_AI_FLAVOR_BLOCK}\n"
        "物品与技能必须遵循引入约束：任何物品/道具/技能/能力的首次出现，必须有明确的获得/发现/习得过程；"
        "如【可用物品与技能清单】中未列出的物品或技能，正文中不得凭空使用，必须先在本章内铺垫引入过程。\n"
        "输出本章正文，不要输出元解释。"
        "输出格式强约束：第一行必须是\u201c第N章《章名》\u201d（N 必须与当前章节号一致），第二行空行后再写正文。"
        "正文必须符合中文网文阅读习惯：自然分段，段落长短有变化；对话、动作、心理、环境描写要穿插展开；"
        "必须使用完整标点，禁止输出一整坨几乎不分段、缺少标点或只有超长段落的文本。"
    )
    user_parts = [
        f"【世界观与长期规则（摘要）】\n{_trim_prompt_text(bible, 3200)}",
        f"【本书硬设定锚点（JSON摘录）】\n{_trim_prompt_text(fj_block, 2600)}",
    ]
    if style_block:
        user_parts.append(style_block)
    user_parts.extend(memory_blocks)

    # 新增：卷级上下文（在摘录之前，提供整体视图）
    if volume_progress:
        user_parts.append(volume_progress)
    if available_entities:
        user_parts.append(available_entities)
    if voice_profiles:
        user_parts.append(voice_profiles)
    if state_snapshot:
        user_parts.append(state_snapshot)

    user_parts.append(
        f"【前文衔接摘录（含再前一章与上一章结尾，若有）】\n{continuity_excerpt or '（首章）'}"
    )
    if _should_include_recent_full_context(
        chapter_no=chapter_no,
        continuity_excerpt=continuity_excerpt,
        recent_full_context=recent_full_context,
        chapter_plan_hint=chapter_plan_hint,
    ):
        user_parts.append(
            "【最近已审定章节完整正文（增强衔接）】\n"
            + _trim_prompt_text(recent_full_context, 6000)
        )
    user_parts.append(beat)
    user_parts.append(pacing_guard)
    if future_arc_guard:
        user_parts.append(future_arc_guard)
    user_parts.append(chapter_rules)
    if chapter_plan_hint:
        user_parts.append(chapter_plan_hint)
    user_parts.append(
        f"请写第 {chapter_no} 章"
        f"{('，章标题建议：' + chapter_title_hint) if chapter_title_hint else ''}。"
    )
    target_words = _chapter_target_words(novel)

    if chapter_no == 1:
        user_parts.append(
            "【全书第1章特别要求】\n"
            "读者第一次打开本书：正文须在前段或随场景推进**交代清楚**基本背景——至少包括与入场相关的：时代/世界或环境定位、主角身份与当前处境、"
            "即将牵动主线的矛盾/契机/目标为何出现；与【世界观与框架摘要】一致，须可感知、可代入，不要信息真空。\n"
            "禁止「莫名其妙」：不得用缺乏情境铺垫的群战、满篇生造设定名、或读者尚不知谁与谁为何起冲突就写结果；"
            "若用悬念开头，须尽快给出能理解情境的最小线索，避免为悬念而悬念。"
        )

    ch1_rule_8 = ""
    if chapter_no == 1:
        ch1_rule_8 = (
            "8) 若本书为第1章：除满足【全书第1章特别要求】外，正文须让读者在章内获得「谁、何处、因何如此」的最低可理解度，"
            "与上述章内执行规则、本章计划中的 must_not 不冲突；禁止整章读毕仍搞不清基本设定与主角处境。\n"
        )
    user_parts.append(
        "【统一输出规则】\n"
        f"1) 第一行必须输出：第{chapter_no}章《章名》；\n"
        "2) 若未提供章标题建议，请先拟定一个贴合剧情的章名；\n"
        "3) 第二行留空一行，再开始正文。\n"
        f"4) {_strong_chapter_word_rule(target_words)} 请在输出前自行检查并修正，确保落在允许范围内。\n"
        "5) 用场景、对白与细节描写支撑篇幅，避免用一两段概括带过，也不要为了凑字数重复心理、环境或解释。\n"
        "6) 正文必须按自然阅读节奏分段：一般 2～6 句一段；场景切换、人物对话、动作变化、心理转折处要主动换段。\n"
        "7) 必须使用规范中文标点；禁止连续大段无标点铺陈，禁止整章只有少数几个超长段落。"
        f"\n{ch1_rule_8}"
    )
    user = "\n\n".join(user_parts)
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _revise_chapter_messages(
    novel: Novel,
    chapter: Chapter,
    memory_json: str,
    feedback_bodies: list[str],
    user_prompt: str,
    db: Any = None,
) -> list[dict[str, str]]:
    efw = effective_framework_json_for_prompt(db, novel)
    bible = (
        format_stage_aware_framework_bible(novel, chapter.chapter_no, framework_json_for_arcs=efw)
        if db
        else (novel.framework_markdown[:6000] if novel.framework_markdown else novel.background)
    )
    fj_block = truncate_framework_json_stage_aware(efw, chapter.chapter_no)
    fb = "\n".join(f"- {b}" for b in feedback_bodies) or "（无）"
    style_block = _writing_style_block(getattr(novel, "writing_style", None))
    target_words = _chapter_target_words(novel)
    memory_blocks = _build_chapter_context_bundle(
        memory_json=memory_json,
        chapter_no=chapter.chapter_no,
        chapter_title_hint=chapter.title,
        chapter_plan_hint=user_prompt,
        use_cold_recall=False,
        cold_recall_items=0,
        db=db,
        novel_id=novel.id,
        include_entity_recall=False,
        include_rag=False,
    )
    sys = (
        "你是资深小说编辑。在保持世界观与人物一致的前提下，根据历史反馈意见与用户最新指令，"
        "对章节全文进行改写。框架 JSON 中的 world_rules 与已定设定不得被改稿推翻；只输出改写后的正文，"
        "不要前言、标题解释或 Markdown 围栏。"
        "改写后的正文必须符合中文阅读习惯：自然分段、标点完整、避免整页只有极少数超长段落。\n"
        f"{_ANTI_AI_FLAVOR_BLOCK}"
    )
    user_parts = [
        f"【世界观与长期规则（摘要）】\n{_trim_prompt_text(bible, 2600)}",
        f"【本书硬设定锚点（JSON摘录）】\n{_trim_prompt_text(fj_block, 2200)}",
    ]
    if style_block:
        user_parts.append(style_block)
    user_parts.extend(memory_blocks)
    user_parts.append(f"【字数硬约束】\n{_strong_chapter_word_rule(target_words)}")
    user_parts.append(f"第 {chapter.chapter_no} 章《{chapter.title}》\n\n【当前正文（正式稿）】\n{chapter.content}")
    user_parts.append(f"【历史改进意见】\n{fb}")
    user_parts.append(f"【用户本次指令】\n{user_prompt}")
    if chapter.chapter_no == 1:
        user_parts.append(
            "【全书第1章】改稿后须仍能让首次入场的读者理解：基本背景、主角处境、故事因何启动；"
            "避免改完后变成更莫名其妙或更缺信息的切入。"
        )
    user = "\n\n".join(user_parts)
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _check_and_fix_chapter_messages(
    novel: Novel,
    chapter_no: int,
    chapter_title_hint: str,
    memory_json: str,
    continuity_excerpt: str,
    chapter_text: str,
    db: Any = None,
) -> list[dict[str, str]]:
    efw = effective_framework_json_for_prompt(db, novel)
    bible = (
        format_stage_aware_framework_bible(novel, chapter_no, framework_json_for_arcs=efw)
        if db
        else (novel.framework_markdown[:6000] if novel.framework_markdown else novel.background)
    )
    fj_block = truncate_framework_json_stage_aware(efw, chapter_no)
    target_words = _chapter_target_words(novel)
    memory_blocks = _build_chapter_context_bundle(
        memory_json=memory_json,
        chapter_no=chapter_no,
        chapter_title_hint=chapter_title_hint,
        chapter_plan_hint="",
        use_cold_recall=False,
        cold_recall_items=0,
        db=db,
        novel_id=novel.id,
        include_entity_recall=False,
        include_rag=False,
    )
    available_entities = ""
    if db:
        try:
            available_entities = format_available_entities_for_chapter(db, novel.id, chapter_no)
        except Exception:
            available_entities = ""
    sys = (
        "你是小说一致性编辑。你的任务是对「待核对正文」做最小修改，解决设定漂移与前后因果断裂。"
        "严格遵守世界观与人物设定，必要时以【框架 JSON】与 world_rules 为准修正正文。"
        "canonical_timeline 作为规范因果链：若正文与时间线关键事实冲突，必须修正正文。"
        "输出只允许包含「修订后的正文内容本体」，不得输出标题、前言、解释或 Markdown 围栏。"
        "修订时需保留并优化正文可读性：自然分段、标点完整，避免出现一整坨不分段的文本。\n"
        f"{_ANTI_AI_FLAVOR_BLOCK}"
    )
    user_parts = [
        f"【世界观与长期规则（摘要）】\n{_trim_prompt_text(bible, 2200)}",
        f"【本书硬设定锚点（JSON摘录）】\n{_trim_prompt_text(fj_block, 1800)}",
    ]
    user_parts.extend(memory_blocks)
    if available_entities:
        user_parts.append(available_entities)
    user_parts.extend(
        [
            f"【本章信息】第 {chapter_no} 章"
            f"{('，章标题建议：' + chapter_title_hint) if chapter_title_hint else ''}",
            f"【字数硬约束】\n{_strong_chapter_word_rule(target_words)}",
            f"【前文衔接摘录（含再前一章与上一章结尾）】\n{continuity_excerpt or '（首章）'}",
            f"【待核对正文】\n{chapter_text}",
            "【要求】\n"
            "1) 若发现与 world_rules/canonical_timeline/设定防火墙冲突，必须修正正文；不得只做说明。\n"
            "2) 允许做必要的因果补线、人物状态修正、伏笔承接与收束呈现，但不要大幅重写风格。\n"
            "3) 若正文使用了未在【当前可用物品与技能】中列出的物品/技能，必须改成已铺垫版本，或补出明确引入过程。\n"
            "4) 维持中文小说的正常排版与阅读节奏：对话、动作、场景切换、心理变化处应合理换段。\n"
            "5) 修正后正文仍必须严格满足上述目标字数范围要求。\n"
            "6) 只输出最终正文。",
        ]
    )
    user = "\n\n".join(user_parts)
    if chapter_no == 1:
        user = (
            user
            + "\n\n【全书第1章补充】若待核对正文存在「读完全章仍不知基本世界/主角处境/故事因何启动」或明显莫名其妙切入，"
            "须做最小增删补，使上述信息在章内可理解呈现，并仍满足字数范围。"
        )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _audit_chapter_against_plan_messages(
    *,
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
    chapter_text: str,
) -> list[dict[str, str]]:
    plan_payload = chapter_plan_guard_payload(
        beats,
        chapter_no=chapter_no,
        plan_title=plan_title,
    )
    sys = (
        "你是小说章计划执行审计员。只输出一个 JSON 对象，不要 Markdown、不要解释。"
        '格式：{"ok":boolean,"violations":["..."],"warnings":["..."]}。'
        "仅在正文明显违反执行卡硬约束时写入 violations："
        "必须发生却缺失、必须承接却完全失联、写出了 must_not、提前写出了 reserved_for_later、"
        "实质推进明显超过 allowed_progress。"
        "ending_hook 与 style_guardrails 只作为 warnings，不作为 violations。"
    )
    user = (
        "【执行卡硬约束】\n"
        f"{json.dumps(plan_payload, ensure_ascii=False)}\n\n"
        "【待审正文】\n"
        f"{(chapter_text or '')[:18000]}"
    )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _fix_chapter_to_plan_messages(
    novel: Novel,
    *,
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
    memory_json: str,
    continuity_excerpt: str,
    chapter_text: str,
    violations: list[str],
    db: Any = None,
) -> list[dict[str, str]]:
    efw = effective_framework_json_for_prompt(db, novel)
    bible = (
        format_stage_aware_framework_bible(novel, chapter_no, framework_json_for_arcs=efw)
        if db
        else (novel.framework_markdown[:6000] if novel.framework_markdown else novel.background)
    )
    fj_block = truncate_framework_json_stage_aware(efw, chapter_no)
    target_words = _chapter_target_words(novel)
    plan_payload = chapter_plan_guard_payload(
        beats,
        chapter_no=chapter_no,
        plan_title=plan_title,
    )
    memory_blocks = _build_chapter_context_bundle(
        memory_json=memory_json,
        chapter_no=chapter_no,
        chapter_title_hint="",
        chapter_plan_hint=json.dumps(plan_payload, ensure_ascii=False),
        use_cold_recall=False,
        cold_recall_items=0,
        db=db,
        novel_id=novel.id,
        include_entity_recall=False,
        include_rag=False,
    )
    available_entities = ""
    if db:
        try:
            available_entities = format_available_entities_for_chapter(db, novel.id, chapter_no)
        except Exception:
            available_entities = ""
    sys = (
        "你是小说执行卡纠偏编辑。你的任务是对正文做最小必要改写，使其重新满足本章执行卡。"
        "必须补齐 must_happen / required_callbacks，删除或改写 must_not 与 reserved_for_later 的越界内容，"
        "并把剧情收回 allowed_progress 允许的边界内。"
        "不得破坏既有世界观、人物逻辑与前后承接。只输出修订后的正文，不要解释。\n"
        f"{_ANTI_AI_FLAVOR_BLOCK}"
    )
    user_parts = [
        f"【世界观与长期规则（摘要）】\n{_trim_prompt_text(bible, 2000)}",
        f"【本书硬设定锚点（JSON摘录）】\n{_trim_prompt_text(fj_block, 1800)}",
    ]
    user_parts.extend(memory_blocks)
    if available_entities:
        user_parts.append(available_entities)
    user_parts.extend(
        [
            f"【字数硬约束】\n{_strong_chapter_word_rule(target_words)}",
            f"【前文衔接摘录】\n{continuity_excerpt or '（首章）'}",
            "【执行卡】\n" + json.dumps(plan_payload, ensure_ascii=False),
            "【当前正文】\n" + chapter_text,
            "【已发现问题】\n" + json.dumps(violations or [], ensure_ascii=False),
            "【修正要求】\n"
            "1) 优先解决硬约束 violations；\n"
            "2) 保持本章标题行格式与章号正确；\n"
            "3) 若正文使用了未在【当前可用物品与技能】中列出的物品/技能，必须改成已铺垫版本，或明确补出引入过程；\n"
            "4) 尽量保留已有可用段落，只改冲突处；\n"
            "5) 章末尽量贴近 ending_hook，但不要额外越级推进；\n"
            "6) 修正后正文必须严格满足上述目标字数范围要求；\n"
            "7) 只输出最终正文。",
        ]
    )
    user = "\n\n".join(user_parts)
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _de_ai_chapter_messages(
    novel: Novel,
    *,
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
    chapter_text: str,
    db: Any = None,
) -> list[dict[str, str]]:
    style_block = _writing_style_block(getattr(novel, "writing_style", None))
    plan_payload = chapter_plan_guard_payload(
        beats,
        chapter_no=chapter_no,
        plan_title=plan_title,
    )
    target_words = _chapter_target_words(novel)
    original_body_chars = int(
        chapter_content_metrics(chapter_text).get("body_chars", 0) or 0
    )
    sys = (
        "你是中文网文润色编辑。你的任务是去除正文中的 AI 味，但不得改动剧情事实。"
        "你只能改写表达方式，不能改事件顺序、人物决定、信息边界、伏笔状态、章末结果。"
        "必须保留第一行章节标题，且章号与章名不得改。"
        "允许做的事：删解释腔、删总结腔、删空泛心理描写、删套路化比喻、删重复修饰，"
        "把'告诉读者'改成动作/对白/观察里自然呈现。"
        "禁止新增设定、禁止补新剧情、禁止改变执行卡中的必须发生项和章末钩子。"
        "只输出润色后的正文，不要解释。\n"
        f"{_ANTI_AI_FLAVOR_BLOCK}"
    )
    parts: list[str] = []
    if style_block:
        parts.append(style_block)
    parts.extend(
        [
            "【执行卡（仅作边界，不可改剧情事实）】\n"
            + json.dumps(plan_payload, ensure_ascii=False),
            "【润色要求】\n"
            "1) 只改描述，不改剧情；\n"
            "2) 禁止把概述性句子改成新的剧情发展；\n"
            "3) 可以缩短、拆句、换更自然的表达，但不要扩写，也不要大幅删减有效情节与描写；\n"
            f"4) {_strong_chapter_word_rule(target_words)}\n"
            f"5) 当前正文约 {original_body_chars} 字，润色后必须重新计数并修正到允许范围内；\n"
            "6) 物品、技能、人物关系和章末结果都视为硬事实，禁止润色时改动；\n"
            "7) 优先处理解释腔、总结腔、空泛心理句、重复修饰和机械比喻。",
            f"【当前正文】\n{chapter_text}",
        ]
    )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _expressive_enhance_chapter_messages(
    novel: Novel,
    *,
    chapter_no: int,
    plan_title: str,
    beats: dict[str, Any],
    chapter_text: str,
    strength: str,
    db: Any = None,
) -> list[dict[str, str]]:
    plan_payload = chapter_plan_guard_payload(
        beats,
        chapter_no=chapter_no,
        plan_title=plan_title,
    )
    st = (strength or "safe").strip().lower()
    strength_hint = {
        "safe": "轻量：只加强少数画面/对白节奏，避免大幅增删。",
        "strong": "中等：可重排小段落、增强镜头感与潜台词，不得动事实。",
        "cinematic": "强：更电影化分镜与张力，仍禁止动事实。",
    }.get(st, "以提升阅读张力为主，禁止改事件。")
    style_block = _writing_style_block(getattr(novel, "writing_style", None))
    voice_profiles = _format_character_voice_profiles_for_prompt(db, novel.id, chapter_no)
    state_snapshot = _format_state_snapshot_for_prompt(db, novel.id, chapter_no)
    sys = (
        "你是资深网文执行编辑。本轮只负责「表现力增强」：强画面、动作、感官、对白与潜台词；"
        "必须保留首行章标题。禁止增删/颠倒/改写剧情硬事实、禁止新设定、禁止改人名地名、禁止改章末收束与执行卡'必须'项。"
        f"\n强度：{strength_hint}\n{_ANTI_AI_FLAVOR_BLOCK}"
    )
    parts: list[str] = []
    if style_block:
        parts.append(style_block)
    if voice_profiles:
        parts.append(voice_profiles)
    if state_snapshot:
        parts.append(state_snapshot)
    parts.extend(
        [
            "【硬边界：执行卡】\n" + json.dumps(plan_payload, ensure_ascii=False),
            f"【当前正文】\n{chapter_text}",
        ]
    )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _volume_plan_extract_json_object(raw: str) -> str | None:
    """从文本中提取首个平衡的 `{...}` JSON 对象（忽略字符串内的花括号）。"""
    s = raw.strip()
    i = s.find("{")
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(s)):
        ch = s[j]
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[i : j + 1]
    return None


def _volume_plan_escape_raw_newlines_in_strings(blob: str) -> str:
    """将 JSON 字符串值内的裸换行/回车/制表符转义（模型在长 plot_summary 中常犯）。"""
    out: list[str] = []
    i = 0
    in_str = False
    esc = False
    while i < len(blob):
        ch = blob[i]
        if esc:
            out.append(ch)
            esc = False
            i += 1
            continue
        if in_str:
            if ch == "\\":
                out.append(ch)
                esc = True
                i += 1
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                i += 1
                continue
            if ch == "\n":
                out.append("\\n")
                i += 1
                continue
            if ch == "\r":
                out.append("\\r")
                i += 1
                continue
            if ch == "\t":
                out.append("\\t")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
        i += 1
    return "".join(out)


def _volume_plan_strip_trailing_commas(blob: str) -> str:
    """移除对象/数组末尾多余逗号。"""
    s = re.sub(r",\s*}", "}", blob)
    s = re.sub(r",\s*]", "]", s)
    return s


def _extract_last_fenced_block(raw: str) -> str | None:
    blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw or "", flags=re.IGNORECASE)
    if not blocks:
        return None
    return str(blocks[-1]).strip()


def _extract_balanced_json_object(raw: str) -> str | None:
    s = str(raw or "")
    start: int | None = None
    depth = 0
    in_str = False
    escape = False
    last_full: str | None = None
    for idx, ch in enumerate(s):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
            continue
        if ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    last_full = s[start : idx + 1].strip()
                    start = None
    if last_full:
        return last_full
    return None


def _strip_last_fenced_block(raw: str) -> str:
    text = str(raw or "").strip()
    return re.sub(
        r"\n*```(?:json)?\s*[\s\S]*?```\s*$",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).rstrip()


def _parse_framework_json_from_reply(raw: str) -> dict[str, Any]:
    s = str(raw or "").strip()
    if not s:
        raise ValueError("框架生成结果为空")

    candidates: list[str] = []
    for c in (
        _extract_last_fenced_block(s),
        _extract_balanced_json_object(s),
        s,
    ):
        if c and c not in candidates:
            candidates.append(c)

    last_err: Exception | None = None
    for blob in candidates:
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
        except Exception as e:
            last_err = e

    for blob in candidates:
        try:
            data = json_repair_loads(blob)
            if isinstance(data, dict):
                return data
        except Exception as e:
            last_err = e

    raise ValueError("生成的大纲结构化 JSON 不完整，疑似输出被截断，请点击重新生成") from last_err


def _notify_progress(cb: Callable[[str], None] | None, message: str) -> None:
    if cb is None:
        return
    try:
        cb(message)
    except Exception:
        logger.exception("framework progress callback failed")


def _trim_base_framework_markdown(markdown: str) -> str:
    text = str(markdown or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if not line.lstrip().startswith("##"):
            continue
        compact = re.sub(r"\s+", "", line)
        if (
            "卷级概览" in compact
            or "分卷剧情大纲" in compact
            or "(Arcs)" in compact
            or "（Arcs）" in compact
        ):
            return "\n".join(lines[:idx]).rstrip()
    return text


def _strip_leading_markdown_title(markdown: str) -> str:
    text = str(markdown or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        return "\n".join(lines[1:]).lstrip()
    return text


def _merge_framework_markdown_sections(base_markdown: str, arcs_markdown: str) -> str:
    base = _trim_base_framework_markdown(base_markdown)
    extra = _strip_leading_markdown_title(arcs_markdown)
    if not base:
        return extra
    if not extra:
        return base
    return f"{base.rstrip()}\n\n{extra.lstrip()}"


def _sanitize_base_framework_payload(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data or {})
    out.pop("arcs", None)
    out.pop("volume_overview", None)
    out.pop("volumes", None)
    return out


def _merge_framework_payloads(
    base_payload: dict[str, Any],
    arcs_payload: dict[str, Any],
) -> dict[str, Any]:
    merged = _sanitize_base_framework_payload(base_payload)
    if isinstance(arcs_payload.get("volume_overview"), list):
        merged["volume_overview"] = arcs_payload["volume_overview"]
    arcs = arcs_payload.get("arcs")
    if not isinstance(arcs, list) or not arcs:
        raise ValueError("二次生成分卷剧情大纲失败：未返回有效的 arcs")
    merged["arcs"] = arcs
    return merged


def coerce_novel_outline_base_fields(
    markdown: str | None, json_str: str | None
) -> tuple[str, str]:
    """小说表仅存「基础大纲」：世界观/人物/主线；去掉 arcs 与卷级概览等。"""
    data = _safe_json_dict(json_str or "{}")
    base_j = json.dumps(_sanitize_base_framework_payload(data), ensure_ascii=False)
    base_md = _trim_base_framework_markdown(markdown or "")
    return base_md, base_j


def _collect_arc_body_for_markdown(arc: dict) -> str:
    """从单条 arc 对象提取可读正文（兼容 summary / sub_arcs / key_events 等结构）。"""
    chunks: list[str] = []

    for key in ("summary", "description", "detail", "plot", "outline", "content", "notes"):
        v = arc.get(key)
        if isinstance(v, str) and v.strip():
            chunks.append(v.strip())

    subs = arc.get("sub_arcs")
    if isinstance(subs, list):
        for j, sa in enumerate(subs, 1):
            if not isinstance(sa, dict):
                continue
            st = str(sa.get("title") or sa.get("name") or f"子阶段{j}").strip()
            block: list[str] = []
            for key in ("summary", "description", "detail", "plot"):
                vv = sa.get(key)
                if isinstance(vv, str) and vv.strip():
                    block.append(vv.strip())
            if block:
                body = " ".join(block)
                chunks.append(f"**{st}** {body}" if st else body)

    ke = arc.get("key_events")
    if isinstance(ke, list):
        bullets: list[str] = []
        for x in ke:
            if isinstance(x, str) and x.strip():
                bullets.append(f"- {x.strip()}")
            elif isinstance(x, dict):
                t = str(x.get("title") or x.get("name") or "").strip()
                body = (
                    x.get("summary")
                    or x.get("text")
                    or x.get("event")
                    or x.get("description")
                )
                if isinstance(body, str) and body.strip():
                    if t:
                        bullets.append(f"- **{t}** {body.strip()}")
                    else:
                        bullets.append(f"- {body.strip()}")
        if bullets:
            chunks.append("\n".join(bullets))

    return "\n\n".join(chunks) if chunks else ""


def render_volume_arcs_markdown(volume_no: int, arcs: list[Any]) -> str:
    """由本卷 arcs 列表生成可读 Markdown，写入 novel_volumes.outline_markdown。"""
    lines: list[str] = [f"## 第{volume_no}卷 分卷剧情弧线（Arcs）", ""]
    n = 0
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        n += 1
        title = str(arc.get("title") or arc.get("name") or f"弧线{n}").strip()
        b = arc_bounds_from_dict(arc)
        rng = f"（约第{b[0]}—{b[1]}章）" if b else ""
        body = _collect_arc_body_for_markdown(arc)
        lines.append(f"### {title} {rng}".rstrip())
        if body:
            lines.append(body)
        else:
            lines.append("（本 5 章段未返回 summary，请重新生成分卷剧情。）")
        hook = arc.get("hook")
        if isinstance(hook, str) and hook.strip():
            lines.append(f"- **钩子**：{hook.strip()}")
        mn = arc.get("must_not")
        if isinstance(mn, list) and mn:
            mns = [str(x).strip() for x in mn if str(x).strip()]
            if mns:
                lines.append(
                    "- **禁止推进（本段内不得）**："
                    + "；".join(mns)
                )
        elif isinstance(mn, str) and mn.strip():
            lines.append(f"- **禁止推进（本段内不得）**：{mn.strip()}")
        pa = arc.get("progress_allowed")
        if isinstance(pa, list) and pa:
            pas = [str(x).strip() for x in pa if str(x).strip()]
            if pas:
                lines.append(
                    "- **允许推进（本段应完成/可写）**："
                    + "；".join(pas)
                )
        elif isinstance(pa, str) and pa.strip():
            lines.append(f"- **允许推进（本段应完成/可写）**：{pa.strip()}")
        lines.append("")
    if n == 0:
        return ""
    return "\n".join(lines).rstrip()


def _build_prior_volumes_arcs_context_block(
    framework_json: dict[str, Any] | None,
    *,
    min_target_volume_no: int,
    volume_size: int,
    max_chars: int = 14000,
    max_prior_volumes: int = 3,
) -> str:
    """
    增量生成分卷 arcs 时，把「目标卷之前」已存在于 framework_json 的弧线摘要喂给模型，
    避免后卷与已写前卷脱节。（仅用于 prompt，不修改存库结构。）

    默认只纳入「紧邻新卷之前」的若干整卷弧线（max_prior_volumes），避免第 10 卷等把全书
    前 9 卷全文塞进 prompt；主线与设定已由第一阶段基础大纲覆盖。
    若仍超长，截断时**保留靠近新卷的一端**（尾部），避免丢掉刚发生的剧情。
    """
    if min_target_volume_no <= 1 or not isinstance(framework_json, dict):
        return ""
    arcs = framework_json.get("arcs")
    if not isinstance(arcs, list) or not arcs:
        return ""
    ch_start = (min_target_volume_no - 1) * volume_size + 1
    prev_last_vol = min_target_volume_no - 1
    span = max(1, int(max_prior_volumes))
    earliest_vol = max(1, prev_last_vol - span + 1)
    earliest_ch = (earliest_vol - 1) * volume_size + 1
    picked: list[dict[str, Any]] = []
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        b = arc_bounds_from_dict(arc)
        if not b:
            continue
        fc, _tc = b
        if fc < ch_start and fc >= earliest_ch:
            picked.append(arc)

    def _sort_key(a: dict[str, Any]) -> int:
        b2 = arc_bounds_from_dict(a)
        return b2[0] if b2 else 999999

    picked.sort(key=_sort_key)
    lines: list[str] = []
    for arc in picked:
        title = str(arc.get("title") or arc.get("name") or "弧线").strip()
        b = arc_bounds_from_dict(arc)
        rng = f"第{b[0]}—{b[1]}章" if b else "章号未定"
        body = _collect_arc_body_for_markdown(arc)
        if body:
            body = body[:900]
        hook = arc.get("hook")
        hook_s = hook.strip()[:400] if isinstance(hook, str) and hook.strip() else ""
        chunk = f"### {title}（{rng}）\n{(body or '（无 summary）').strip()}"
        if hook_s:
            chunk += f"\n卷末/段末钩子：{hook_s}"
        lines.append(chunk)
    if not lines:
        return ""
    out = "\n\n".join(lines)
    if len(out) > max_chars:
        # 保留靠近目标卷的一端（列表已按章号升序，尾部更关键）
        tail = out[-(max_chars - 48) :].lstrip()
        out = "…（更早卷弧线已从摘要中省略；以下贴近当前卷）\n" + tail
    return out


def _merge_arcs_into_framework(
    current_fw: dict[str, Any],
    new_arcs_payload: dict[str, Any],
    target_volume_nos: list[int] | None = None,
) -> dict[str, Any]:
    """
    增量合并：将新生成的 arcs 替换/追加到当前 framework_json 中。
    如果指定了 target_volume_nos，只替换对应卷号的 arcs；
    否则全量替换 arcs 数组。
    """
    merged = dict(current_fw or {})

    # 合并 volume_overview
    if isinstance(new_arcs_payload.get("volume_overview"), list):
        existing_vo = merged.get("volume_overview")
        if isinstance(existing_vo, list) and target_volume_nos:
            # 增量替换：只替换指定卷号的 volume_overview 条目
            vol_set = set(target_volume_nos)
            new_vo = [v for v in existing_vo if not isinstance(v, dict) or v.get("volume_no") not in vol_set]
            new_vo.extend(v for v in new_arcs_payload["volume_overview"] if isinstance(v, dict))
            merged["volume_overview"] = new_vo
        else:
            merged["volume_overview"] = new_arcs_payload["volume_overview"]

    # 合并 arcs
    new_arcs = new_arcs_payload.get("arcs")
    if isinstance(new_arcs, list) and new_arcs:
        if target_volume_nos:
            # 增量替换：按 from_chapter/to_chapter 判断卷号范围
            existing_arcs = merged.get("arcs")
            if not isinstance(existing_arcs, list):
                existing_arcs = []
            volume_size = 50
            # 计算目标卷的章节范围
            target_chapter_ranges: list[tuple[int, int]] = []
            for vn in target_volume_nos:
                lo = (vn - 1) * volume_size + 1
                hi = vn * volume_size
                target_chapter_ranges.append((lo, hi))

            def _arc_in_target(arc: dict[str, Any]) -> bool:
                if not isinstance(arc, dict):
                    return False
                b = arc_bounds_from_dict(arc)
                if not b:
                    return False
                fc, tc = b
                for lo, hi in target_chapter_ranges:
                    if fc >= lo and fc <= hi:
                        return True
                    if tc >= lo and tc <= hi:
                        return True
                    if fc < lo and tc >= hi:
                        return True
                return False

            # 保留不在目标卷范围内的旧 arcs
            kept = [a for a in existing_arcs if not _arc_in_target(a)]
            kept.extend(new_arcs)
            # 按 from_chapter 排序
            def _arc_sort_key(a: dict[str, Any]) -> int:
                if isinstance(a, dict):
                    b = arc_bounds_from_dict(a)
                    if b:
                        return b[0]
                return 99999
            kept.sort(key=_arc_sort_key)
            merged["arcs"] = kept
        else:
            merged["arcs"] = new_arcs

    return merged


def _volume_plan_parse_llm_json_to_dict(raw: str) -> dict[str, Any]:
    """多步容错解析卷章计划 JSON。"""
    s = (raw or "").strip()
    if not s:
        raise json.JSONDecodeError("empty", s, 0)

    candidates: list[str] = []
    for c in (s, _volume_plan_extract_json_object(s) or ""):
        if c and c not in candidates:
            candidates.append(c)

    variants: list[str] = []
    for c in candidates:
        if not c:
            continue
        for v in (
            c,
            _volume_plan_strip_trailing_commas(c),
            _volume_plan_escape_raw_newlines_in_strings(c),
            _volume_plan_escape_raw_newlines_in_strings(_volume_plan_strip_trailing_commas(c)),
        ):
            if v and v not in variants:
                variants.append(v)

    last_err: json.JSONDecodeError | None = None
    for blob in variants:
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"chapters": data}
        except json.JSONDecodeError as e:
            last_err = e

    # LLM 常输出未闭合字符串、字符串内未转义 "、截断等；json-repair 可修复多数情况
    last_repair_err: Exception | None = None
    for blob in variants:
        try:
            data = json_repair_loads(blob)
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"chapters": data}
        except Exception as e:
            last_repair_err = e
    if last_repair_err is not None and last_err is not None:
        raise last_err from last_repair_err
    if last_err is not None:
        raise last_err
    raise json.JSONDecodeError("无法解析为对象", s, 0)


class NovelLLMService:
    """小说相关 302 Chat；默认智谱 GLM-4.7，可按配置开启联网搜索。"""

    def __init__(self, billing_user_id: str | None = None) -> None:
        # 与历史实现保持兼容：一致性修订/记忆刷新仍走 AI302Client（sync + async）
        self._client = AI302Client()
        self._billing_user_id = billing_user_id

    @staticmethod
    def _timeout_retry_attempts() -> int:
        return max(1, int(settings.novel_llm_timeout_retries) + 1)

    @staticmethod
    def _timeout_retry_backoff(attempt: int) -> float:
        base = max(0.0, float(settings.novel_llm_timeout_retry_backoff_seconds))
        return base * max(1, attempt)

    async def _chat_text_with_timeout_retry(
        self,
        *,
        router: LLMRouter,
        operation: str,
        novel_id: str,
        chapter_no: int | None = None,
        timeout: float,
        **kwargs: Any,
    ) -> str:
        attempts = self._timeout_retry_attempts()
        for attempt in range(1, attempts + 1):
            try:
                return await router.chat_text(timeout=timeout, **kwargs)
            except httpx.TimeoutException:
                logger.warning(
                    "llm timeout(async) | op=%s novel_id=%s chapter_no=%s attempt=%s/%s timeout=%.1fs provider=%s model=%s",
                    operation,
                    novel_id,
                    chapter_no,
                    attempt,
                    attempts,
                    timeout,
                    "ai302",
                    router.model or "-",
                )
                if attempt >= attempts:
                    raise
                await asyncio.sleep(self._timeout_retry_backoff(attempt))

    def _chat_text_sync_with_timeout_retry(
        self,
        *,
        router: LLMRouter,
        operation: str,
        novel_id: str,
        chapter_no: int | None = None,
        timeout: float,
        **kwargs: Any,
    ) -> str:
        attempts = self._timeout_retry_attempts()
        for attempt in range(1, attempts + 1):
            try:
                return router.chat_text_sync(timeout=timeout, **kwargs)
            except httpx.TimeoutException:
                logger.warning(
                    "llm timeout(sync) | op=%s novel_id=%s chapter_no=%s attempt=%s/%s timeout=%.1fs provider=%s model=%s",
                    operation,
                    novel_id,
                    chapter_no,
                    attempt,
                    attempts,
                    timeout,
                    "ai302",
                    router.model or "-",
                )
                if attempt >= attempts:
                    raise
                time.sleep(self._timeout_retry_backoff(attempt))

    @staticmethod
    def _bill_kw(db: Any, billing_user_id: str | None) -> dict[str, Any]:
        if not billing_user_id:
            return {}
        out: dict[str, Any] = {"billing_user_id": billing_user_id}
        if db is not None:
            out["billing_db"] = db
        return out

    def _router(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        db: Any = None,
    ) -> LLMRouter:
        # 仅支持 302.AI；ignore provider
        return LLMRouter(model=model, user_id=self._billing_user_id, db=db)

    def _novel_web_search(
        self,
        db: Any = None,
        *,
        flow: Literal[
            "default",
            "inspiration",
            "generate",
            "volume_plan",
            "memory_refresh",
        ] = "default",
    ) -> bool:
        fallback = (
            True if flow == "inspiration" else bool(settings.ai302_novel_web_search)
        )
        close_db = False
        use_db = db
        if use_db is None:
            use_db = SessionLocal()
            close_db = True
        try:
            cfg = get_runtime_web_search_config(use_db, user_id=self._billing_user_id)
            if flow == "inspiration":
                return bool(cfg.novel_inspiration_web_search)
            if flow == "generate":
                return bool(cfg.novel_generate_web_search)
            if flow == "volume_plan":
                return bool(cfg.novel_volume_plan_web_search)
            if flow == "memory_refresh":
                return bool(cfg.novel_memory_refresh_web_search)
            return bool(cfg.novel_web_search)
        except Exception:
            return fallback
        finally:
            if close_db and use_db is not None:
                use_db.close()

    @staticmethod
    def _messages_chars(messages: list[dict[str, str]]) -> int:
        return sum(len(m.get("content", "")) for m in messages)

    @staticmethod
    def _trim_text_block(block: str, max_chars: int) -> str:
        raw = str(block or "").strip()
        if max_chars <= 0 or len(raw) <= max_chars:
            return raw
        half = max_chars // 2
        if half < 80:
            return raw[-max_chars:]
        return raw[:half] + "\n…（中间已裁剪）…\n" + raw[-(max_chars - half - 14):]

    @classmethod
    def _budget_chapter_messages(
        cls,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        budget = max(12000, int(settings.novel_prompt_char_budget))
        if cls._messages_chars(messages) <= budget:
            return messages

        trimmed = [dict(m) for m in messages]
        if len(trimmed) < 2:
            return trimmed
        user_text = trimmed[1].get("content", "")
        blocks = user_text.split("\n\n")
        lowered = [
            ("【最近已审定章节完整正文（增强衔接）】", 9000),
            ("【前文衔接摘录", 3200),
            ("【与本章最相关的记忆召回】", 2600),
            ("【冷层历史召回（按需）】", 1800),
            ("【过程章素材（用于降速但不拖沓）】", 1200),
        ]
        for marker, keep_chars in lowered:
            if cls._messages_chars(trimmed) <= budget:
                break
            for idx, block in enumerate(blocks):
                if block.startswith(marker):
                    blocks[idx] = cls._trim_text_block(block, keep_chars)
                    break
            trimmed[1]["content"] = "\n\n".join(blocks)

        if cls._messages_chars(trimmed) > budget:
            trimmed[1]["content"] = cls._trim_text_block(trimmed[1]["content"], budget - len(trimmed[0].get("content", "")) - 200)
        return trimmed

    async def inspiration_chat(self, messages: list[dict[str, str]], db: Any = None) -> str:
        """新建小说阶段：多轮对话 + 强制联网搜索，获取创作灵感。"""
        router = self._router(db=db)
        system = (
            "你是网络小说策划助手。请使用联网搜索能力，根据用户问题检索题材热点、类型套路、设定参考，"
            "并给出可执行的创作灵感。回答尽量结构化，可包含：题材方向、核心冲突、人设建议、世界观要点、文风提示。"
            "若用户希望填入表单，请在末段用简短列表对应：书名建议、简介要点、背景设定要点、文风关键词。"
        )
        out: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            out.append({"role": role, "content": m["content"]})
        return await router.chat_text(
            messages=out,
            temperature=0.75,
            web_search=self._novel_web_search(db, flow="inspiration"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )

    async def inspiration_chat_stream(
        self, messages: list[dict[str, str]], db: Any = None
    ) -> AsyncIterator[dict[str, str]]:
        router = self._router(db=db)
        system = (
            "你是网络小说策划助手。请使用联网搜索能力，根据用户问题检索题材热点、类型套路、设定参考，"
            "并给出可执行的创作灵感。回答尽量结构化，可包含：题材方向、核心冲突、人设建议、世界观要点、文风提示。"
            "若用户希望填入表单，请在末段用简短列表对应：书名建议、简介要点、背景设定要点、文风关键词。"
        )
        out: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            out.append({"role": role, "content": m["content"]})
        async for evt in router.chat_text_stream(
            messages=out,
            temperature=0.75,
            web_search=self._novel_web_search(db, flow="inspiration"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        ):
            yield evt

    async def chapter_context_chat(
        self,
        novel: Novel,
        *,
        memory_json: str,
        approved_chapters_summary: str,
        continuity_excerpt: str,
        messages: list[dict[str, str]],
        llm_provider: str | None = None,
        llm_model: str | None = None,
        db: Any = None,
    ) -> str:
        """章节侧问答：基于小说框架、记忆与已写章节上下文回答问题。"""
        router = self._router(provider=llm_provider, model=llm_model, db=db)
        bible = novel.framework_markdown[:6000] if novel.framework_markdown else novel.background
        fj_block = truncate_framework_json(effective_framework_json_for_prompt(db, novel), 4000)
        memory_blocks = _build_chapter_context_bundle(
            memory_json=memory_json,
            chapter_no=0,
            chapter_title_hint="",
            chapter_plan_hint="".join(m.get("content", "") for m in messages[-2:]),
            use_cold_recall=False,
            cold_recall_items=0,
            db=db,
            novel_id=novel.id,
        )
        sys = (
            "你是小说章节助手。请严格基于用户提供的小说上下文回答："
            "框架 Markdown、框架 JSON、结构化记忆、已写章节摘录。"
            "目标：帮助用户判断设定一致性、续写方向、伏笔回收、人物动机、节奏与冲突设计。"
            "若上下文中没有明确依据，请明确说明「当前信息不足」，并给出最小化假设选项。"
            "不要编造未提供的硬设定。回答尽量简洁、可执行。"
        )
        context_user = (
            f"【小说标题】{novel.title}\n\n"
            f"【框架 Markdown】\n{bible}\n\n"
            f"【框架 JSON（截断）】\n{fj_block}\n\n"
            f"{chr(10).join(memory_blocks)}\n\n"
            f"【已审定章节摘要（近段）】\n{approved_chapters_summary or '（暂无）'}\n\n"
            f"【连续性衔接摘录】\n{continuity_excerpt or '（暂无）'}"
        )
        out: list[dict[str, str]] = [
            {"role": "system", "content": sys},
            {"role": "user", "content": context_user},
        ]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            out.append({"role": role, "content": content})

        return await router.chat_text(
            messages=out,
            temperature=0.45,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )

    async def chapter_context_chat_stream(
        self,
        novel: Novel,
        *,
        memory_json: str,
        approved_chapters_summary: str,
        continuity_excerpt: str,
        messages: list[dict[str, str]],
        llm_provider: str | None = None,
        llm_model: str | None = None,
        db: Any = None,
    ) -> AsyncIterator[dict[str, str]]:
        router = self._router(provider=llm_provider, model=llm_model, db=db)
        bible = novel.framework_markdown[:6000] if novel.framework_markdown else novel.background
        fj_block = truncate_framework_json(effective_framework_json_for_prompt(db, novel), 4000)
        memory_blocks = _build_chapter_context_bundle(
            memory_json=memory_json,
            chapter_no=0,
            chapter_title_hint="",
            chapter_plan_hint="".join(m.get("content", "") for m in messages[-2:]),
            use_cold_recall=False,
            cold_recall_items=0,
            db=db,
            novel_id=novel.id,
        )
        sys = (
            "你是小说章节助手。请严格基于用户提供的小说上下文回答："
            "框架 Markdown、框架 JSON、结构化记忆、已写章节摘录。"
            "目标：帮助用户判断设定一致性、续写方向、伏笔回收、人物动机、节奏与冲突设计。"
            "若上下文中没有明确依据，请明确说明「当前信息不足」，并给出最小化假设选项。"
            "不要编造未提供的硬设定。回答尽量简洁、可执行。"
        )
        context_user = (
            f"【小说标题】{novel.title}\n\n"
            f"【框架 Markdown】\n{bible}\n\n"
            f"【框架 JSON（截断）】\n{fj_block}\n\n"
            f"{chr(10).join(memory_blocks)}\n\n"
            f"【已审定章节摘要（近段）】\n{approved_chapters_summary or '（暂无）'}\n\n"
            f"【连续性衔接摘录】\n{continuity_excerpt or '（暂无）'}"
        )
        out: list[dict[str, str]] = [
            {"role": "system", "content": sys},
            {"role": "user", "content": context_user},
        ]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            out.append({"role": role, "content": content})
        async for evt in router.chat_text_stream(
            messages=out,
            temperature=0.45,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        ):
            yield evt

    def _framework_style_block_for_novel(self, novel: Novel, db: Any = None) -> str:
        if not novel.writing_style_id or not db:
            return ""
        ws = db.get(WritingStyle, novel.writing_style_id)
        if not ws:
            return ""
        return f"\n【写作风格深度定制要求】\n{_writing_style_block(ws)}\n"

    def _framework_target_meta(self, novel: Novel) -> tuple[int, int, int]:
        target_chapters = int(getattr(novel, "target_chapters", 0) or 0)
        volume_size = 50
        volume_n = (target_chapters + volume_size - 1) // volume_size if target_chapters > 0 else 0
        return target_chapters, volume_size, volume_n

    async def _generate_framework_base_stage(
        self,
        novel: Novel,
        *,
        mode: Literal["create", "regen", "characters"],
        db: Any = None,
        instruction: str = "",
        characters: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        router = self._router(db=db)
        ref = load_reference_text_for_llm(
            novel.reference_storage_key,
            novel.id,
            novel.reference_public_url,
        )
        target_chapters, _, _ = self._framework_target_meta(novel)
        ws_block = self._framework_style_block_for_novel(novel, db=db)

        tc_scale = int(target_chapters) if isinstance(target_chapters, int) and target_chapters > 0 else 120
        if tc_scale >= 300:
            framework_depth_contract = (
                "【篇幅与细节契约（须严格遵守）】目标章数偏多，禁止「设定名词堆砌」或一句话带过。\n"
                "- Markdown 三部分合计建议不少于 **2800 汉字**；其中「## 一、世界观与核心设定」不少于 **1000 汉字**，"
                "须覆盖：权力结构/日常与异常的张力、力量或规则的**代价与边界**、信息如何流动、至少两处可被剧情反复利用的「硬设定钩子」。\n"
                "- 「## 二、核心人物」至少 **6 名**有姓名的关键角色（主角、主要对手或制度性阻力、导师/盟友、至少两名功能性强的配角）；"
                "每人 Markdown 不少于 **180 汉字**，写清：外在目标、内在匮乏或恐惧、与同阵营/对手的关系张力、可被读者记住的行为或语言习惯。\n"
                "- 「## 三、主线剧情与长期矛盾」不少于 **700 汉字**，写出阶段性升级与至少两条支线种子。\n"
                "- JSON：characters 数组至少 **6** 条；每人 traits 用分号串联 **不少于 6 条**可表演化标签；motivation 每人不少于 **70 汉字**；"
                "world_rules 总字数不少于 **220 汉字**且用短句分条；main_plot 不少于 **400 汉字**，须以「阶段—关键事件—阶段性后果」链式写出至少三段递进，"
                "并能读出「开篇势能—中段对抗—终局方向/悬念」；"
                "themes 不少于 **40 汉字**。\n"
            )
        elif tc_scale <= 60:
            framework_depth_contract = (
                "【篇幅与细节契约（须严格遵守）】偏中短篇仍要写透可用设定。\n"
                "- Markdown 三部分合计建议不少于 **1200 汉字**；「## 一」不少于 **420 汉字**；「## 二」至少 **4 名**核心角色，每人不少于 **110 汉字**；"
                "「## 三」不少于 **380 汉字**。\n"
                "- JSON：characters 至少 **4** 条；traits 每人不少于 **4** 条标签；motivation 每人不少于 **45 汉字**；"
                "world_rules 不少于 **120 汉字**；main_plot 不少于 **220 汉字**，须含至少两段「谁做什么→遭遇什么→得到/失去什么」的具体推进；"
                "themes 不少于 **28 汉字**。\n"
            )
        else:
            framework_depth_contract = (
                "【篇幅与细节契约（须严格遵守）】\n"
                "- Markdown 三部分合计建议不少于 **2000 汉字**；「## 一」不少于 **800 汉字**；「## 二」至少 **5 名**核心角色，每人不少于 **150 汉字**；"
                "「## 三」不少于 **550 汉字**。\n"
                "- JSON：characters 至少 **5** 条；traits 每人不少于 **5** 条标签；motivation 每人不少于 **55 汉字**；"
                "world_rules 不少于 **180 汉字**；main_plot 不少于 **320 汉字**，须含至少三段可执行推进（每段含具体冲突或信息反转位）；"
                "themes 不少于 **36 汉字**。\n"
            )

        framework_markdown_structure_contract = (
            "【Markdown 结构要求】\n"
            "- 只输出基础框架，必须包含且仅按以下三个一级章节组织：## 一、世界观与核心设定；## 二、核心人物；## 三、主线剧情与长期矛盾。\n"
            "- 除非用户明确要求改变格式，否则不要改章节标题名、不要改章节顺序、不要把人物或主线拆成额外的同级大节。\n"
        )
        framework_content_contract = (
            "【内容要求】\n"
            "- 世界观：除法则与力量体系外，须点名主要势力/地理或空间结构、资源稀缺性、普通人 vs 超凡者的日常差异。\n"
            "- 人物：禁止只写「高冷/温柔」等抽象词；traits 要能指导对白与行为；说明人物在主线中的功能（推动/阻碍/误导/牺牲等）。\n"
            "- 主线：必须写清「谁想要什么、为何现在拿不到、拿不到会怎样」；并写出可执行故事线：至少点明主要对手或制度性阻力在做什么、"
            "至少两处中盘反转或信息反转的伏笔位、至少两个带代价或时限的压力点；避免只用抽象词概括成长或逆袭。\n"
        )

        if mode == "create":
            sys = (
                "你是资深网文策划与世界观编辑。当前是第一阶段，只生成基础框架：设定、人物、主线，不生成卷级概览，不生成分卷剧情大纲（arcs）。\n"
                "请输出两部分：1) 完整可读 Markdown；2) 末尾单独一个 JSON 代码块，包含 "
                "world_rules, main_plot, characters[{name,role,traits,motivation}], themes 等基础键；"
                "可以补充 forbidden_constraints、key_locations、key_factions 等硬约束或索引键，但严禁输出 arcs、volume_overview、volumes。\n"
                f"{framework_markdown_structure_contract}"
                f"{framework_content_contract}"
                f"{framework_depth_contract}"
                f"{_ANTI_AI_FLAVOR_BLOCK}\n"
                "参考文本仅借鉴结构与文风，禁止抄袭原句。"
            )
            user = (
                f"书名：{novel.title}\n简介：{novel.intro}\n"
                f"背景设定：{novel.background}\n文风关键词：{novel.style}\n"
                f"{ws_block}"
                f"目标章节数：{target_chapters}\n\n"
                "请把简介与背景设定中的信息**展开、细化、落地**到 Markdown 与 JSON 中，而不是复述一遍短句；"
                "若简介与背景互有缺口，可在不违背用户意图的前提下做合理推演补全。\n"
                "本阶段不要写卷级概览，不要写分卷剧情大纲，不要输出 arcs。\n\n"
                f"参考文本节选：\n{ref or '（无）'}"
            )
        elif mode == "regen":
            fj_block = truncate_framework_json(framework_json_base_str(novel), 9000)
            md_block = (novel.framework_markdown or "")[:9000]
            sys = (
                "你是资深网文策划与世界观编辑。当前是第一阶段重构，只重写基础框架：设定、人物、主线。"
                "卷级概览与分卷剧情大纲（arcs）将在第二阶段单独生成。\n"
                "请输出两部分：1) 完整可读 Markdown；2) 末尾单独一个 JSON 代码块，包含 "
                "world_rules, main_plot, characters[{name,role,traits,motivation}], themes 等基础键；"
                "可以补充 forbidden_constraints、key_locations、key_factions 等硬约束，但严禁输出 arcs、volume_overview、volumes。\n"
                f"{framework_markdown_structure_contract}"
                f"{framework_content_contract}"
                f"{framework_depth_contract}"
                f"{_ANTI_AI_FLAVOR_BLOCK}\n"
                "参考文本仅借鉴结构与文风，禁止抄袭原句。"
            )
            user = (
                f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风关键词：{novel.style}\n"
                f"{ws_block}"
                f"目标章节数：{target_chapters}\n\n"
                f"【当前框架 Markdown（截断）】\n{md_block or '（空）'}\n\n"
                f"【当前框架 JSON（截断）】\n{fj_block}\n\n"
                f"【用户修改指令】\n{(instruction or '').strip()}\n\n"
                "请优先保留当前版本里已经合理、可用的部分，在此基础上重写并补强；若用户指令未明确要求换格式，就继续维持三段式基础大纲骨架。\n"
                "本阶段只处理设定/人物/主线，不要输出卷级概览，不要输出 arcs。\n\n"
                f"参考文本节选：\n{ref or '（无）'}"
            )
        else:
            fj_block = truncate_framework_json(framework_json_base_str(novel), 9000)
            md_block = (novel.framework_markdown or "")[:9000]
            chars_text = json.dumps(characters or [], ensure_ascii=False)
            sys = (
                "你是资深网文策划与世界观编辑。当前是第一阶段人物定向修订，只重写基础框架：设定、人物、主线。"
                "卷级概览与分卷剧情大纲（arcs）将在第二阶段基于本结果单独生成。\n"
                "请输出两部分：1) 完整可读 Markdown；2) 末尾单独一个 JSON 代码块，包含 "
                "world_rules, main_plot, characters[{name,role,traits,motivation}], themes 等基础键；"
                "可以补充 forbidden_constraints、key_locations、key_factions 等硬约束，但严禁输出 arcs、volume_overview、volumes。\n"
                "要求：人物列表以用户提供为准；需要时可以补充少量关键配角，但不得删除用户给出的主角。\n"
                f"{framework_depth_contract}"
                f"{_ANTI_AI_FLAVOR_BLOCK}"
            )
            user = (
                f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风：{novel.style}\n"
                f"{ws_block}"
                f"目标章节数：{target_chapters}\n\n"
                f"【当前框架 Markdown（截断）】\n{md_block or '（空）'}\n\n"
                f"【当前框架 JSON（截断）】\n{fj_block}\n\n"
                f"【用户确认后的人物列表（JSON）】\n{chars_text}\n\n"
                "请将人物变更融入基础框架：\n"
                "- 若人物改名，需全局替换并保持一致\n"
                "- traits 要落到动机/行为模式/关系张力上\n"
                "- 本阶段不要输出卷级概览，不要输出 arcs"
            )

        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.55 if mode != "create" else 0.6,
            max_tokens=settings.novel_framework_max_tokens,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _sanitize_base_framework_payload(_parse_framework_json_from_reply(text))
        markdown = _trim_base_framework_markdown(_strip_last_fenced_block(text) or text)
        return markdown or text, parsed

    async def _generate_framework_arcs_stage(
        self,
        novel: Novel,
        *,
        base_markdown: str,
        base_payload: dict[str, Any],
        db: Any = None,
        instruction: str = "",
        characters: list[dict[str, Any]] | None = None,
        target_volume_nos: list[int] | None = None,
        prior_volumes_arcs_context: str = "",
    ) -> tuple[str, dict[str, Any]]:
        router = self._router(db=db)
        ref = load_reference_text_for_llm(
            novel.reference_storage_key,
            novel.id,
            novel.reference_public_url,
        )
        target_chapters, volume_size, volume_n = self._framework_target_meta(novel)
        ws_block = self._framework_style_block_for_novel(novel, db=db)
        base_json_text = json.dumps(base_payload, ensure_ascii=False)
        chars_block = (
            f"\n【最新人物列表（JSON）】\n{json.dumps(characters or [], ensure_ascii=False)}\n"
            if characters is not None
            else ""
        )
        instruction_block = (
            f"\n【需要同步遵守的修改指令】\n{instruction.strip()}\n"
            if instruction.strip()
            else ""
        )

        # 根据是否指定卷号生成不同的 system prompt
        if target_volume_nos:
            vol_nos_str = ",".join(str(v) for v in sorted(target_volume_nos))
            volume_scope_hint = (
                f"当前只需生成第 {vol_nos_str} 卷的 arcs，不要输出其他卷的 arcs。"
                f"总卷数约 {volume_n if volume_n else '请按目标章节数估算'}，"
                f"但本请求只处理指定的卷号。\n"
            )
        else:
            volume_scope_hint = (
                f"- 默认每卷约 {volume_size} 章；总卷数约 {volume_n if volume_n else '请按目标章节数估算'}。\n"
            )

        vol_seg_block = ""
        tc = int(target_chapters) if isinstance(target_chapters, int) and target_chapters > 0 else 0
        if target_volume_nos and tc > 0:
            parts: list[str] = []
            for raw in sorted(target_volume_nos):
                try:
                    vn = int(raw)
                except (TypeError, ValueError):
                    continue
                if vn < 1:
                    continue
                lo = (vn - 1) * volume_size + 1
                hi = min(tc, vn * volume_size)
                if lo > hi:
                    continue
                n_arc = max(1, (hi - lo + 1 + 4) // 5)
                parts.append(
                    f"  · 第{vn}卷为全书第 {lo}—{hi} 章：JSON 的 arcs 中，针对该卷**必须出现恰好 {n_arc} 条** arc，"
                    f"按**每 5 章一条**连续切分（相邻 arc 的章节号衔接、不重不漏，最后一条可到 {hi}）。"
                )
            if parts:
                vol_seg_block = (
                    "【本请求须满足的卷内条数（与下方 JSON 的 arcs 数组一一对应）】\n"
                    + "\n".join(parts)
                    + "\n"
                )

        prior_arcs_sys = ""
        if prior_volumes_arcs_context.strip():
            prior_arcs_sys = (
                "若用户消息中包含「已生成的前序分卷剧情弧线摘要」，你必须将其视为已定剧情走向："
                "新卷 arcs 与卷级概览须自然承接其中人物状态、未收束悬念与冲突升级，不得重置或无视前序已定内容。\n"
            )
        sys = (
            "你是资深网文策划与长篇连载分卷编辑。当前是第二阶段：只负责补完「卷级概览 + 分卷剧情大纲（Arcs）」。\n"
            f"{prior_arcs_sys}"
            "你必须严格沿用既有的世界观、人物、主线，不得重写 world_rules、main_plot、characters、themes，只能在其基础上细化长篇推进节奏。\n"
            "请输出两部分：1) 只包含新增部分的 Markdown 片段，且只写 `## 四、卷级概览` 与 `## 五、分卷剧情大纲 (Arcs)` 两节；"
            "2) 末尾单独一个 JSON 代码块，只包含 volume_overview 与 arcs 两个键，其中 arcs 必填。\n"
            "【卷级概览要求】\n"
            f"{volume_scope_hint}"
            "- 用卷为粒度概括每卷的主目标、核心冲突、阶段成果、卷末钩子。\n"
            "【分卷剧情 arcs 的硬性切分（必须遵守）】\n"
            f"- 以全书连续章号书写 from_chapter、to_chapter；默认每卷约 {volume_size} 章。\n"
            "- **每一卷内**按**每 5 章为一条 arc** 切分：在标准 50 章的卷中必须输出**恰好 10 条** arc，"
            "对应全书章号 1-5、6-10、11-15、16-20、21-25、26-30、31-35、36-40、41-45、46-50"
            f"（若该卷在全书中的章节起点不是 1，则整体平移到该卷的 from–to 范围内，仍保持每 5 章一条）。\n"
            "- 若某卷章数不是 5 的倍数，最后一条 arc 的 to_chapter 可到该卷末，前面仍按每 5 章一条。\n"
            "- **禁止**仅用 1-30、31-50 等两三条粗弧代替整卷的 5 章细弧。\n"
            "- 每个 arc 使用 JSON 整数 from_chapter、to_chapter（勿用字符串）；\n"
            "每条必须包含 **title**（短标题）与 **summary**（必填，**至少约 80 个汉字**），"
            "写清该段内的目标、冲突、转折、人物与伏笔；**禁止**只输出标题不写 summary。\n"
            "每条 arc **还必须**包含以下与执行约束相关的键（都不得为空泛占位）：\n"
            "- **hook**（string）：本段收束时留给下一段的悬念/钩子，1-3 句，可接剧情。\n"
            "- **must_not**（string[]）：**至少 1 条**，写明本段内**禁止**提前推进、揭露或完结的内容（如终局真相、某身份、某势力底牌等）。\n"
            "- **progress_allowed**（string 或 string[]）：**至少 1 项**，写明本段**允许且应当**推进到的阶段/可写事件，与 must_not 不矛盾。\n"
            "- 若仍有余力，可在 arc 内附加 sub_arcs 或 key_events 作补充，**但不得**用子结构代替使 summary、hook、must_not、progress_allowed 留空。\n"
            f"{_ANTI_AI_FLAVOR_BLOCK}\n"
            "参考文本仅借鉴结构与文风，禁止抄袭原句。"
        )
        user = (
            f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风关键词：{novel.style}\n"
            f"{ws_block}"
            f"目标章节数：{target_chapters}\n"
            f"分卷规则：默认每卷 {volume_size} 章；总卷数约：{volume_n if volume_n else '（请按目标章节数自行估算）'}\n"
            f"{vol_seg_block}\n"
            f"【第一阶段基础框架 Markdown】\n{base_markdown or '（空）'}\n\n"
            f"【第一阶段基础框架 JSON】\n{base_json_text}\n"
            f"{instruction_block}"
            f"{chars_block}\n"
            + (
                f"\n【已生成的前序分卷剧情弧线摘要（承接用；勿逐字复述，须与本批新卷内容连贯）】\n"
                f"{prior_volumes_arcs_context.strip()}\n"
                if prior_volumes_arcs_context.strip()
                else ""
            )
            + "请只补全卷级概览与 arcs，不要重复输出前面已经定好的设定/人物/主线全文。\n\n"
            f"参考文本节选：\n{ref or '（无）'}"
        )
        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.55,
            max_tokens=settings.novel_framework_max_tokens,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _parse_framework_json_from_reply(text)
        markdown = _strip_last_fenced_block(text)
        return markdown or text, parsed

    async def generate_framework(
        self,
        novel: Novel,
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """返回 (markdown 正文, 尽力解析的 json 字符串)。"""
        _notify_progress(progress_callback, "第一阶段：生成设定、人物与主线")
        base_markdown, base_payload = await self._generate_framework_base_stage(
            novel,
            mode="create",
            db=db,
        )
        _notify_progress(progress_callback, "第二阶段：生成卷级概览与分卷剧情大纲（Arcs）")
        arcs_markdown, arcs_payload = await self._generate_framework_arcs_stage(
            novel,
            base_markdown=base_markdown,
            base_payload=base_payload,
            db=db,
        )
        final_markdown = _merge_framework_markdown_sections(base_markdown, arcs_markdown)
        final_payload = _merge_framework_payloads(base_payload, arcs_payload)
        return final_markdown, json.dumps(final_payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    #  仅生成基础框架（大纲 + 人物 + 主线，不含 arcs）
    # ------------------------------------------------------------------
    async def generate_base_framework(
        self,
        novel: Novel,
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
        *,
        mode: Literal["create", "regen"] = "create",
        instruction: str = "",
    ) -> tuple[str, str]:
        """只生成基础框架（设定/人物/主线），不含 arcs。返回 (markdown, json_string)。"""
        _notify_progress(progress_callback, "生成设定、人物与主线")
        base_markdown, base_payload = await self._generate_framework_base_stage(
            novel,
            mode=mode,
            db=db,
            instruction=instruction,
        )
        return base_markdown, json.dumps(base_payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    #  为指定卷号生成 arcs（增量）
    # ------------------------------------------------------------------
    async def generate_arcs_for_volumes(
        self,
        novel: Novel,
        *,
        target_volume_nos: list[int] | None = None,
        instruction: str = "",
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """
        为指定卷号生成 arcs 并增量合并到 framework_json。
        返回 (更新后的 markdown, 更新后的 json_string)。
        如果 target_volume_nos 为 None，则生成所有卷的 arcs。
        """
        # 从当前 framework_json 中提取 base 部分
        current_fw = _safe_json_dict(novel.framework_json or "{}")
        base_payload = _sanitize_base_framework_payload(current_fw)
        base_markdown = _trim_base_framework_markdown(novel.framework_markdown or "")

        _notify_progress(progress_callback, f"生成第{','.join(str(v) for v in (target_volume_nos or []))}卷的 Arcs")

        prior_ctx = ""
        if target_volume_nos:
            try:
                min_v = min(int(x) for x in target_volume_nos)
            except (TypeError, ValueError):
                min_v = 1
            if min_v > 1:
                _, vs, _ = self._framework_target_meta(novel)
                prior_ctx = _build_prior_volumes_arcs_context_block(
                    current_fw,
                    min_target_volume_no=min_v,
                    volume_size=vs,
                )

        arcs_markdown, arcs_payload = await self._generate_framework_arcs_stage(
            novel,
            base_markdown=base_markdown,
            base_payload=base_payload,
            db=db,
            instruction=instruction,
            target_volume_nos=target_volume_nos,
            prior_volumes_arcs_context=prior_ctx,
        )

        # 增量合并：只替换/追加指定卷的 arcs
        final_payload = _merge_arcs_into_framework(current_fw, arcs_payload, target_volume_nos)
        final_markdown = _merge_framework_markdown_sections(base_markdown, arcs_markdown)
        return final_markdown, json.dumps(final_payload, ensure_ascii=False)

    async def regenerate_framework(
        self,
        novel: Novel,
        instruction: str,
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """仅重写基础大纲；分卷 Arcs 在卷表单独生成/维护。"""
        return await self.generate_base_framework(
            novel,
            db=db,
            progress_callback=progress_callback,
            mode="regen",
            instruction=instruction,
        )

    async def update_framework_characters(
        self,
        novel: Novel,
        characters: list[dict[str, Any]],
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """仅更新基础框架中的人物与相关设定；卷级 Arcs 不受影响。"""
        _notify_progress(progress_callback, "按新人物设定重写基础框架")
        base_markdown, base_payload = await self._generate_framework_base_stage(
            novel,
            mode="characters",
            db=db,
            characters=characters,
        )
        return base_markdown, json.dumps(base_payload, ensure_ascii=False)

    async def generate_volume_chapter_plan_batch_json(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """
        生成“指定章节区间”的一批章计划，并返回严格 JSON 字符串。

        设计目的：
        - 前端/用户手动点击推进，每次只跑一批，成功即落库，避免整卷循环导致超时白跑。
        - 通过 prev_batch_context 传递上一批末两章关键信息，保证连续性。
        - cross_volume_tail_context：新开卷首批时由调用方注入上一卷末计划/正文摘录。
        """
        batch_label = f"卷{volume_no} 批次 {from_chapter}-{to_chapter}"
        batch_json_str = await self._generate_single_batch_plan(
            novel=novel,
            volume_no=volume_no,
            volume_title=volume_title,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            memory_json=memory_json,
            prev_batch_context=prev_batch_context,
            cross_volume_tail_context=cross_volume_tail_context,
            db=db,
        )
        batch_data = self._parse_volume_plan_llm_json(batch_json_str, batch_label=batch_label)
        raw_chapters = batch_data.get("chapters", [])
        if not isinstance(raw_chapters, list):
            raw_chapters = []
        chapters = self._normalize_volume_plan_batch_chapters(
            raw_chapters,
            batch_start=from_chapter,
            batch_end=to_chapter,
            batch_label=batch_label,
        )
        result = {
            "volume_title": volume_title,
            "volume_summary": f"第{volume_no}卷，批次第{from_chapter}-{to_chapter}章",
            "chapters": chapters,
        }
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _volume_plan_chapter_sort_key(ch: dict) -> int:
        cn = ch.get("chapter_no")
        if isinstance(cn, int):
            return cn
        if isinstance(cn, str) and cn.strip().lstrip("-").isdigit():
            try:
                return int(cn.strip())
            except ValueError:
                pass
        return 1 << 30

    def _sort_volume_plan_chapters(self, chapters: list[Any]) -> list[dict]:
        return sorted(
            (c for c in chapters if isinstance(c, dict)),
            key=self._volume_plan_chapter_sort_key,
        )

    def _parse_volume_plan_llm_json(self, batch_json_str: str, *, batch_label: str) -> dict:
        try:
            return _volume_plan_parse_llm_json_to_dict(batch_json_str)
        except json.JSONDecodeError as e:
            snippet = (batch_json_str or "")[:1200]
            logger.warning(
                "%s 卷章计划 JSON 解析失败 | err=%s pos=%s snippet_head=%r",
                batch_label,
                e,
                getattr(e, "pos", None),
                snippet[:500],
            )
            raise RuntimeError(f"{batch_label} 返回非法 JSON：{e}") from e

    def _normalize_volume_plan_batch_chapters(
        self,
        chapters: list[Any],
        *,
        batch_start: int,
        batch_end: int,
        batch_label: str,
    ) -> list[dict]:
        expected = batch_end - batch_start + 1
        sorted_ch = self._sort_volume_plan_chapters(chapters)
        if len(sorted_ch) > expected:
            logger.warning(
                "%s 章条目数为 %d，多于本批 %d 条，已截断（第 %d-%d 章）",
                batch_label,
                len(sorted_ch),
                expected,
                batch_start,
                batch_end,
            )
            sorted_ch = sorted_ch[:expected]
        elif len(sorted_ch) < expected:
            logger.warning(
                "%s 章条目数为 %d，少于本批 %d 条，仍按已生成条目落库（第 %d-%d 章）",
                batch_label,
                len(sorted_ch),
                expected,
                batch_start,
                batch_end,
            )
        for i, ch in enumerate(sorted_ch):
            ch["chapter_no"] = batch_start + i
            beats = ch.get("beats")
            ch["beats"] = normalize_beats_to_v2(beats if isinstance(beats, dict) else {})
        return sorted_ch

    def _validate_merged_volume_plan_chapters(
        self,
        chapters: list[dict],
        *,
        from_chapter: int,
        to_chapter: int,
        volume_no: int,
    ) -> None:
        total = to_chapter - from_chapter + 1
        if len(chapters) != total:
            logger.warning(
                "第 %s 卷章计划合并后共 %d 条，期望 %d 条（第 %d-%d 章），条数不足时仍返回已生成部分",
                volume_no,
                len(chapters),
                total,
                from_chapter,
                to_chapter,
            )
        if len(chapters) != total:
            return
        for i, ch in enumerate(chapters):
            expect_no = from_chapter + i
            cn = ch.get("chapter_no")
            if cn != expect_no:
                raise RuntimeError(
                    f"第 {volume_no} 卷章计划 chapter_no 不连续："
                    f"第 {i + 1} 条期望 {expect_no}，实际 {cn!r}"
                )

    async def generate_volume_chapter_plan_json(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        db: Any = None,
    ) -> str:
        """
        生成整卷章计划（严格 JSON 文本）。该 JSON 会由路由解析并落库。
        采用分批生成策略，避免单次请求超时，同时保证批次间剧情连续性。
        """
        batch_size = max(1, settings.novel_volume_plan_batch_size)
        total_chapters = to_chapter - from_chapter + 1

        # 如果章节数不超过批次大小，直接单次生成
        if total_chapters <= batch_size:
            batch_json_str = await self._generate_single_batch_plan(
                novel=novel,
                volume_no=volume_no,
                volume_title=volume_title,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                memory_json=memory_json,
                prev_batch_context="",
                cross_volume_tail_context="",
                db=db,
            )
            batch_data = self._parse_volume_plan_llm_json(
                batch_json_str, batch_label="整卷章计划"
            )
            raw_chapters = batch_data.get("chapters", [])
            if not isinstance(raw_chapters, list):
                raw_chapters = []
            chapters = self._normalize_volume_plan_batch_chapters(
                raw_chapters,
                batch_start=from_chapter,
                batch_end=to_chapter,
                batch_label="整卷章计划",
            )
            self._validate_merged_volume_plan_chapters(
                chapters,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                volume_no=volume_no,
            )
            result = {
                "volume_title": volume_title,
                "volume_summary": f"第{volume_no}卷，共{len(chapters)}章",
                "chapters": chapters,
            }
            return json.dumps(result, ensure_ascii=False)

        # 分批生成
        all_chapters: list[dict] = []
        prev_batch_context = ""
        batch_num = 0

        for batch_start in range(from_chapter, to_chapter + 1, batch_size):
            batch_end = min(batch_start + batch_size - 1, to_chapter)
            batch_num += 1
            logger.info(
                "generate_volume_chapter_plan batch %d | chapters %d-%d | total %d",
                batch_num,
                batch_start,
                batch_end,
                total_chapters,
            )

            batch_json_str = await self._generate_single_batch_plan(
                novel=novel,
                volume_no=volume_no,
                volume_title=volume_title,
                from_chapter=batch_start,
                to_chapter=batch_end,
                memory_json=memory_json,
                prev_batch_context=prev_batch_context,
                cross_volume_tail_context="",
                db=db,
            )

            batch_data = self._parse_volume_plan_llm_json(
                batch_json_str, batch_label=f"批次 {batch_num}"
            )
            raw_chapters = batch_data.get("chapters", [])
            if not isinstance(raw_chapters, list):
                raw_chapters = []

            chapters = self._normalize_volume_plan_batch_chapters(
                raw_chapters,
                batch_start=batch_start,
                batch_end=batch_end,
                batch_label=f"批次 {batch_num}",
            )
            all_chapters.extend(chapters)

            # 构建下一批次的上下文（最后2章的关键信息）
            prev_batch_context = self._build_next_batch_context(
                chapters=chapters,
                volume_title=volume_title,
            )

        merged = self._sort_volume_plan_chapters(all_chapters)
        self._validate_merged_volume_plan_chapters(
            merged,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            volume_no=volume_no,
        )

        # 合并结果
        result = {
            "volume_title": volume_title,
            "volume_summary": f"第{volume_no}卷，共{len(merged)}章",
            "chapters": merged,
        }
        return json.dumps(result, ensure_ascii=False)

    async def _generate_single_batch_plan(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """生成单批次章计划"""
        router = self._router(db=db)
        batch_chapter_count = to_chapter - from_chapter + 1

        # 根据篇幅获取对应的防重复约束
        anti_repetition_block = self._get_anti_repetition_constraints(novel, batch_chapter_count)

        sys = (
            "你是网络小说总策划。请为指定章节区间生成「章计划」，用于后续逐章写作。"
            "你必须严格输出一个 JSON 对象，不要输出任何解释性文字、不要 Markdown、不要代码块围栏。"
            "输出必须以 { 开头，以 } 结尾；除 JSON 外不得包含任何字符。"
            "【JSON 语法硬要求】所有字符串值内禁止直接换行；若需分段请使用 \\n 转义。"
            "剧情文本中避免使用未转义的英文双引号；可用中文「」或单引号代替。"
            "【核心原则】剧情必须递进，禁止原地踏步式的重复！每一章都必须推动故事前进，不得重复已有的冲突模式。\n"
            f"{_ANTI_AI_FLAVOR_BLOCK}"
        )

        cross_volume_hint = ""
        if cross_volume_tail_context.strip():
            cross_volume_hint = (
                "\n\n【跨卷衔接：上一卷末（须承接，与下列事实无矛盾）】\n"
                f"{cross_volume_tail_context.strip()}\n"
                "要求：本批为当前卷起始章计划，须在人物状态、悬念与未结冲突上自然接续上一卷末；"
                "不得重置剧情线或无视上文已发生的事实；volume_summary 须点出与上一卷的承接关系。\n"
            )

        # 构建前文上下文提示
        continuity_hint = ""
        if prev_batch_context:
            continuity_hint = (
                "\n\n【前批次剧情衔接（必须承接）】\n"
                f"{prev_batch_context}\n"
                "要求：本章计划必须自然承接前批次的剧情走向、人物状态和未完结线索；"
                "open_plots_intent_added 若在前批次已出现，本章不得重复声明（除非是新的分支）。\n"
            )

        user = (
            f"【小说标题】{novel.title}\n"
            f"【卷信息】第{volume_no}卷《{volume_title}》，本批次章节范围：第{from_chapter}章-第{to_chapter}章\n\n"
            f"【框架 Markdown（摘要）】\n{(novel.framework_markdown or novel.background or '')[:8000]}\n\n"
            f"【框架 JSON】\n{novel.framework_json or '{}'}\n\n"
            f"【结构化记忆（open_plots/canonical_timeline 等）】\n{memory_json}\n"
            f"{cross_volume_hint}"
            f"{continuity_hint}"
            "【输出要求（严格 JSON）】\n"
            "{\n"
            '  \"volume_title\": string,\n'
            '  \"volume_summary\": string,\n'
            '  \"chapters\": [\n'
            "    {\n"
            '      \"chapter_no\": number,\n'
            '      \"title\": string,\n'
            '      \"beats\": {\n'
            '        \"goal\": string,\n'
            '        \"conflict\": string,\n'
            '        \"turn\": string,\n'
            '        \"hook\": string,\n'
            '        \"plot_summary\": string,\n'
            '        \"stage_position\": string,\n'
            '        \"pacing_justification\": string,\n'
            '        \"expressive_brief\": {\n'
            '          \"pov_strategy\": string,\n'
            '          \"emotional_curve\": string,\n'
            '          \"sensory_focus\": string,\n'
            '          \"dialogue_strategy\": string,\n'
            '          \"scene_tempo\": string,\n'
            '          \"reveal_strategy\": string\n'
            '        },\n'
            '        \"progress_allowed\": string 或 string[],\n'
            '        \"must_not\": string[],\n'
            '        \"reserved_for_later\": [ { \"item\": string, \"not_before_chapter\": number } ],\n'
            '        \"scene_cards\": [\n'
            '          {\n'
            '            \"label\": string,\n'
            '            \"goal\": string,\n'
            '            \"conflict\": string,\n'
            '            \"content\": string,\n'
            '            \"outcome\": string,\n'
            '            \"emotion_beat\": string,\n'
            '            \"camera\": string,\n'
            '            \"dialogue_density\": string,\n'
            '            \"words\": number\n'
            '          }\n'
            '        ]\n'
            "      },\n"
            '      \"open_plots_intent_added\": string[],\n'
            '      \"open_plots_intent_resolved\": string[]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "volume_summary：用 200～500 字写清本卷在本作中的位置、本卷核心矛盾、阶段目标、与前后卷的衔接、读者在本卷应获得的情绪曲线；"
            "避免空泛一句话，需分层（人物线/主线/副线/悬念）各至少一句。\n"
            "beats 字段说明：plot_summary 为本章剧情梗概（约 5～12 句，须写清场景转换、关键行动、信息边界、章末停笔点）；"
            "stage_position 用一两句说明本章在「当前大纲弧/本卷」中的位置（例如「第一弧约 15% 处、仅完成铺垫」）；"
            "pacing_justification 用一两句说明本章为何**不会**提前触发后续弧或更大阶段的核心事件（避免与 must_not 矛盾）；"
            "expressive_brief 必填，负责规定本章怎么写而不是写什么：至少写清 POV 站位、情绪推进、感官焦点、对白策略、场景节奏、信息揭示方式；"
            "progress_allowed 写明本章允许推进的内容；must_not 列出本章绝对不得出现的情节、能力觉醒、设定点名、剧透；"
            "reserved_for_later 列出须延后到指定章节号及之后才允许在正文成真或点名的条目（not_before_chapter 为全局章节号）；"
            "scene_cards 必填，按顺序拆成 2-4 个场景，每个场景除剧情内容外还要包含 emotion_beat / camera / dialogue_density，确保后续写作有表现抓手。\n\n"
            "【硬约束】\n"
            f"1) chapters 数组必须恰好包含 {batch_chapter_count} 个对象（第 {from_chapter}～{to_chapter} 章，缺一不可、也不可合并）；"
            f"chapter_no 从 {from_chapter} 起连续递增；输出前自检 JSON 中 chapters.length === {batch_chapter_count}；\n"
            "2) 每章 beats 必须体现「只推进一个小节拍」（不要一章跨多个大事件）；\n"
            "3) 每章 open_plots_intent_resolved 最多 1 条（可以为空），避免清坑过猛导致快进；\n"
            "4) 若本批次非卷末，章末应自然过渡到下一章，但不得提前解决后续大事件；\n"
            "5) 必须通读【框架 JSON】中的 arcs、人物、金手指/能力、主线节点；若大纲写明某能力/身份/真相「第 N 章」才觉醒或揭露，"
            "则所有 chapter_no < N 的章，beats.must_not 必须包含对应的禁止描述（如不得觉醒、不得点名该能力真名、不得让配角知晓等），"
            "且 plot_summary/turn/hook 不得写到该事件的结果；\n"
            "6) 每章 plot_summary 仅允许写本章内发生的事，不得写到后续章的结局或后验信息；\n"
            "7) 输出前自检：若某章 plot_summary、turn 或 hook 与该章 must_not、或 reserved_for_later 中 not_before_chapter 大于该章 chapter_no 的条目冲突，必须改写该章直至一致；\n"
            "8) reserved_for_later 可为空数组；若框架无明确章节锚点，按 arcs 节拍合理分配 not_before_chapter，且与 must_not 一致；\n"
            "9) 每章必须填写 stage_position 与 pacing_justification，且与 plot_summary、must_not 一致；\n"
            "10) 若本批次章节落在框架 JSON 中某一弧的章节范围内，不得让本批次计划实质跨入下一弧的核心事件；\n"
            + (
                "11) 本批次若包含**全书第1章**（存在 chapter_no=1）：该章必须是「可入场的第1章」——"
                "plot_summary 须写清如何通过场景/对白/观察呈现：基本时空或环境、主角身份与当前处境、主线矛盾或故事契机的来由，"
                "使读者不依赖脑补即可理解谁、何处、因何进入当前局面；"
                "goal 与 conflict 须与上述交代自然衔接，不得写成无情境骨架的事件清单；"
                "must_not 须明确禁止缺乏铺垫的「莫名其妙」开场（例如未解释的多方混战、大段生造专名砸脸、读者尚不知人物关系就写终局式结果等）。\n"
                if from_chapter <= 1 <= to_chapter
                else ""
            )
            + f"{anti_repetition_block}"
        )
        return await router.chat_text(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.55,
            web_search=self._novel_web_search(db, flow="volume_plan"),
            timeout=settings.novel_volume_plan_batch_timeout,
            max_tokens=8192,
            **self._bill_kw(db, self._billing_user_id),
        )

    @staticmethod
    def _get_anti_repetition_constraints(novel: Novel, batch_chapter_count: int) -> str:
        """根据小说篇幅返回对应的防重复约束提示词

        篇幅定义：
        - 短篇：≤50章 - 节奏紧凑，每章必须推进
        - 中篇：51-200章 - 适度推进，允许过渡和蓄势
        - 长篇：>200章 - 张弛有度，允许支线、人物发展、休整章节
        """
        target = getattr(novel, "target_chapters", 0) or 0

        # 短篇：严格紧凑
        if target <= 50:
            return """【短篇节奏约束 - 严格推进】
11) 短篇节奏必须紧凑：每章必须有实质性推进，不允许「纯过渡/纯对话/纯描述」章节；
12) 禁止重复使用相同的心理活动模式：如「心里乱成一团」、「感到深深的疲惫」等固定句式；
13) 禁止重复的环境描写开场：同一卷内各章的场景氛围必须有所变化；
14) 每章 conflict 必须与前3章有本质区别或递进，不得「换汤不换药」；
15) 人物情绪必须递进：不得在同一情绪层级反复横跳，必须朝向解决或恶化方向演进。
"""

        # 长篇：张弛有度
        if target > 200:
            return """【长篇节奏约束 - 张弛有度】
11) 长篇允许节奏变化：章节可分为「推进章」「蓄势章」「过渡章」「人物章」「支线章」等不同类型，不必每章都推进主线；
12) 避免固定套路化描写即可，但不要求每章都完全不同：相似的心理状态可在不同情境下出现，但需有合理差异；
13) 环境描写可适当重复（如同一地点的多次到访），但需体现时间、氛围、人物心境的变化；
14) conflict 可有层次地展开：允许在同一冲突主题下分多章逐步升级，不必每章都是新冲突；
15) 人物情绪发展允许反复和挣扎：真实的人物塑造允许情绪回退、自我怀疑、短暂动摇，不必单向递进；
16) 多线叙事鼓励：允许并鼓励支线发展、配角视角、背景铺陈，这些「非主线推进」内容对长篇质量至关重要。
"""

        # 中篇：平衡策略（默认）
        return """【中篇节奏约束 - 平衡推进】
11) 中篇需保持适度推进：每1-2章应有可见的进展，允许必要的过渡和蓄势章节；
12) 避免固定套路化描写：不重复使用完全相同的心理/环境描写句式；
13) 同一卷内场景氛围需有变化：但允许相关章节的场景延续；
14) conflict 需有递进或变化：同一主题可分章展开，但需体现层次升级；
15) 人物情绪应总体递进：允许短暂波动，但总体趋势应朝向发展或变化。
"""

    def _generate_single_batch_plan_sync(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """生成单批次章计划（同步，供 Celery worker 使用）。"""
        router = self._router(db=db)
        batch_chapter_count = to_chapter - from_chapter + 1

        # 根据篇幅获取对应的防重复约束
        anti_repetition_block = self._get_anti_repetition_constraints(novel, batch_chapter_count)

        sys = (
            "你是网络小说总策划。请为指定章节区间生成「章计划」，用于后续逐章写作。"
            "你必须严格输出一个 JSON 对象，不要输出任何解释性文字、不要 Markdown、不要代码块围栏。"
            "输出必须以 { 开头，以 } 结尾；除 JSON 外不得包含任何字符。"
            "【JSON 语法硬要求】所有字符串值内禁止直接换行；若需分段请使用 \\n 转义。"
            "剧情文本中避免使用未转义的英文双引号；可用中文「」或单引号代替。"
            "【核心原则】剧情必须递进，禁止原地踏步式的重复！每一章都必须推动故事前进，不得重复已有的冲突模式。\n"
            f"{_ANTI_AI_FLAVOR_BLOCK}"
        )
        cross_volume_hint = ""
        if cross_volume_tail_context.strip():
            cross_volume_hint = (
                "\n\n【跨卷衔接：上一卷末（须承接，与下列事实无矛盾）】\n"
                f"{cross_volume_tail_context.strip()}\n"
                "要求：本批为当前卷起始章计划，须在人物状态、悬念与未结冲突上自然接续上一卷末；"
                "不得重置剧情线或无视上文已发生的事实；volume_summary 须点出与上一卷的承接关系。\n"
            )
        continuity_hint = ""
        if prev_batch_context:
            continuity_hint = (
                "\n\n【前批次剧情衔接（必须承接）】\n"
                f"{prev_batch_context}\n"
                "要求：本章计划必须自然承接前批次的剧情走向、人物状态和未完结线索；"
                "open_plots_intent_added 若在前批次已出现，本章不得重复声明（除非是新的分支）。\n"
            )
        user = (
            f"【小说标题】{novel.title}\n"
            f"【卷信息】第{volume_no}卷《{volume_title}》，本批次章节范围：第{from_chapter}章-第{to_chapter}章\n\n"
            f"【框架 Markdown（摘要）】\n{(novel.framework_markdown or novel.background or '')[:8000]}\n\n"
            f"【框架 JSON】\n{novel.framework_json or '{}'}\n\n"
            f"【结构化记忆（open_plots/canonical_timeline 等）】\n{memory_json}\n"
            f"{cross_volume_hint}"
            f"{continuity_hint}"
            "【输出要求（严格 JSON）】\n"
            "{\n"
            '  \"volume_title\": string,\n'
            '  \"volume_summary\": string,\n'
            '  \"chapters\": [\n'
            "    {\n"
            '      \"chapter_no\": number,\n'
            '      \"title\": string,\n'
            '      \"beats\": {\n'
            '        \"goal\": string,\n'
            '        \"conflict\": string,\n'
            '        \"turn\": string,\n'
            '        \"hook\": string,\n'
            '        \"plot_summary\": string,\n'
            '        \"stage_position\": string,\n'
            '        \"pacing_justification\": string,\n'
            '        \"expressive_brief\": {\n'
            '          \"pov_strategy\": string,\n'
            '          \"emotional_curve\": string,\n'
            '          \"sensory_focus\": string,\n'
            '          \"dialogue_strategy\": string,\n'
            '          \"scene_tempo\": string,\n'
            '          \"reveal_strategy\": string\n'
            '        },\n'
            '        \"progress_allowed\": string 或 string[],\n'
            '        \"must_not\": string[],\n'
            '        \"reserved_for_later\": [ { \"item\": string, \"not_before_chapter\": number } ],\n'
            '        \"scene_cards\": [\n'
            '          {\n'
            '            \"label\": string,\n'
            '            \"goal\": string,\n'
            '            \"conflict\": string,\n'
            '            \"content\": string,\n'
            '            \"outcome\": string,\n'
            '            \"emotion_beat\": string,\n'
            '            \"camera\": string,\n'
            '            \"dialogue_density\": string,\n'
            '            \"words\": number\n'
            '          }\n'
            '        ]\n'
            "      },\n"
            '      \"open_plots_intent_added\": string[],\n'
            '      \"open_plots_intent_resolved\": string[]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "volume_summary：用 200～500 字写清本卷在本作中的位置、本卷核心矛盾、阶段目标、与前后卷的衔接、读者在本卷应获得的情绪曲线；"
            "避免空泛一句话，需分层（人物线/主线/副线/悬念）各至少一句。\n"
            "beats 字段说明：plot_summary 为本章剧情梗概（约 5～12 句，须写清场景转换、关键行动、信息边界、章末停笔点）；"
            "stage_position 用一两句说明本章在「当前大纲弧/本卷」中的位置（例如「第一弧约 15% 处、仅完成铺垫」）；"
            "pacing_justification 用一两句说明本章为何**不会**提前触发后续弧或更大阶段的核心事件（避免与 must_not 矛盾）；"
            "progress_allowed 写明本章允许推进的内容；must_not 列出本章绝对不得出现的情节、能力觉醒、设定点名、剧透；"
            "reserved_for_later 列出须延后到指定章节号及之后才允许在正文成真或点名的条目（not_before_chapter 为全局章节号）。\n\n"
            "【硬约束】\n"
            f"1) chapters 数组必须恰好包含 {batch_chapter_count} 个对象（第 {from_chapter}～{to_chapter} 章，缺一不可、也不可合并）；"
            f"chapter_no 从 {from_chapter} 起连续递增；输出前自检 JSON 中 chapters.length === {batch_chapter_count}；\n"
            "2) 每章 beats 必须体现「只推进一个小节拍」（不要一章跨多个大事件）；\n"
            "3) 每章 open_plots_intent_resolved 最多 1 条（可以为空），避免清坑过猛导致快进；\n"
            "4) 若本批次非卷末，章末应自然过渡到下一章，但不得提前解决后续大事件；\n"
            "5) 必须通读【框架 JSON】中的 arcs、人物、金手指/能力、主线节点；若大纲写明某能力/身份/真相「第 N 章」才觉醒或揭露，"
            "则所有 chapter_no < N 的章，beats.must_not 必须包含对应的禁止描述（如不得觉醒、不得点名该能力真名、不得让配角知晓等），"
            "且 plot_summary/turn/hook 不得写到该事件的结果；\n"
            "6) 每章 plot_summary 仅允许写本章内发生的事，不得写到后续章的结局或后验信息；\n"
            "7) 输出前自检：若某章 plot_summary、turn 或 hook 与该章 must_not、或 reserved_for_later 中 not_before_chapter 大于该章 chapter_no 的条目冲突，必须改写该章直至一致；\n"
            "8) reserved_for_later 可为空数组；若框架无明确章节锚点，按 arcs 节拍合理分配 not_before_chapter，且与 must_not 一致；\n"
            "9) 每章必须填写 stage_position 与 pacing_justification，且与 plot_summary、must_not 一致；\n"
            "10) 若本批次章节落在框架 JSON 中某一弧的章节范围内，不得让本批次计划实质跨入下一弧的核心事件；\n"
            + (
                "【全书第1章（仅当本批次含第1章时适用）】\n"
                "若 chapters 含 chapter_no=1：该章须为「可入场」第1章——plot_summary/goal/conflict 须体现基本时空或环境、主角身份与处境、故事契机的来由；"
                "must_not 须明确禁止缺乏铺垫的莫名其妙开场（未解释的多方混战、大段生造专名、人物关系未明就写终局式结果等）。\n"
                if from_chapter <= 1 <= to_chapter
                else ""
            )
            + (
                "【防剧情重复硬约束 - 必须遵守】\n"
                "11) 自检：若前批次已出现「质疑-举证-被否定」的冲突循环，本批次不得再使用相同模式，必须让剧情进入新阶段（如：误会加深导致关系破裂、发现新证据、引入新人物、冲突升级等）；\n"
                "12) 禁止重复使用相同的心理活动描写模式：如「心里乱成一团」、「感到深深的疲惫」、「嘴角挂着冷笑」等固定句式，同一卷内不得在不同章重复出现；\n"
                "13) 禁止重复的环境描写开场：如「月光惨白」、「村里的狗吠」、「红木桌子」等，同一卷内各章的场景氛围必须有所变化（时间、天气、环境、氛围）；\n"
                "14) 每章的 conflict 必须与前3章的冲突有本质区别或递进，不得只是换汤不换药的重复争吵；自检：如果本章 conflict 只是前章的「再来一次」，必须重新设计；\n"
                "15) 人物情绪必须递进：如二舅对男主的态度应从信任→怀疑→动摇→愤怒→决裂逐步演变，不得在同一情绪层级反复横跳。\n"
            )
        )
        return router.chat_text_sync(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.55,
            web_search=self._novel_web_search(db, flow="volume_plan"),
            timeout=settings.novel_volume_plan_batch_timeout,
            max_tokens=8192,
            **self._bill_kw(db, self._billing_user_id),
        )

    def generate_volume_chapter_plan_batch_json_sync(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """同步版：生成指定区间的一批章计划 JSON 字符串（供 Celery）。"""
        batch_label = f"卷{volume_no} 批次 {from_chapter}-{to_chapter}"
        batch_json_str = self._generate_single_batch_plan_sync(
            novel=novel,
            volume_no=volume_no,
            volume_title=volume_title,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            memory_json=memory_json,
            prev_batch_context=prev_batch_context,
            cross_volume_tail_context=cross_volume_tail_context,
            db=db,
        )
        batch_data = self._parse_volume_plan_llm_json(batch_json_str, batch_label=batch_label)
        raw_chapters = batch_data.get("chapters", [])
        if not isinstance(raw_chapters, list):
            raw_chapters = []
        chapters = self._normalize_volume_plan_batch_chapters(
            raw_chapters,
            batch_start=from_chapter,
            batch_end=to_chapter,
            batch_label=batch_label,
        )
        result = {
            "volume_title": volume_title,
            "volume_summary": f"第{volume_no}卷，批次第{from_chapter}-{to_chapter}章",
            "chapters": chapters,
        }
        return json.dumps(result, ensure_ascii=False)

    async def regenerate_single_chapter_plan(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        chapter_no: int,
        memory_json: str,
        prev_chapters: list[dict] = None,
        next_chapters: list[dict] = None,
        user_instruction: str = "",
        db: Any = None,
    ) -> dict:
        """重生成单章计划，支持前后文参考和自定义指令"""
        router = self._router(db=db)
        sys = (
            "你是网络小说高级编剧。你的任务是根据用户指令修订或重生成指定章节的「章计划」。"
            "你必须严格输出一个 JSON 对象，不要输出任何解释性文字。"
            "【JSON 语法要求】字符串值内禁止直接换行；剧情文本避免未转义双引号。\n"
            f"{_ANTI_AI_FLAVOR_BLOCK}"
        )

        # 构建参考上下文
        ref_context = ""
        if prev_chapters:
            ref_context += "\n【前文计划参考（必须承接）】\n"
            for c in prev_chapters:
                ref_context += f"第{c.get('chapter_no')}章《{c.get('title')}》: {c.get('beats', {}).get('plot_summary', '')[:300]}\n"
        
        if next_chapters:
            ref_context += "\n【后文计划参考（需保证因果逻辑不冲突）】\n"
            for c in next_chapters:
                ref_context += f"第{c.get('chapter_no')}章《{c.get('title')}》: {c.get('beats', {}).get('plot_summary', '')[:300]}\n"

        user = (
            f"【小说标题】{novel.title}\n"
            f"【本章位置】第{volume_no}卷《{volume_title}》，第{chapter_no}章\n\n"
            f"【用户修订指令】\n{user_instruction or '请根据大纲和前后文重新优化本章计划，增强戏剧冲突。'}\n\n"
            f"【框架摘要】\n{(novel.framework_markdown or novel.background or '')[:5000]}\n\n"
            f"{ref_context}\n"
            "【输出格式（严格 JSON）】\n"
            "{\n"
            '  "chapter_no": number,\n'
            '  "title": string,\n'
            '  "beats": {\n'
            '    "goal": string,\n'
            '    "conflict": string,\n'
            '    "turn": string,\n'
            '    "hook": string,\n'
            '    "plot_summary": string,\n'
            '    "stage_position": string,\n'
            '    "pacing_justification": string,\n'
            '    "expressive_brief": {\n'
            '      "pov_strategy": string,\n'
            '      "emotional_curve": string,\n'
            '      "sensory_focus": string,\n'
            '      "dialogue_strategy": string,\n'
            '      "scene_tempo": string,\n'
            '      "reveal_strategy": string\n'
            '    },\n'
            '    "progress_allowed": string[],\n'
            '    "must_not": string[],\n'
            '    "reserved_for_later": [ { "item": string, "not_before_chapter": number } ],\n'
            '    "scene_cards": [\n'
            '      {\n'
            '        "label": string,\n'
            '        "goal": string,\n'
            '        "conflict": string,\n'
            '        "content": string,\n'
            '        "outcome": string,\n'
            '        "emotion_beat": string,\n'
            '        "camera": string,\n'
            '        "dialogue_density": string,\n'
            '        "words": number\n'
            '      }\n'
            '    ]\n'
            '  },\n'
            '  "open_plots_intent_added": string[],\n'
            '  "open_plots_intent_resolved": string[]\n'
            "}\n"
        )

        resp = await router.chat_text(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.6,
            timeout=120.0,
            max_tokens=3000,
            **self._bill_kw(db, self._billing_user_id),
        )
        
        # 解析 JSON
        try:
            data = _volume_plan_parse_llm_json_to_dict(resp)
            # 兼容处理：如果是包装在 {"chapters": [...]} 里的单项
            if "chapters" in data and isinstance(data["chapters"], list) and len(data["chapters"]) > 0:
                data = data["chapters"][0]
            data["chapter_no"] = chapter_no # 强制修正
            data["beats"] = normalize_beats_to_v2(data.get("beats") or {})
            return data
        except Exception as e:
            logger.error("regenerate_single_chapter_plan parse failed: %s | resp=%r", e, resp[:500])
            raise RuntimeError(f"单章计划解析失败：{e}")

    def _build_next_batch_context(
        self,
        chapters: list[dict],
        volume_title: str,
    ) -> str:
        """构建下一批次的衔接上下文"""
        if not chapters:
            return ""

        ordered = self._sort_volume_plan_chapters(chapters)

        # 取排序后最后 2 章（或更少）的关键信息
        tail_chapters = ordered[-2:] if len(ordered) >= 2 else ordered

        context_parts = []
        for ch in tail_chapters:
            if not isinstance(ch, dict):
                continue
            ch_no = ch.get("chapter_no", "?")
            title = ch.get("title", "")
            beats = normalize_beats_to_v2(ch.get("beats", {}))
            plot_summary = chapter_plan_plot_summary(beats)
            hook = chapter_plan_hook(beats)

            # 收集新增和解决的 open_plots
            added = ch.get("open_plots_intent_added", [])
            resolved = ch.get("open_plots_intent_resolved", [])

            context_parts.append(
                f"第{ch_no}章《{title}》:\n"
                f"  剧情梗概: {plot_summary[:500] if plot_summary else '（无）'}\n"
                f"  章末钩子: {hook[:200] if hook else '（无）'}\n"
                f"  新增线索: {json.dumps(added, ensure_ascii=False) if added else '[]'}\n"
                f"  解决线索: {json.dumps(resolved, ensure_ascii=False) if resolved else '[]'}\n"
            )

        # 汇总当前活跃的 open_plots（按章节号顺序折叠，避免模型乱序导致错判）
        active_plots = set()
        for ch in ordered:
            for p in ch.get("open_plots_intent_added", []):
                if isinstance(p, str) and p.strip():
                    active_plots.add(p.strip())
            for p in ch.get("open_plots_intent_resolved", []):
                if isinstance(p, str) and p.strip():
                    active_plots.discard(p.strip())

        summary = "\n".join(context_parts)
        if active_plots:
            summary += f"\n当前批次遗留的活跃线索（后续需承接或解决）:\n{json.dumps(list(active_plots), ensure_ascii=False)}\n"

        return summary

    async def generate_chapter(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        recent_full_context: str = "",
        chapter_plan_hint: str = "",
        db: Any = None,
        *,
        use_cold_recall: bool = False,
        cold_recall_items: int = 5,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> str:
        router = self._router(provider=llm_provider, model=llm_model, db=db)
        messages = _chapter_messages(
            novel,
            chapter_no,
            chapter_title_hint,
            memory_json,
            continuity_excerpt,
            recent_full_context,
            chapter_plan_hint,
            db=db,
            use_cold_recall=use_cold_recall,
            cold_recall_items=cold_recall_items,
        )
        messages = self._budget_chapter_messages(messages)
        model = (llm_model or router.model or "").strip() or "-"
        web_search = self._novel_web_search(db, flow="generate")
        timeout = settings.novel_chapter_timeout
        start = time.perf_counter()
        logger.info(
            "generate_chapter start | novel_id=%s chapter_no=%s model=%s web_search=%s cold_recall=%s cold_items=%s msg_chars=%s mem_chars=%s continuity_chars=%s",
            novel.id,
            chapter_no,
            model,
            web_search,
            use_cold_recall,
            cold_recall_items,
            self._messages_chars(messages),
            len(memory_json or ""),
            len(continuity_excerpt or ""),
        )
        try:
            out = await self._chat_text_with_timeout_retry(
                router=router,
                operation="generate_chapter",
                novel_id=novel.id,
                chapter_no=chapter_no,
                messages=messages,
                temperature=0.45,
                web_search=web_search,
                timeout=timeout,
                max_tokens=settings.novel_chapter_max_tokens,
                **self._bill_kw(db, self._billing_user_id),
            )
            return out
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "generate_chapter done | novel_id=%s chapter_no=%s elapsed=%.2fs",
                novel.id,
                chapter_no,
                elapsed,
            )

    def generate_chapter_sync(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        recent_full_context: str = "",
        chapter_plan_hint: str = "",
        db: Any = None,
        *,
        use_cold_recall: bool = False,
        cold_recall_items: int = 5,
    ) -> str:
        router = self._router(db=db)
        messages = _chapter_messages(
            novel,
            chapter_no,
            chapter_title_hint,
            memory_json,
            continuity_excerpt,
            recent_full_context,
            chapter_plan_hint,
            db=db,
            use_cold_recall=use_cold_recall,
            cold_recall_items=cold_recall_items,
        )
        messages = self._budget_chapter_messages(messages)
        model = (router.model or "").strip() or "-"
        web_search = self._novel_web_search(db, flow="generate")
        timeout = settings.novel_chapter_timeout
        start = time.perf_counter()
        logger.info(
            "generate_chapter_sync start | novel_id=%s chapter_no=%s model=%s web_search=%s cold_recall=%s cold_items=%s msg_chars=%s",
            novel.id,
            chapter_no,
            model,
            web_search,
            use_cold_recall,
            cold_recall_items,
            self._messages_chars(messages),
        )
        try:
            return self._chat_text_sync_with_timeout_retry(
                router=router,
                operation="generate_chapter",
                novel_id=novel.id,
                chapter_no=chapter_no,
                messages=messages,
                temperature=0.45,
                timeout=timeout,
                web_search=web_search,
                max_tokens=settings.novel_chapter_max_tokens,
                **self._bill_kw(db, self._billing_user_id),
            )
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "generate_chapter_sync done | novel_id=%s chapter_no=%s elapsed=%.2fs",
                novel.id,
                chapter_no,
                elapsed,
            )

    async def check_and_fix_chapter(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        chapter_text: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        messages = _check_and_fix_chapter_messages(
            novel,
            chapter_no,
            chapter_title_hint,
            memory_json,
            continuity_excerpt,
            chapter_text,
            db,
        )
        messages = self._budget_chapter_messages(messages)
        start = time.perf_counter()
        logger.info(
            "check_and_fix_chapter start | novel_id=%s chapter_no=%s msg_chars=%s text_chars=%s",
            novel.id,
            chapter_no,
            self._messages_chars(messages),
            len(chapter_text or ""),
        )
        try:
            return await self._chat_text_with_timeout_retry(
                router=router,
                operation="check_and_fix_chapter",
                novel_id=novel.id,
                chapter_no=chapter_no,
                messages=messages,
                temperature=settings.novel_consistency_check_temperature,
                web_search=False,
                timeout=settings.novel_consistency_check_timeout,
                **self._bill_kw(db, self._billing_user_id),
            )
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "check_and_fix_chapter done | novel_id=%s chapter_no=%s elapsed=%.2fs",
                novel.id,
                chapter_no,
                elapsed,
            )

    def check_and_fix_chapter_sync(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        chapter_text: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="check_and_fix_chapter",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _check_and_fix_chapter_messages(
                    novel,
                    chapter_no,
                    chapter_title_hint,
                    memory_json,
                    continuity_excerpt,
                    chapter_text,
                    db,
                )
            ),
            temperature=settings.novel_consistency_check_temperature,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def audit_chapter_against_plan_sync(
        self,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        chapter_text: str,
        db: Any = None,
    ) -> dict[str, Any]:
        if not chapter_plan_has_guardrails(beats):
            return {"ok": True, "violations": [], "warnings": [], "skipped": True}
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="audit_chapter_against_plan",
            novel_id="-",
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _audit_chapter_against_plan_messages(
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    chapter_text=chapter_text,
                )
            ),
            temperature=0.15,
            web_search=False,
            timeout=180.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _safe_json_dict(raw)
        if not parsed:
            try:
                repaired = json_repair_loads(raw or "{}")
                parsed = repaired if isinstance(repaired, dict) else {}
            except Exception:
                parsed = {}
        violations = _dedupe_str_list(parsed.get("violations") or [], max_items=12)
        warnings = _dedupe_str_list(parsed.get("warnings") or [], max_items=12)
        ok = bool(parsed.get("ok")) if "ok" in parsed else (len(violations) == 0)
        return {
            "ok": ok and len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "skipped": False,
        }

    def fix_chapter_to_plan_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        memory_json: str,
        continuity_excerpt: str,
        chapter_text: str,
        violations: list[str],
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="fix_chapter_to_plan",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _fix_chapter_to_plan_messages(
                    novel,
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    memory_json=memory_json,
                    continuity_excerpt=continuity_excerpt,
                    chapter_text=chapter_text,
                    violations=violations,
                    db=db,
                )
            ),
            temperature=settings.novel_consistency_check_temperature,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def polish_chapter_style_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        chapter_text: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="polish_chapter_style",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _de_ai_chapter_messages(
                    novel,
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    chapter_text=chapter_text,
                    db=db,
                )
            ),
            temperature=0.25,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def expressive_enhance_chapter_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        chapter_text: str,
        db: Any = None,
        strength: str | None = None,
    ) -> str:
        st = (strength or settings.novel_expressive_enhance_strength or "safe").strip()
        router = self._router(db=db)
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="expressive_enhance_chapter",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _expressive_enhance_chapter_messages(
                    novel,
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    chapter_text=chapter_text,
                    strength=st,
                    db=db,
                )
            ),
            temperature=0.35,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def _parse_refresh_memory_response(self, raw: str) -> dict[str, Any]:
        candidates: list[str] = []
        text = (raw or "").strip()
        if text:
            candidates.append(text)
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            extracted = m.group(0).strip()
            if extracted and extracted not in candidates:
                candidates.append(extracted)

        for blob in candidates:
            try:
                parsed = json.loads(blob)
                if isinstance(parsed, dict):
                    return self._normalize_refresh_memory_response(parsed)
            except json.JSONDecodeError:
                pass

        for blob in candidates:
            try:
                parsed = json_repair_loads(blob)
                if isinstance(parsed, dict):
                    return self._normalize_refresh_memory_response(parsed)
            except Exception:
                pass
        return {}

    @staticmethod
    def _empty_refresh_memory_delta() -> dict[str, Any]:
        return {
            "facts_added": [],
            "facts_updated": [],
            "open_plots_added": [],
            "open_plots_resolved": [],
            "canonical_entries": [],
            "characters_added": [],
            "characters_updated": [],
            "characters_inactivated": [],
            "relations_added": [],
            "relations_updated": [],
            "relations_inactivated": [],
            "relations_changed": [],
            "inventory_changed": {"added": [], "removed": []},
            "skills_changed": {"added": [], "updated": [], "removed": []},
            "pets_changed": {"added": [], "updated": [], "removed": []},
            "conflicts_detected": [],
            "forbidden_constraints_added": [],
            "ids_to_remove": [],
            "entity_influence_updates": [],
        }

    @classmethod
    def _normalize_refresh_memory_response(cls, parsed: dict[str, Any]) -> dict[str, Any]:
        normalized = cls._empty_refresh_memory_delta()
        for key, value in parsed.items():
            normalized[key] = value

        # 1. 章节项去重（按 chapter_no）
        raw_entries = normalized.get("canonical_entries")
        if isinstance(raw_entries, list):
            unique_entries_map: dict[int, dict[str, Any]] = {}
            for item in raw_entries:
                norm_item = cls._normalize_delta_entry(item)
                if norm_item:
                    cno = norm_item["chapter_no"]
                    if cno in unique_entries_map:
                        # 如果重复，合并它们
                        unique_entries_map[cno] = cls._merge_timeline_entry(unique_entries_map[cno], norm_item)
                    else:
                        unique_entries_map[cno] = norm_item
            normalized["canonical_entries"] = [unique_entries_map[k] for k in sorted(unique_entries_map.keys())]

        def _dedupe_named_entities(raw: Any) -> list[dict[str, Any]]:
            if not isinstance(raw, list):
                return []
            unique_map: dict[str, dict[str, Any]] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if name:
                    unique_map[name] = item
            return list(unique_map.values())

        def _dedupe_relations(raw: Any) -> list[dict[str, Any]]:
            if not isinstance(raw, list):
                return []
            unique_map: dict[tuple[str, str], dict[str, Any]] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                if src and dst:
                    unique_map[(src, dst)] = item
            return list(unique_map.values())

        normalized["characters_added"] = _dedupe_named_entities(normalized.get("characters_added"))
        normalized["characters_updated"] = _dedupe_named_entities(normalized.get("characters_updated"))
        normalized["characters_inactivated"] = _dedupe_named_entities(
            normalized.get("characters_inactivated")
        )
        normalized["relations_added"] = _dedupe_relations(normalized.get("relations_added"))
        normalized["relations_updated"] = _dedupe_relations(
            [
                *_dedupe_relations(normalized.get("relations_updated")),
                *_dedupe_relations(normalized.get("relations_changed")),
            ]
        )
        normalized["relations_inactivated"] = _dedupe_relations(
            normalized.get("relations_inactivated")
        )

        # 3. 其他常规字段清理
        inventory_changed = normalized.get("inventory_changed")
        if not isinstance(inventory_changed, dict):
            inventory_changed = {}
        normalized["inventory_changed"] = {
            "added": inventory_changed.get("added") if isinstance(inventory_changed.get("added"), list) else [],
            "removed": inventory_changed.get("removed") if isinstance(inventory_changed.get("removed"), list) else [],
        }

        skills_changed = normalized.get("skills_changed")
        if not isinstance(skills_changed, dict):
            skills_changed = {}
        normalized["skills_changed"] = {
            "added": skills_changed.get("added") if isinstance(skills_changed.get("added"), list) else [],
            "updated": skills_changed.get("updated") if isinstance(skills_changed.get("updated"), list) else [],
            "removed": skills_changed.get("removed") if isinstance(skills_changed.get("removed"), list) else [],
        }

        pets_changed = normalized.get("pets_changed")
        if not isinstance(pets_changed, dict):
            pets_changed = {}
        normalized["pets_changed"] = {
            "added": pets_changed.get("added") if isinstance(pets_changed.get("added"), list) else [],
            "updated": pets_changed.get("updated") if isinstance(pets_changed.get("updated"), list) else [],
            "removed": pets_changed.get("removed") if isinstance(pets_changed.get("removed"), list) else [],
        }
        return normalized

    @staticmethod
    def _extract_chapter_blobs(chapters_summary: str) -> list[dict[str, Any]]:
        text = (chapters_summary or "").strip()
        if not text:
            return []

        pattern = re.compile(r"(?m)^第\s*(\d+)\s*章(?:《([^》\n]*)》|[ \t]+([^\n]+))?\n")
        matches = list(pattern.finditer(text))
        if not matches:
            return []

        out: list[dict[str, Any]] = []
        for idx, match in enumerate(matches):
            chapter_no = int(match.group(1))
            title = str(match.group(2) or match.group(3) or "").strip()
            body_start = match.end()
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            chapter_text = text[body_start:body_end].strip()
            out.append(
                {
                    "chapter_no": chapter_no,
                    "chapter_title": title,
                    "chapter_text": chapter_text,
                }
            )
        return out

    @staticmethod
    def _fallback_list_from_text(text: str, *, limit: int, item_max_chars: int = 120) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return []
        chunks = [
            seg.strip(" -\t")
            for seg in re.split(r"(?:\n{2,}|[。！？!?]\s*)", cleaned)
            if seg and seg.strip(" -\t")
        ]
        out: list[str] = []
        for seg in chunks:
            short = seg[:item_max_chars].strip()
            if short and short not in out:
                out.append(short)
            if len(out) >= limit:
                break
        if not out:
            return [cleaned[:item_max_chars]]
        return out

    @classmethod
    def _build_fallback_canonical_entry(
        cls,
        *,
        chapter_no: int,
        chapter_title: str,
        chapter_text: str,
    ) -> dict[str, Any]:
        key_facts = cls._fallback_list_from_text(chapter_text, limit=3, item_max_chars=120)
        tail_candidates = cls._fallback_list_from_text(chapter_text[-500:], limit=2, item_max_chars=120)
        causal_results = tail_candidates[:1] if tail_candidates else []
        unresolved_hooks = [
            item
            for item in tail_candidates[1:]
            if any(token in item for token in ("?", "？", "将", "未", "待", "是否"))
        ][:2]
        return {
            "chapter_no": chapter_no,
            "chapter_title": (chapter_title or f"第{chapter_no}章").strip(),
            "key_facts": key_facts,
            "causal_results": causal_results,
            "open_plots_added": [],
            "open_plots_resolved": [],
            "emotional_state": "",
            "unresolved_hooks": unresolved_hooks,
        }

    @classmethod
    def _extract_chapter_no(cls, item: Any) -> int | None:
        """从条目提取章节号，处理各种格式（字符串、整数等）"""
        if not isinstance(item, dict):
            return None
        cn = item.get("chapter_no")
        if isinstance(cn, int):
            return cn if cn > 0 else None
        if isinstance(cn, str):
            cn = cn.strip()
            if cn.isdigit():
                return int(cn)
        return None

    @classmethod
    def _supplement_missing_canonical_entries(
        cls,
        delta: dict[str, Any],
        chapters_summary: str,
    ) -> tuple[dict[str, Any], list[int]]:
        blobs = cls._extract_chapter_blobs(chapters_summary)
        if not blobs:
            return delta, []

        existing_entries = delta.get("canonical_entries")
        if not isinstance(existing_entries, list):
            existing_entries = []

        # 1. 先清理和去重已有条目（按 chapter_no）
        existing_nos: set[int] = set()
        unique_entries: list[dict[str, Any]] = []
        for item in existing_entries:
            cno = cls._extract_chapter_no(item)
            if cno is None:
                # 格式不正确的条目保留，但不参与去重判断
                unique_entries.append(item)
                continue
            if cno in existing_nos:
                # 重复条目：找到已存在的并合并
                for idx, existing in enumerate(unique_entries):
                    if cls._extract_chapter_no(existing) == cno:
                        norm_existing = cls._normalize_delta_entry(existing)
                        norm_item = cls._normalize_delta_entry(item)
                        if norm_existing and norm_item:
                            unique_entries[idx] = cls._merge_timeline_entry(norm_existing, norm_item)
                        break
            else:
                existing_nos.add(cno)
                unique_entries.append(item)

        # 2. 为缺失的章节创建兜底条目
        missing_entries: list[dict[str, Any]] = []
        missing_nos: list[int] = []
        for blob in blobs:
            chapter_no = int(blob["chapter_no"])
            if chapter_no in existing_nos:
                continue
            existing_nos.add(chapter_no)
            missing_nos.append(chapter_no)
            missing_entries.append(
                cls._build_fallback_canonical_entry(
                    chapter_no=chapter_no,
                    chapter_title=str(blob.get("chapter_title") or ""),
                    chapter_text=str(blob.get("chapter_text") or ""),
                )
            )

        if not missing_entries:
            return delta, []

        patched = dict(delta)
        patched["canonical_entries"] = [*unique_entries, *missing_entries]
        return patched, missing_nos

    @classmethod
    def _refresh_memory_repair_messages(cls, raw: str) -> list[dict[str, str]]:
        example = json.dumps(cls._empty_refresh_memory_delta(), ensure_ascii=False)
        return [
            {
                "role": "system",
                "content": (
                    "你是记忆增量 JSON 修复器。"
                    "你只能输出一个可被 json.loads() 直接解析的 JSON 对象。"
                    "不要输出解释、Markdown、代码块或多余文字。"
                    "如果原文缺少字段，必须补齐为空数组或空对象。"
                    "输出结构示例："
                    f"{example}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把下面这段模型原始输出修复为合法 JSON 对象，只保留记忆增量本体：\n"
                    f"{raw or ''}"
                ),
            },
        ]

    async def _repair_refresh_memory_response(
        self,
        *,
        router: LLMRouter,
        raw: str,
        db: Any = None,
    ) -> dict[str, Any]:
        try:
            repaired_raw = await router.chat_text(
                messages=self._refresh_memory_repair_messages(raw),
                temperature=0.0,
                timeout=min(120.0, settings.novel_memory_refresh_batch_timeout),
                max_tokens=min(settings.novel_memory_delta_max_tokens, 4096),
                response_format={"type": "json_object"},
                **self._bill_kw(db, self._billing_user_id),
            )
        except Exception:
            logger.exception("memory delta json repair failed(async)")
            return {}
        return self._parse_refresh_memory_response(repaired_raw)

    def _repair_refresh_memory_response_sync(
        self,
        *,
        router: LLMRouter,
        raw: str,
        db: Any = None,
    ) -> dict[str, Any]:
        try:
            repaired_raw = router.chat_text_sync(
                messages=self._refresh_memory_repair_messages(raw),
                temperature=0.0,
                timeout=min(120.0, settings.novel_memory_refresh_batch_timeout),
                max_tokens=min(settings.novel_memory_delta_max_tokens, 4096),
                response_format={"type": "json_object"},
                **self._bill_kw(db, self._billing_user_id),
            )
        except Exception:
            logger.exception("memory delta json repair failed(sync)")
            return {}
        return self._parse_refresh_memory_response(repaired_raw)

    def _build_memory_delta_plan_targets(
        self,
        db: Session | None,
        novel_id: str,
        chapters_summary: str,
    ) -> str:
        if not db:
            return ""
        chapter_nos = [
            int(blob["chapter_no"])
            for blob in self._extract_chapter_blobs(chapters_summary)
            if isinstance(blob, dict) and blob.get("chapter_no")
        ]
        if not chapter_nos:
            return ""
        rows = (
            db.query(NovelChapterPlan)
            .filter(
                NovelChapterPlan.novel_id == novel_id,
                NovelChapterPlan.chapter_no.in_(chapter_nos),
            )
            .order_by(NovelChapterPlan.chapter_no.asc())
            .all()
        )
        if not rows:
            return ""

        sections: list[str] = ["【本批章节对应章计划的结束状态目标】"]
        for row in rows:
            try:
                beats = json.loads(row.beats_json or "{}")
            except json.JSONDecodeError:
                beats = {}
            card = chapter_plan_execution_card(beats)
            targets = card.get("end_state_targets") if isinstance(card, dict) else {}
            if not isinstance(targets, dict):
                continue
            chunks: list[str] = []
            for key, label in (
                ("characters", "角色状态"),
                ("relations", "关系状态"),
                ("items", "物品状态"),
                ("plots", "线索状态"),
            ):
                values = targets.get(key)
                if not isinstance(values, list):
                    continue
                bullets = [str(x).strip() for x in values if str(x).strip()]
                if bullets:
                    chunks.append(f"{label}：\n" + "\n".join(f"  · {x}" for x in bullets[:8]))
            if chunks:
                sections.append(
                    f"第{row.chapter_no}章《{row.chapter_title or f'第{row.chapter_no}章'}》\n"
                    + "\n".join(chunks)
                )
        return "\n\n".join(sections) if len(sections) > 1 else ""

    def _memory_delta_messages(
        self, novel: Novel, chapters_summary: str, prev_memory: str, db: Session | None = None
    ) -> list[dict[str, str]]:
        fj = truncate_framework_json(effective_framework_json_for_prompt(db, novel), 6000)
        compact_prev = build_hot_memory_for_prompt(
            prev_memory,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
        )
        prev_open_plots = format_open_plots_block(prev_memory)
        plan_targets_block = self._build_memory_delta_plan_targets(db, novel.id, chapters_summary)
        sys = (
            "你是小说记忆增量抽取器。"
            "你不能重写整份记忆，只能根据新章节内容输出“本批新增/变更了什么”。"
            "必须输出严格 JSON 对象，不要 Markdown，不要解释。"
            "若某字段没有变化，必须输出空数组或空对象。"
            "若本批输入里包含 1 章或多章内容，则 canonical_entries 必须为本批每一章各输出一条条目，不允许漏章。"
            "输出字段固定为："
            "facts_added[], facts_updated[], open_plots_added[], open_plots_resolved[],"
            "canonical_entries[], characters_added[], characters_updated[], characters_inactivated[],"
            "relations_added[], relations_updated[], relations_inactivated[],"
            "inventory_changed{added[],removed[]}, skills_changed{added[],updated[],removed[]},"
            "pets_changed{added[],updated[],removed[]}, conflicts_detected[],"
            "forbidden_constraints_added[], ids_to_remove[], entity_influence_updates[]。"
            "ids_to_remove[]：非常重要！当你判断某条【待收束线】已收束、某条【硬约束】已失效、或某项技能/道具已遗失/毁坏时，"
            "直接在 ids_to_remove 中填入该条目在下文提供的 4 位短 ID。不要通过文本匹配删除。\n"
            "【同类条目替换与升级规则（通用）】\n"
            "1. 状态/等级更新：若某项属性、技能或物品存在明显的等级递进或阶段更替（如：等级1 -> 等级2，初级 -> 中级），必须在 added 中加入新条目，并务必在 ids_to_remove 中放入旧条目的 ID。严禁同一实体的多个版本/阶段同时处于活跃状态。\n"
            "1.1 若升级后名称发生变化（旧名不再出现），必须把旧条目放入 skills_changed.removed / pets_changed.removed（优先填 ID，没有 ID 才填旧名）。\n"
            "2. 唯一性冲突：对于在设定上具有唯一性或排他性的条目，新条目出现时必须移除旧条目。"
            "canonical_entries 每项结构："
            "{chapter_no:number, chapter_title:string, key_facts:string[], causal_results:string[],"
            " open_plots_added:(string|{body,plot_type,priority,estimated_duration,current_stage,resolve_when})[],"
            " open_plots_resolved:string[],"
            " emotional_state:string, unresolved_hooks:string[]}。"
            "open_plots_added 可为字符串或对象：对象时 plot_type 取 Core|Arc|Transient，"
            "priority 越大越重要，estimated_duration 为预计持续章节数（估算即可），"
            "current_stage 为当前推进到哪一步，resolve_when 为真正收束所需条件。"
            "【人物抽取硬约束】"
            "只要本批章节中出现了明确人名，这个人物就必须被记录，绝对不允许遗漏。"
            "不管是主角、配角、反派、路人、只出场一次的人物，还是回忆/传闻/书信中明确点名的人物，只要出现姓名都要入库。"
            "首次出现的人名必须写入 characters_added；旧人物有状态、立场、伤势、阵营、目标、身份认知变化时必须写入 characters_updated；"
            "人物死亡、长期退场、离队、封印等明确下线写入 characters_inactivated。"
            "人物条目必须使用唯一主名，避免用代称、称谓或模糊指代；若正文里只写称谓，但上下文能确定实名，也必须回填实名。"
            "characters_added / characters_updated / characters_inactivated / entity_influence_updates 可含 influence_score(0-100)、is_active。"
            "【人物关系硬约束】"
            "只要本批章节里出现两个人物之间的亲属、同盟、敌对、上下级、爱慕、利用、师徒、交易、控制、怀疑、冲突等可识别关系，relations 必须有记录，绝对不能缺失。"
            "relations_added 用于新建立的重要关系；relations_updated 用于已有关系变化；relations_inactivated 用于关系失效、断裂或不再成立。"
            "若 characters 中出现了本批新人物或发生状态变化的人物，你必须同步检查并补齐其与其他人物的关系变化；不要只记人物不记关系。"
            "entity_influence_updates 每项：{entity_type, name, influence_score?, is_active?}，"
            "entity_type 为 character|skill|item|pet|plot 之一。"
            "forbidden_constraints_added：新增全局禁止事项（硬设定防火墙），须谨慎，只写正文绝不能违反的规则。"
            "facts_added / facts_updated 不要再重复塞进 notes。"
            "严禁输出全量 world_rules/main_plot/arcs。"
            "open_plots_resolved：每条字符串必须与下文【全书待收束线】或 canonical_entries 中已有 open_plots 的 body 文本完全一致（逐字一致）；"
            "只允许填写真正影响剧情推进、人物关系、核心矛盾、卷目标或后续章节承接的关键收束线；"
            "日常动作、一次性细节、气氛描写、小误会、无后续影响的临时事件，即使结束了也不要写入 open_plots_resolved。"
            "推荐优先使用 ids_to_remove 进行删除。"
            f"合法输出示例：{json.dumps(self._empty_refresh_memory_delta(), ensure_ascii=False)}"
        )
        user = (
            f"【框架 JSON（硬约束）】\n{fj}\n\n"
            f"【旧记忆热层快照（含 ID）】\n{compact_prev}\n\n"
            f"{prev_open_plots}\n\n"
            f"{plan_targets_block}\n\n" if plan_targets_block else
            f"【框架 JSON（硬约束）】\n{fj}\n\n"
            f"【旧记忆热层快照（含 ID）】\n{compact_prev}\n\n"
            f"{prev_open_plots}\n\n"
        )
        user += (
            f"【新章节文本/摘要】\n{chapters_summary}\n\n"
            "任务：提取本批章节相对旧记忆的增量事实。\n"
            "特别提醒：若实体状态/等级发生变更（升级、替换），必须找到旧版本的 ID 放入 ids_to_remove！"
            "如果某条线索在本批明确收束，请将该线索的 ID 放入 ids_to_remove；"
            "如果某条硬约束、技能或物品不再适用，也请放入 ids_to_remove。"
            "如果只是推进但未真正解决，不要移除。"
            "如果章计划里明确给了本章结束状态目标，优先按该目标判断人物、关系和物品的新增/更新/下线。"
            "再次强调：所有出现明确姓名的人物都要记录，且相关人物关系必须补齐，不允许漏人、不允许漏关系。"
            "再次强调：只总结关键收束线，不要总结对主剧情没有实质影响的小收尾。"
        )
        return [
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _is_key_resolved_plot(plot: Any, *, current_chapter_no: int = 0) -> bool:
        if plot is None:
            return False
        if isinstance(plot, dict):
            plot_type = normalize_plot_type(plot.get("plot_type"))
            priority = clamp_int(plot.get("priority"), minimum=0, maximum=100, default=0)
            estimated_duration = clamp_int(
                plot.get("estimated_duration"), minimum=0, maximum=999, default=0
            )
            introduced = clamp_int(
                plot.get("introduced_chapter"), minimum=0, maximum=20000, default=0
            )
            touched = clamp_int(
                plot.get("last_touched_chapter"), minimum=0, maximum=20000, default=0
            )
            current_stage = str(plot.get("current_stage") or "").strip()
            resolve_when = str(plot.get("resolve_when") or "").strip()
        else:
            plot_type = normalize_plot_type(getattr(plot, "plot_type", "Transient"))
            priority = clamp_int(
                getattr(plot, "priority", 0), minimum=0, maximum=100, default=0
            )
            estimated_duration = clamp_int(
                getattr(plot, "estimated_duration", 0),
                minimum=0,
                maximum=999,
                default=0,
            )
            introduced = clamp_int(
                getattr(plot, "introduced_chapter", 0),
                minimum=0,
                maximum=20000,
                default=0,
            )
            touched = clamp_int(
                getattr(plot, "last_touched_chapter", 0),
                minimum=0,
                maximum=20000,
                default=0,
            )
            current_stage = str(getattr(plot, "current_stage", "") or "").strip()
            resolve_when = str(getattr(plot, "resolve_when", "") or "").strip()
        observed_end = max(current_chapter_no, touched, introduced)
        chapter_span = max(0, observed_end - introduced)
        return any(
            (
                plot_type in {"Core", "Arc"},
                priority >= 20,
                estimated_duration >= 4,
                chapter_span >= 3,
                bool(current_stage and resolve_when and plot_type != "Transient"),
            )
        )

    @classmethod
    def _filter_key_resolved_plot_bodies(
        cls,
        bodies: list[str],
        *,
        plot_lookup: dict[str, Any],
        current_chapter_no: int = 0,
    ) -> list[str]:
        kept: list[str] = []
        seen: set[str] = set()
        for body in bodies:
            normalized = str(body or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            plot = plot_lookup.get(normalized)
            if plot is None or cls._is_key_resolved_plot(
                plot, current_chapter_no=current_chapter_no
            ):
                kept.append(normalized)
        return kept

    @staticmethod
    def _normalize_delta_entry(entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        chapter_no = entry.get("chapter_no")
        if isinstance(chapter_no, str) and chapter_no.strip().isdigit():
            chapter_no = int(chapter_no.strip())
        if not isinstance(chapter_no, int) or chapter_no <= 0:
            return None
        # open_plots_added：保留字符串或对象，供合并时解析
        raw_added = entry.get("open_plots_added", [])
        open_plots_added_norm: list[Any] = []
        if isinstance(raw_added, list):
            for x in raw_added:
                if isinstance(x, dict):
                    body = str(x.get("body") or "").strip()
                    if body:
                        open_plots_added_norm.append(
                            {
                                "body": body,
                                "plot_type": normalize_plot_type(x.get("plot_type")),
                                "priority": clamp_int(x.get("priority"), minimum=0, maximum=100, default=0),
                                "estimated_duration": max(
                                    0, clamp_int(x.get("estimated_duration"), minimum=0, maximum=999, default=0)
                                ),
                                "current_stage": str(x.get("current_stage") or "").strip()[:500],
                                "resolve_when": str(x.get("resolve_when") or "").strip()[:500],
                            }
                        )
                else:
                    s = str(x or "").strip()
                    if s:
                        open_plots_added_norm.append(s)
        uh = entry.get("unresolved_hooks")
        if not isinstance(uh, list):
            uh = []
        normalized = {
            "chapter_no": chapter_no,
            "chapter_title": str(entry.get("chapter_title") or "").strip(),
            "key_facts": _dedupe_str_list(entry.get("key_facts", [])),
            "causal_results": _dedupe_str_list(entry.get("causal_results", [])),
            "open_plots_added": open_plots_added_norm,
            "open_plots_resolved": _dedupe_str_list(
                NovelLLMService._open_plot_bodies_from_mixed(entry.get("open_plots_resolved"))
            ),
            "emotional_state": str(entry.get("emotional_state") or "").strip(),
            "unresolved_hooks": _dedupe_str_list(uh),
        }
        return normalized

    @staticmethod
    def _merge_timeline_open_plots_added(base: Any, incoming: Any) -> list[Any]:
        out: list[Any] = []
        seen: set[str] = set()

        def _body(x: Any) -> str:
            if isinstance(x, dict):
                return str(x.get("body") or "").strip()
            return str(x or "").strip()

        for seq in (base if isinstance(base, list) else [], incoming if isinstance(incoming, list) else []):
            for x in seq:
                b = _body(x)
                if not b or b in seen:
                    continue
                seen.add(b)
                out.append(x)
        return out

    @staticmethod
    def _open_plot_bodies_from_mixed(items: Any) -> list[str]:
        out: list[str] = []
        if not isinstance(items, list):
            return out
        for x in items:
            if isinstance(x, dict):
                b = str(x.get("body") or "").strip()
                if b:
                    out.append(b)
            else:
                s = str(x or "").strip()
                if s:
                    out.append(s)
        return out

    @classmethod
    def _merge_timeline_entry(cls, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        merged["chapter_no"] = incoming["chapter_no"]
        merged["chapter_title"] = str(
            incoming.get("chapter_title") or base.get("chapter_title") or ""
        ).strip()
        merged["key_facts"] = _dedupe_str_list(
            [*(base.get("key_facts") or []), *(incoming.get("key_facts") or [])]
        )
        merged["causal_results"] = _dedupe_str_list(
            [*(base.get("causal_results") or []), *(incoming.get("causal_results") or [])]
        )
        merged["open_plots_added"] = cls._merge_timeline_open_plots_added(
            base.get("open_plots_added"), incoming.get("open_plots_added")
        )
        merged["open_plots_resolved"] = _dedupe_str_list(
            [
                *NovelLLMService._open_plot_bodies_from_mixed(base.get("open_plots_resolved")),
                *NovelLLMService._open_plot_bodies_from_mixed(incoming.get("open_plots_resolved")),
            ]
        )
        emo_in = str(incoming.get("emotional_state") or "").strip()
        merged["emotional_state"] = emo_in or str(base.get("emotional_state") or "").strip()
        merged["unresolved_hooks"] = _dedupe_str_list(
            [*(base.get("unresolved_hooks") or []), *(incoming.get("unresolved_hooks") or [])]
        )
        return merged

    @staticmethod
    def _inventory_entry_label_and_detail(entry: Any) -> tuple[str, str]:
        """
        inventory_changed 里 LLM 可能输出字符串或对象（含 item/name/description）。
        label 列必须为短字符串；完整对象写入 detail_json。
        """
        if isinstance(entry, dict):
            lab = str(
                entry.get("item_name")
                or entry.get("name")
                or entry.get("item")
                or entry.get("label")
                or entry.get("title")
                or ""
            ).strip()
            if not lab:
                lab = json.dumps(entry, ensure_ascii=False)[:512]
            else:
                lab = lab[:512]
            return lab, json.dumps(entry, ensure_ascii=False)
        s = str(entry or "").strip()[:512]
        return s, "{}"

    @staticmethod
    def _upsert_normalized_memory_from_delta(
        db: Session,
        novel_id: str,
        delta: dict[str, Any],
        memory_version: int,
        replace_timeline: bool = False,
        chapters_summary: str | None = None,
    ) -> dict[str, int]:
        """
        根据 LLM 返回的增量 Delta，直接更新规范化数据库表。
        返回操作统计。
        """
        stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
            "skills_updated": 0,
            "items_updated": 0,
        }
        
        # 0. 解析正文摘要中的章节号
        target_chapter_nos = []
        if chapters_summary:
            target_chapter_nos = [int(n) for n in re.findall(r"第(\d+)章", chapters_summary)]

        # 0.1 如果是刷新模式，先清空这些章节的旧事实，确保“先删除再更新”
        if replace_timeline and target_chapter_nos:
            # 1. 清空章节级事实
            db.query(NovelMemoryNormChapter).filter(
                NovelMemoryNormChapter.novel_id == novel_id,
                NovelMemoryNormChapter.chapter_no.in_(target_chapter_nos)
            ).update({
                "key_facts_json": "[]",
                "causal_results_json": "[]",
                "open_plots_added_json": "[]",
                "open_plots_resolved_json": "[]",
                "emotional_state": "",
                "unresolved_hooks_json": "[]"
            }, synchronize_session='fetch')
            
            # 2. 【核心加固】同步删除在这几章“出生”的剧情线实体，防止刷新后产生重复或残留的“孤儿”线索
            db.query(NovelMemoryNormPlot).filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.introduced_chapter.in_(target_chapter_nos)
            ).delete(synchronize_session='fetch')

        latest_delta_chapter_no = 0
        
        # 0. 处理全局删除：ids_to_remove
        ids_to_remove = set(delta.get("ids_to_remove") or [])
        if ids_to_remove:
            # 尝试在各分表中根据内容哈希删除或失效匹配项。
            # 人物与关系遵循软下线；物品保持硬删除。
            for table, attr in [
                (NovelMemoryNormPlot, "body"),
                (NovelMemoryNormSkill, "name"),
                (NovelMemoryNormItem, "label"),
                (NovelMemoryNormPet, "name"),
            ]:
                rows = db.query(table).filter(table.novel_id == novel_id).all()
                to_del_ids = []
                for row in rows:
                    val = getattr(row, attr)
                    if val and _short_id(val) in ids_to_remove:
                        to_del_ids.append(row.id)
                if to_del_ids:
                    db.query(table).filter(table.id.in_(to_del_ids)).delete(synchronize_session='fetch')

            for row in (
                db.query(NovelMemoryNormCharacter)
                .filter(NovelMemoryNormCharacter.novel_id == novel_id)
                .all()
            ):
                name = str(getattr(row, "name", "") or "").strip()
                if name and _short_id(name) in ids_to_remove:
                    row.is_active = False
                    row.memory_version = memory_version

            for row in (
                db.query(NovelMemoryNormRelation)
                .filter(NovelMemoryNormRelation.novel_id == novel_id)
                .all()
            ):
                relation_id = _relation_identity(
                    str(getattr(row, "src", "") or "").strip(),
                    str(getattr(row, "dst", "") or "").strip(),
                )
                if relation_id in ids_to_remove:
                    row.is_active = False
                    row.memory_version = memory_version
        active_plot_lookup = {
            str(row.body or "").strip(): row
            for row in db.query(NovelMemoryNormPlot)
            .filter(NovelMemoryNormPlot.novel_id == novel_id)
            .all()
            if str(row.body or "").strip()
        }

        # 1. 更新时间线 canonical_entries
        incoming_entries = delta.get("canonical_entries")
        if isinstance(incoming_entries, list):
            for item in incoming_entries:
                if not isinstance(item, dict):
                    continue
                chapter_no = item.get("chapter_no")
                if not isinstance(chapter_no, int):
                    continue
                latest_delta_chapter_no = max(latest_delta_chapter_no, chapter_no)
                
                # 查找是否存在该章节
                entry = db.query(NovelMemoryNormChapter).filter(
                    NovelMemoryNormChapter.novel_id == novel_id,
                    NovelMemoryNormChapter.chapter_no == chapter_no
                ).first()
                
                if not entry:
                    entry = NovelMemoryNormChapter(
                        novel_id=novel_id,
                        chapter_no=chapter_no,
                        memory_version=memory_version
                    )
                    db.add(entry)
                
                entry.chapter_title = str(item.get("chapter_title") or entry.chapter_title or "").strip()
                
                for field in ("key_facts", "causal_results", "open_plots_resolved"):
                    json_field = f"{field}_json"
                    old_list = json.loads(getattr(entry, json_field) or "[]")
                    inc = item.get(field) or []
                    if not isinstance(inc, list):
                        inc = []
                    
                    if replace_timeline:
                        # 刷新模式：直接使用 LLM 提取的内容替换旧内容（但仍做基础去重）
                        if field == "open_plots_resolved":
                            new_list = NovelLLMService._filter_key_resolved_plot_bodies(
                                NovelLLMService._open_plot_bodies_from_mixed(inc),
                                plot_lookup=active_plot_lookup,
                                current_chapter_no=chapter_no,
                            )
                        else:
                            new_list = _dedupe_str_list(inc)
                    else:
                        # 增量模式：追加
                        if field == "open_plots_resolved":
                            inc_norm = NovelLLMService._filter_key_resolved_plot_bodies(
                                NovelLLMService._open_plot_bodies_from_mixed(inc),
                                plot_lookup=active_plot_lookup,
                                current_chapter_no=chapter_no,
                            )
                            new_list = _dedupe_str_list([*old_list, *inc_norm])
                        else:
                            new_list = _dedupe_str_list([*old_list, *inc])
                    setattr(entry, json_field, json.dumps(new_list, ensure_ascii=False))

                oa_raw = item.get("open_plots_added") or []
                if not isinstance(oa_raw, list):
                    oa_raw = []
                bodies_add: list[str] = []
                for x in oa_raw:
                    if isinstance(x, dict):
                        b = str(x.get("body") or "").strip()
                        if b:
                            bodies_add.append(b)
                            plot = db.query(NovelMemoryNormPlot).filter(
                                NovelMemoryNormPlot.novel_id == novel_id,
                                NovelMemoryNormPlot.body == b,
                            ).first()
                            if plot:
                                plot.plot_type = normalize_plot_type(x.get("plot_type"))
                                plot.priority = clamp_int(
                                    x.get("priority"), minimum=0, maximum=100, default=0
                                )
                                plot.estimated_duration = max(
                                    0,
                                    clamp_int(
                                        x.get("estimated_duration"),
                                        minimum=0,
                                        maximum=999,
                                        default=0,
                                    ),
                                )
                                plot.current_stage = str(
                                    x.get("current_stage") or plot.current_stage or ""
                                ).strip()[:2000]
                                plot.resolve_when = str(
                                    x.get("resolve_when") or plot.resolve_when or ""
                                ).strip()[:2000]
                                if chapter_no > 0:
                                    if not getattr(plot, "introduced_chapter", 0):
                                        plot.introduced_chapter = chapter_no
                                    plot.last_touched_chapter = chapter_no
                                active_plot_lookup[b] = plot
                    else:
                        s = str(x or "").strip()
                        if s:
                            bodies_add.append(s)
                
                if replace_timeline:
                    # 刷新模式：替换 open_plots_added
                    entry.open_plots_added_json = json.dumps(
                        _dedupe_str_list(bodies_add), ensure_ascii=False
                    )
                else:
                    # 增量模式：追加
                    old_oa = json.loads(entry.open_plots_added_json or "[]")
                    entry.open_plots_added_json = json.dumps(
                        _dedupe_str_list([*old_oa, *bodies_add]), ensure_ascii=False
                    )

                emo = str(item.get("emotional_state") or "").strip()
                if emo:
                    entry.emotional_state = emo[:2000]
                
                uh = item.get("unresolved_hooks")
                if isinstance(uh, list) and uh:
                    if replace_timeline:
                        # 刷新模式：替换
                        new_uh = _dedupe_str_list([str(x).strip() for x in uh if str(x).strip()])
                    else:
                        # 增量模式：追加
                        old_uh = json.loads(entry.unresolved_hooks_json or "[]")
                        if not isinstance(old_uh, list):
                            old_uh = []
                        new_uh = _dedupe_str_list(
                            [
                                *old_uh,
                                *[str(x).strip() for x in uh if str(x).strip()],
                            ]
                        )
                    entry.unresolved_hooks_json = json.dumps(new_uh, ensure_ascii=False)

                entry.memory_version = memory_version
                stats["canonical_entries"] += 1

        # 2. 处理 open_plots 活跃列表
        raw_top_add = delta.get("open_plots_added", [])
        if not isinstance(raw_top_add, list):
            raw_top_add = []
        for plot_add in raw_top_add:
            if isinstance(plot_add, dict):
                body = str(plot_add.get("body") or "").strip()
                pt = normalize_plot_type(plot_add.get("plot_type"))
                pr = clamp_int(plot_add.get("priority"), minimum=0, maximum=100, default=0)
                est = max(
                    0,
                    clamp_int(
                        plot_add.get("estimated_duration"),
                        minimum=0,
                        maximum=999,
                        default=0,
                    ),
                )
                current_stage = str(plot_add.get("current_stage") or "").strip()
                resolve_when = str(plot_add.get("resolve_when") or "").strip()
            else:
                body = str(plot_add or "").strip()
                pt, pr, est = "Transient", 0, 0
                current_stage, resolve_when = "", ""
            if not body:
                continue
            exists = db.query(NovelMemoryNormPlot).filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.body == body,
            ).first()
            if not exists:
                max_order = (
                    db.query(func.max(NovelMemoryNormPlot.sort_order))
                    .filter(NovelMemoryNormPlot.novel_id == novel_id)
                    .scalar()
                    or 0
                )
                new_plot = NovelMemoryNormPlot(
                    novel_id=novel_id,
                    body=body,
                    sort_order=max_order + 1,
                    memory_version=memory_version,
                    plot_type=pt,
                    priority=pr,
                    estimated_duration=est,
                    current_stage=current_stage[:2000],
                    resolve_when=resolve_when[:2000],
                    introduced_chapter=latest_delta_chapter_no,
                    last_touched_chapter=latest_delta_chapter_no,
                )
                db.add(new_plot)
                active_plot_lookup[body] = new_plot
                stats["open_plots_added"] += 1
            else:
                exists.plot_type = pt
                exists.priority = pr
                exists.estimated_duration = est
                exists.current_stage = (current_stage or exists.current_stage or "")[:2000]
                exists.resolve_when = (resolve_when or exists.resolve_when or "")[:2000]
                if latest_delta_chapter_no > 0:
                    if not getattr(exists, "introduced_chapter", 0):
                        exists.introduced_chapter = latest_delta_chapter_no
                    exists.last_touched_chapter = latest_delta_chapter_no
                exists.memory_version = memory_version
                active_plot_lookup[body] = exists

        # 移除已结案的线索（与 plot.body 对齐：dict 取 body，禁止把 dict 绑进 SQL IN）
        top_resolved = NovelLLMService._filter_key_resolved_plot_bodies(
            NovelLLMService._open_plot_bodies_from_mixed(delta.get("open_plots_resolved")),
            plot_lookup=active_plot_lookup,
            current_chapter_no=latest_delta_chapter_no,
        )
        if top_resolved:
            db.query(NovelMemoryNormPlot).filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.body.in_(top_resolved)
            ).delete(synchronize_session='fetch')
            stats["open_plots_resolved"] += len(top_resolved)

        # 3. 更新角色（新增 / 更新 / 软下线）
        def _ensure_character_row(name: str) -> NovelMemoryNormCharacter:
            char = (
                db.query(NovelMemoryNormCharacter)
                .filter(
                    NovelMemoryNormCharacter.novel_id == novel_id,
                    NovelMemoryNormCharacter.name == name,
                )
                .first()
            )
            if char:
                return char
            max_order = (
                db.query(func.max(NovelMemoryNormCharacter.sort_order))
                .filter(NovelMemoryNormCharacter.novel_id == novel_id)
                .scalar()
                or 0
            )
            char = NovelMemoryNormCharacter(
                novel_id=novel_id,
                name=name,
                sort_order=max_order + 1,
                memory_version=memory_version,
            )
            db.add(char)
            return char

        def _apply_character_item(
            item: dict[str, Any],
            *,
            force_inactive: bool = False,
        ) -> NovelMemoryNormCharacter | None:
            name = str(item.get("name") or "").strip()
            if not name:
                return None
            char = _ensure_character_row(name)
            if item.get("role"):
                char.role = str(item["role"]).strip()
            status = str(item.get("status") or "").strip()
            if status:
                char.status = status

            traits = item.get("traits")
            if traits:
                old_traits = json.loads(char.traits_json or "[]")
                if isinstance(traits, list):
                    new_traits = _dedupe_str_list([*old_traits, *traits])
                else:
                    new_traits = _dedupe_str_list([*old_traits, str(traits)])
                char.traits_json = json.dumps(new_traits, ensure_ascii=False)

            aliases = dedupe_clean_strs(item.get("aliases"))
            if not aliases:
                aliases = extract_aliases(item)
            if aliases:
                old_aliases = json.loads(char.aliases_json or "[]")
                if not isinstance(old_aliases, list):
                    old_aliases = []
                char.aliases_json = json.dumps(
                    dedupe_clean_strs([*old_aliases, *aliases]),
                    ensure_ascii=False,
                )

            tags = item.get("tags")
            if isinstance(tags, list) and tags:
                old_tags = json.loads(char.tags_json or "[]")
                if not isinstance(old_tags, list):
                    old_tags = []
                char.tags_json = json.dumps(
                    dedupe_clean_strs([*old_tags, *[str(x) for x in tags]]),
                    ensure_ascii=False,
                )

            introduced_chapter = coerce_int(
                item.get("introduced_chapter") or item.get("source_chapter_no"),
                default=int(char.introduced_chapter or 0),
            )
            source_chapter_no = coerce_int(
                item.get("source_chapter_no"),
                default=int(char.source_chapter_no or introduced_chapter),
            )
            last_seen_chapter_no = coerce_int(
                item.get("last_seen_chapter_no"),
                default=max(
                    latest_delta_chapter_no,
                    int(char.last_seen_chapter_no or 0),
                    introduced_chapter,
                ),
            )
            expired_raw = item.get("expired_chapter")
            expired_chapter = (
                coerce_int(expired_raw, default=0) if expired_raw is not None else None
            )
            char.introduced_chapter = introduced_chapter
            char.source_chapter_no = source_chapter_no
            char.last_seen_chapter_no = last_seen_chapter_no
            char.expired_chapter = expired_chapter
            if item.get("identity_stage"):
                char.identity_stage = str(item.get("identity_stage") or "").strip()[:64]
            if item.get("exposed_identity_level") is not None:
                char.exposed_identity_level = str(
                    item.get("exposed_identity_level") or ""
                ).strip()[:32]

            detail = json.loads(char.detail_json or "{}")
            for k, v in item.items():
                if k not in ("name", "role", "status", "traits", "is_active"):
                    detail[k] = v
            if latest_delta_chapter_no > 0:
                detail["last_seen_chapter"] = latest_delta_chapter_no
                detail["last_touched_chapter"] = latest_delta_chapter_no
            if force_inactive:
                if latest_delta_chapter_no > 0:
                    detail["deactivated_at_chapter"] = latest_delta_chapter_no
                if status:
                    detail["inactive_reason"] = status
            char.detail_json = json.dumps(detail, ensure_ascii=False)

            if item.get("influence_score") is not None:
                try:
                    char.influence_score = int(item["influence_score"])
                except (TypeError, ValueError):
                    pass
            explicit_active = item.get("is_active")
            if explicit_active is not None:
                char.is_active = bool(explicit_active)
            elif force_inactive or _status_implies_inactive(status):
                char.is_active = False
            elif not status or char.is_active is None:
                char.is_active = True
            explicit_lifecycle = str(item.get("lifecycle_state") or "").strip() or None
            char.lifecycle_state = infer_lifecycle_state(
                is_active=bool(char.is_active),
                introduced_chapter=int(char.introduced_chapter or 0),
                last_seen_chapter=int(char.last_seen_chapter_no or 0),
                expired_chapter=char.expired_chapter,
                explicit=explicit_lifecycle,
            )
            char.memory_version = memory_version
            return char

        for bucket_key in ("characters_added", "characters_updated"):
            incoming_chars = delta.get(bucket_key)
            if isinstance(incoming_chars, list):
                for item in incoming_chars:
                    if not isinstance(item, dict):
                        continue
                    if _apply_character_item(item) is not None:
                        stats["characters_updated"] += 1

        incoming_chars_inactivated = delta.get("characters_inactivated")
        if isinstance(incoming_chars_inactivated, list):
            for item in incoming_chars_inactivated:
                if not isinstance(item, dict):
                    continue
                if _apply_character_item(item, force_inactive=True) is not None:
                    stats["characters_updated"] += 1

        # 3b. 实体影响力批量更新
        inf_updates = delta.get("entity_influence_updates")
        if isinstance(inf_updates, list):
            for u in inf_updates:
                if not isinstance(u, dict):
                    continue
                et = str(u.get("entity_type") or "").strip().lower()
                name = str(u.get("name") or "").strip()
                if not name:
                    continue
                score = u.get("influence_score")
                active = u.get("is_active")
                if et == "character":
                    row = (
                        db.query(NovelMemoryNormCharacter)
                        .filter(
                            NovelMemoryNormCharacter.novel_id == novel_id,
                            NovelMemoryNormCharacter.name == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            row.is_active = bool(active)
                        row.memory_version = memory_version
                elif et == "skill":
                    row = (
                        db.query(NovelMemoryNormSkill)
                        .filter(
                            NovelMemoryNormSkill.novel_id == novel_id,
                            NovelMemoryNormSkill.name == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            if not bool(active):
                                db.delete(row)
                                row = None
                            else:
                                row.is_active = True
                        if row is not None:
                            row.memory_version = memory_version
                elif et == "item":
                    row = (
                        db.query(NovelMemoryNormItem)
                        .filter(
                            NovelMemoryNormItem.novel_id == novel_id,
                            NovelMemoryNormItem.label == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            if not bool(active):
                                db.delete(row)
                                row = None
                            else:
                                row.is_active = True
                        if row is not None:
                            row.memory_version = memory_version
                elif et == "pet":
                    row = (
                        db.query(NovelMemoryNormPet)
                        .filter(
                            NovelMemoryNormPet.novel_id == novel_id,
                            NovelMemoryNormPet.name == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            row.is_active = bool(active)
                        row.memory_version = memory_version
                elif et == "plot":
                    row = (
                        db.query(NovelMemoryNormPlot)
                        .filter(
                            NovelMemoryNormPlot.novel_id == novel_id,
                            NovelMemoryNormPlot.body == name,
                        )
                        .first()
                    )
                    if row and score is not None:
                        try:
                            row.priority = int(score)
                        except (TypeError, ValueError):
                            pass
                        row.memory_version = memory_version

        # 4. 关系（新增 / 更新 / 软失效）
        def _ensure_relation_row(src: str, dst: str) -> NovelMemoryNormRelation:
            rel = (
                db.query(NovelMemoryNormRelation)
                .filter(
                    NovelMemoryNormRelation.novel_id == novel_id,
                    NovelMemoryNormRelation.src == src,
                    NovelMemoryNormRelation.dst == dst,
                )
                .first()
            )
            if rel:
                return rel
            max_order = (
                db.query(func.max(NovelMemoryNormRelation.sort_order))
                .filter(NovelMemoryNormRelation.novel_id == novel_id)
                .scalar()
                or 0
            )
            rel = NovelMemoryNormRelation(
                novel_id=novel_id,
                src=src,
                dst=dst,
                sort_order=max_order + 1,
                memory_version=memory_version,
            )
            db.add(rel)
            return rel

        def _apply_relation_item(
            item: dict[str, Any],
            *,
            force_inactive: bool = False,
        ) -> NovelMemoryNormRelation | None:
            src = str(item.get("from") or "").strip()
            dst = str(item.get("to") or "").strip()
            relation = str(item.get("relation") or "").strip()
            if not (src and dst):
                return None
            rel = _ensure_relation_row(src, dst)
            if relation:
                rel.relation = relation
            explicit_active = item.get("is_active")
            if explicit_active is not None:
                rel.is_active = bool(explicit_active)
            else:
                rel.is_active = not force_inactive
            rel.memory_version = memory_version
            return rel

        for bucket_key in ("relations_added", "relations_updated", "relations_changed"):
            incoming_relations = delta.get(bucket_key)
            if isinstance(incoming_relations, list):
                for item in incoming_relations:
                    if not isinstance(item, dict):
                        continue
                    _apply_relation_item(item, force_inactive=False)

        incoming_relations_inactivated = delta.get("relations_inactivated")
        if isinstance(incoming_relations_inactivated, list):
            for item in incoming_relations_inactivated:
                if not isinstance(item, dict):
                    continue
                _apply_relation_item(item, force_inactive=True)

        # 5. 物品（added/removed 可能为字符串或 dict，禁止把 dict 直接绑到 label 列）
        inv_changed = delta.get("inventory_changed")
        if isinstance(inv_changed, dict):
            added = inv_changed.get("added") or []
            removed = inv_changed.get("removed") or []

            removed_labels: list[str] = []
            removed_short_ids: set[str] = set()
            for x in removed:
                if isinstance(x, dict):
                    rid = str(x.get("id") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", rid):
                        removed_short_ids.add(rid)
                else:
                    token = str(x or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", token):
                        removed_short_ids.add(token)
                lab, _ = NovelLLMService._inventory_entry_label_and_detail(x)
                if lab:
                    removed_labels.append(lab)
            if removed_short_ids:
                for row in db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id
                ).all():
                    label = str(getattr(row, "label", "") or "").strip()
                    if label and _short_id(label).lower() in removed_short_ids:
                        removed_labels.append(label)
            if removed_labels:
                removed_labels = _dedupe_str_list(removed_labels)
                db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id,
                    NovelMemoryNormItem.label.in_(removed_labels),
                ).delete(synchronize_session=False)

            for raw in added:
                label, detail_json = NovelLLMService._inventory_entry_label_and_detail(raw)
                if not label:
                    continue
                score = None
                active = None
                if isinstance(raw, dict):
                    score = raw.get("influence_score")
                    active = raw.get("is_active")
                exists = db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id,
                    NovelMemoryNormItem.label == label,
                ).first()
                if not exists:
                    max_order = (
                        db.query(func.max(NovelMemoryNormItem.sort_order))
                        .filter(NovelMemoryNormItem.novel_id == novel_id)
                        .scalar()
                        or 0
                    )
                    new_item = NovelMemoryNormItem(
                        novel_id=novel_id,
                        label=label,
                        detail_json=detail_json,
                        sort_order=max_order + 1,
                        memory_version=memory_version,
                    )
                    if score is not None:
                        new_item.influence_score = clamp_int(score, minimum=0, maximum=100, default=0)
                    if active is not None:
                        new_item.is_active = bool(active)
                    db.add(new_item)
                else:
                    if isinstance(raw, dict) and detail_json != "{}":
                        exists.detail_json = detail_json
                    if score is not None:
                        exists.influence_score = clamp_int(score, minimum=0, maximum=100, default=0)
                    if active is not None:
                        exists.is_active = bool(active)
                    else:
                        exists.is_active = True
                    exists.memory_version = memory_version
                stats["items_updated"] += 1

        # 6. 技能
        skills_changed = delta.get("skills_changed")
        if isinstance(skills_changed, dict):
            added = skills_changed.get("added") or []
            updated = skills_changed.get("updated") or []
            removed = skills_changed.get("removed") or []

            removed_names: list[str] = []
            removed_short_ids: set[str] = set()
            for raw in removed:
                if isinstance(raw, dict):
                    name = str(raw.get("name") or "").strip()
                    rid = str(raw.get("id") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", rid):
                        removed_short_ids.add(rid)
                else:
                    name = str(raw or "").strip()
                    token = name.lower()
                    if re.fullmatch(r"[0-9a-f]{4}", token):
                        removed_short_ids.add(token)
                if name:
                    removed_names.append(name)
            if removed_short_ids:
                for row in db.query(NovelMemoryNormSkill).filter(
                    NovelMemoryNormSkill.novel_id == novel_id
                ).all():
                    n = str(getattr(row, "name", "") or "").strip()
                    if n and _short_id(n).lower() in removed_short_ids:
                        removed_names.append(n)
            if removed_names:
                removed_names = _dedupe_str_list(removed_names)
                db.query(NovelMemoryNormSkill).filter(
                    NovelMemoryNormSkill.novel_id == novel_id,
                    NovelMemoryNormSkill.name.in_(removed_names),
                ).delete(synchronize_session=False)
            
            for item in [*added, *updated]:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                else:
                    name = str(item or "").strip()
                
                if not name:
                    continue
                
                skill = db.query(NovelMemoryNormSkill).filter(
                    NovelMemoryNormSkill.novel_id == novel_id,
                    NovelMemoryNormSkill.name == name
                ).first()
                
                if not skill:
                    max_order = db.query(func.max(NovelMemoryNormSkill.sort_order)).filter(
                        NovelMemoryNormSkill.novel_id == novel_id
                    ).scalar() or 0
                    skill = NovelMemoryNormSkill(
                        novel_id=novel_id,
                        name=name,
                        sort_order=max_order + 1,
                        memory_version=memory_version
                    )
                    db.add(skill)
                
                if isinstance(item, dict):
                    aliases = dedupe_clean_strs(item.get("aliases"))
                    if aliases:
                        old_aliases = json.loads(skill.aliases_json or "[]")
                        if not isinstance(old_aliases, list):
                            old_aliases = []
                        skill.aliases_json = json.dumps(
                            dedupe_clean_strs([*old_aliases, *aliases]),
                            ensure_ascii=False,
                        )
                    tags = item.get("tags")
                    if isinstance(tags, list) and tags:
                        old_tags = json.loads(skill.tags_json or "[]")
                        if not isinstance(old_tags, list):
                            old_tags = []
                        skill.tags_json = json.dumps(
                            dedupe_clean_strs([*old_tags, *[str(x) for x in tags]]),
                            ensure_ascii=False,
                        )
                    detail = json.loads(skill.detail_json or "{}")
                    for k, v in item.items():
                        if k != "name":
                            detail[k] = v
                    skill.detail_json = json.dumps(detail, ensure_ascii=False)
                    if item.get("influence_score") is not None:
                        skill.influence_score = clamp_int(
                            item.get("influence_score"), minimum=0, maximum=100, default=0
                        )
                    if item.get("is_active") is not None:
                        skill.is_active = bool(item.get("is_active"))
                    else:
                        skill.is_active = True
                    introduced_chapter = coerce_int(
                        item.get("introduced_chapter") or item.get("source_chapter_no"),
                        default=int(skill.introduced_chapter or 0),
                    )
                    source_chapter_no = coerce_int(
                        item.get("source_chapter_no"),
                        default=int(skill.source_chapter_no or introduced_chapter),
                    )
                    last_used_chapter = coerce_int(
                        item.get("last_used_chapter"),
                        default=int(skill.last_used_chapter or 0),
                    )
                    last_seen_chapter_no = coerce_int(
                        item.get("last_seen_chapter_no"),
                        default=max(
                            latest_delta_chapter_no,
                            int(skill.last_seen_chapter_no or 0),
                            last_used_chapter,
                            introduced_chapter,
                        ),
                    )
                    expired_raw = item.get("expired_chapter")
                    skill.introduced_chapter = introduced_chapter
                    skill.source_chapter_no = source_chapter_no
                    skill.last_used_chapter = last_used_chapter
                    skill.last_seen_chapter_no = last_seen_chapter_no
                    skill.expired_chapter = (
                        coerce_int(expired_raw, default=0)
                        if expired_raw is not None
                        else None
                    )
                    explicit_lifecycle = (
                        str(item.get("lifecycle_state") or "").strip() or None
                    )
                    skill.lifecycle_state = infer_lifecycle_state(
                        is_active=bool(skill.is_active),
                        introduced_chapter=int(skill.introduced_chapter or 0),
                        last_seen_chapter=int(skill.last_seen_chapter_no or 0),
                        expired_chapter=skill.expired_chapter,
                        explicit=explicit_lifecycle,
                    )
                skill.memory_version = memory_version
                stats["skills_updated"] += 1

        # 6b. 宠物 / 同伴
        pets_changed = delta.get("pets_changed")
        if isinstance(pets_changed, dict):
            added = pets_changed.get("added") or []
            updated = pets_changed.get("updated") or []
            removed = pets_changed.get("removed") or []

            removed_names: list[str] = []
            removed_short_ids: set[str] = set()
            for raw in removed:
                if isinstance(raw, dict):
                    name = str(raw.get("name") or "").strip()
                    rid = str(raw.get("id") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", rid):
                        removed_short_ids.add(rid)
                else:
                    name = str(raw or "").strip()
                    token = name.lower()
                    if re.fullmatch(r"[0-9a-f]{4}", token):
                        removed_short_ids.add(token)
                if name:
                    removed_names.append(name)
            if removed_short_ids:
                for row in db.query(NovelMemoryNormPet).filter(
                    NovelMemoryNormPet.novel_id == novel_id
                ).all():
                    n = str(getattr(row, "name", "") or "").strip()
                    if n and _short_id(n).lower() in removed_short_ids:
                        removed_names.append(n)
            if removed_names:
                removed_names = _dedupe_str_list(removed_names)
                db.query(NovelMemoryNormPet).filter(
                    NovelMemoryNormPet.novel_id == novel_id,
                    NovelMemoryNormPet.name.in_(removed_names),
                ).update(
                    {
                        NovelMemoryNormPet.is_active: False,
                        NovelMemoryNormPet.memory_version: memory_version,
                    },
                    synchronize_session=False,
                )

            for item in [*added, *updated]:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                else:
                    name = str(item or "").strip()
                if not name:
                    continue
                pet = db.query(NovelMemoryNormPet).filter(
                    NovelMemoryNormPet.novel_id == novel_id,
                    NovelMemoryNormPet.name == name,
                ).first()
                if not pet:
                    max_order = db.query(func.max(NovelMemoryNormPet.sort_order)).filter(
                        NovelMemoryNormPet.novel_id == novel_id
                    ).scalar() or 0
                    pet = NovelMemoryNormPet(
                        novel_id=novel_id,
                        name=name,
                        sort_order=max_order + 1,
                        memory_version=memory_version,
                    )
                    db.add(pet)
                if isinstance(item, dict):
                    detail = json.loads(pet.detail_json or "{}")
                    for k, v in item.items():
                        if k != "name":
                            detail[k] = v
                    pet.detail_json = json.dumps(detail, ensure_ascii=False)
                    if item.get("influence_score") is not None:
                        pet.influence_score = clamp_int(
                            item.get("influence_score"), minimum=0, maximum=100, default=0
                        )
                    if item.get("is_active") is not None:
                        pet.is_active = bool(item.get("is_active"))
                    else:
                        pet.is_active = True
                pet.memory_version = memory_version

        # 7. 更新 Outline (main_plot, forbidden_constraints 等)
        outline = db.get(NovelMemoryNormOutline, novel_id)
        if not outline:
            outline = NovelMemoryNormOutline(novel_id=novel_id)
            db.add(outline)
        
        fc_add = delta.get("forbidden_constraints_added", [])
        if isinstance(fc_add, list) and fc_add:
            fc = json.loads(outline.forbidden_constraints_json or "[]")
            if not isinstance(fc, list):
                fc = []
            fc = _dedupe_str_list(
                [
                    *fc,
                    *[str(x).strip() for x in fc_add if str(x).strip()],
                ]
            )
            outline.forbidden_constraints_json = json.dumps(fc, ensure_ascii=False)

        outline.memory_version = memory_version

        return stats

    def _merge_memory_delta(
        self,
        prev_memory_json: str,
        delta: dict[str, Any],
        replace_timeline: bool = False,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        prev_data = _safe_json_dict(prev_memory_json)
        data = dict(prev_data)
        stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
        }

        # 1. 时间线处理
        canonical_map: dict[int, dict[str, Any]] = {}
        for item in _canonical_entries_from_payload(prev_data):
            normalized = self._normalize_delta_entry(item)
            if normalized is not None:
                canonical_map[normalized["chapter_no"]] = normalized

        incoming_entries = delta.get("canonical_entries")
        if isinstance(incoming_entries, list):
            for item in incoming_entries:
                normalized = self._normalize_delta_entry(item)
                if normalized is None:
                    continue
                chapter_no = normalized["chapter_no"]
                if replace_timeline:
                    # 刷新模式：直接覆盖该章节的时间线条目
                    canonical_map[chapter_no] = normalized
                else:
                    # 增量模式：合并
                    canonical_map[chapter_no] = self._merge_timeline_entry(
                        canonical_map.get(chapter_no, {"chapter_no": chapter_no}), normalized
                    )
                stats["canonical_entries"] += 1

        ordered_timeline = [canonical_map[k] for k in sorted(canonical_map.keys())]
        latest_timeline_chapter_no = (
            ordered_timeline[-1]["chapter_no"] if ordered_timeline else 0
        )

        # 2. 核心 ID 删除逻辑：IDS TO REMOVE
        ids_to_remove = set(delta.get("ids_to_remove") or [])

        def _normalize_plot_obj(raw: Any, *, chapter_no: int = 0) -> dict[str, Any] | None:
            if isinstance(raw, dict):
                body = str(raw.get("body") or raw.get("text") or "").strip()
                if not body:
                    return None
                iid = raw.get("id") or _short_id(body)
                return {
                    "id": iid,
                    "body": body,
                    "plot_type": normalize_plot_type(raw.get("plot_type")),
                    "priority": clamp_int(raw.get("priority"), minimum=0, maximum=100, default=0),
                    "estimated_duration": max(0, clamp_int(raw.get("estimated_duration"), minimum=0, maximum=999, default=0)),
                    "current_stage": str(raw.get("current_stage") or "").strip()[:500],
                    "resolve_when": str(raw.get("resolve_when") or "").strip()[:500],
                    "introduced_chapter": max(0, clamp_int(raw.get("introduced_chapter"), minimum=0, maximum=20000, default=chapter_no)),
                    "last_touched_chapter": max(0, clamp_int(raw.get("last_touched_chapter"), minimum=0, maximum=20000, default=chapter_no)),
                }
            body = str(raw or "").strip()
            if not body: return None
            return {
                "id": _short_id(body), "body": body, "plot_type": "Transient", "priority": 0, 
                "estimated_duration": 0, "current_stage": "", "resolve_when": "", 
                "introduced_chapter": chapter_no, "last_touched_chapter": chapter_no
            }

        def _merge_plot_state(base: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base or {})
            merged["id"] = incoming.get("id") or merged.get("id") or _short_id(incoming["body"])
            merged["body"] = incoming["body"]
            merged["plot_type"] = normalize_plot_type(incoming.get("plot_type") or merged.get("plot_type"))
            merged["priority"] = clamp_int(incoming.get("priority", merged.get("priority", 0)), minimum=0, maximum=100, default=0)
            merged["estimated_duration"] = max(0, clamp_int(incoming.get("estimated_duration", merged.get("estimated_duration", 0)), minimum=0, maximum=999, default=0))
            merged["current_stage"] = str(incoming.get("current_stage") or merged.get("current_stage") or "").strip()[:500]
            merged["resolve_when"] = str(incoming.get("resolve_when") or merged.get("resolve_when") or "").strip()[:500]
            introduced = max(0, clamp_int(merged.get("introduced_chapter") or incoming.get("introduced_chapter"), minimum=0, maximum=20000, default=0))
            if introduced <= 0: introduced = latest_timeline_chapter_no
            merged["introduced_chapter"] = introduced
            merged["last_touched_chapter"] = max(
                clamp_int(merged.get("last_touched_chapter"), minimum=0, maximum=20000, default=0),
                clamp_int(incoming.get("last_touched_chapter"), minimum=0, maximum=20000, default=latest_timeline_chapter_no)
            )
            return merged

        # 3. Open Plots 合并与清理
        plot_map: dict[str, dict[str, Any]] = {}
        prev_open_plots = prev_data.get("open_plots")
        if isinstance(prev_open_plots, list):
            for item in prev_open_plots:
                normalized_plot = _normalize_plot_obj(item)
                if normalized_plot: plot_map[normalized_plot["body"]] = normalized_plot
        
        # 移除 ID 在 ids_to_remove 中的项
        plot_keys_to_del = [k for k, v in plot_map.items() if v.get("id") in ids_to_remove]
        for k in plot_keys_to_del: plot_map.pop(k)

        raw_top_add = delta.get("open_plots_added", [])
        top_added_bodies = self._open_plot_bodies_from_mixed(raw_top_add if isinstance(raw_top_add, list) else [])
        for item in raw_top_add if isinstance(raw_top_add, list) else []:
            normalized_plot = _normalize_plot_obj(item, chapter_no=latest_timeline_chapter_no)
            if normalized_plot:
                plot_map[normalized_plot["body"]] = _merge_plot_state(plot_map.get(normalized_plot["body"]), normalized_plot)

        # 4. 角色更新 (ID 化，虽然角色通常按名匹配)
        characters_by_name: dict[str, dict[str, Any]] = {}
        prev_characters = prev_data.get("characters", [])
        if isinstance(prev_characters, list):
            for item in prev_characters:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        # 分配 ID
                        if "id" not in item: item["id"] = _short_id(name)
                        characters_by_name[name] = dict(item)
        
        # 人物遵循软下线，不在合并时直接删除
        for character in characters_by_name.values():
            if character.get("id") in ids_to_remove:
                character["is_active"] = False

        for bucket_key in ("characters_added", "characters_updated"):
            incoming_chars = delta.get(bucket_key)
            if isinstance(incoming_chars, list):
                for item in incoming_chars:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    base = characters_by_name.get(
                        name, {"name": name, "id": _short_id(name), "is_active": True}
                    )
                    for key in ("role", "status"):
                        val = str(item.get(key) or "").strip()
                        if val:
                            base[key] = val
                    traits = item.get("traits")
                    if isinstance(traits, list):
                        base["traits"] = _dedupe_str_list(traits)
                    elif "traits" not in base:
                        base["traits"] = []
                    if item.get("influence_score") is not None:
                        try:
                            base["influence_score"] = clamp_int(
                                item["influence_score"], minimum=0, maximum=100, default=0
                            )
                        except Exception:
                            pass
                    if item.get("is_active") is not None:
                        base["is_active"] = bool(item["is_active"])
                    elif _status_implies_inactive(item.get("status")):
                        base["is_active"] = False
                    characters_by_name[name] = base
                    stats["characters_updated"] += 1
        incoming_chars_inactivated = delta.get("characters_inactivated")
        if isinstance(incoming_chars_inactivated, list):
            for item in incoming_chars_inactivated:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                base = characters_by_name.get(
                    name, {"name": name, "id": _short_id(name), "is_active": False}
                )
                for key in ("role", "status"):
                    val = str(item.get(key) or "").strip()
                    if val:
                        base[key] = val
                traits = item.get("traits")
                if isinstance(traits, list):
                    base["traits"] = _dedupe_str_list(traits)
                elif "traits" not in base:
                    base["traits"] = []
                if item.get("influence_score") is not None:
                    try:
                        base["influence_score"] = clamp_int(
                            item["influence_score"], minimum=0, maximum=100, default=0
                        )
                    except Exception:
                        pass
                base["is_active"] = False
                characters_by_name[name] = base
                stats["characters_updated"] += 1
        data["characters"] = list(characters_by_name.values())

        # 5. Forbidden Constraints (ID 化)
        fc_map: dict[str, dict[str, Any]] = {}
        fc_prev = prev_data.get("forbidden_constraints", [])
        if isinstance(fc_prev, list):
            for x in fc_prev:
                if isinstance(x, dict):
                    body = str(x.get("body") or "").strip()
                    iid = x.get("id") or _short_id(body)
                    if body: fc_map[iid] = {"body": body, "id": iid}
                else:
                    body = str(x).strip()
                    if body:
                        iid = _short_id(body)
                        fc_map[iid] = {"body": body, "id": iid}
        
        # 移除
        for iid in ids_to_remove: fc_map.pop(iid, None)
        
        # 新增
        fc_add = delta.get("forbidden_constraints_added", [])
        if isinstance(fc_add, list):
            for x in fc_add:
                body = str(x).strip()
                if body:
                    iid = _short_id(body)
                    fc_map[iid] = {"body": body, "id": iid}
        data["forbidden_constraints"] = list(fc_map.values())

        # 6. Relations (ID 化)
        relation_map: dict[str, dict[str, Any]] = {}
        prev_relations = prev_data.get("relations", [])
        if isinstance(prev_relations, list):
            for item in prev_relations:
                if not isinstance(item, dict): continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                if src and dst:
                    iid = item.get("id") or _relation_identity(src, dst)
                    relation_map[iid] = {
                        "id": iid, "from": src, "to": dst, 
                        "relation": str(item.get("relation") or "").strip(),
                        "is_active": True if item.get("is_active") is None else bool(item.get("is_active")),
                    }
        # 关系遵循软失效，不在合并时直接删除
        for relation in relation_map.values():
            if relation.get("id") in ids_to_remove:
                relation["is_active"] = False
        # 更新/新增
        for bucket_key in ("relations_added", "relations_updated", "relations_changed"):
            incoming_relations = delta.get(bucket_key)
            if isinstance(incoming_relations, list):
                for item in incoming_relations:
                    if not isinstance(item, dict):
                        continue
                    src = str(item.get("from") or "").strip()
                    dst = str(item.get("to") or "").strip()
                    relation = str(item.get("relation") or "").strip()
                    if src and dst:
                        iid = item.get("id") or _relation_identity(src, dst)
                        base = relation_map.get(
                            iid,
                            {"id": iid, "from": src, "to": dst, "relation": relation, "is_active": True},
                        )
                        if relation:
                            base["relation"] = relation
                        if item.get("is_active") is not None:
                            base["is_active"] = bool(item.get("is_active"))
                        else:
                            base["is_active"] = True
                        relation_map[iid] = base
        incoming_relations_inactivated = delta.get("relations_inactivated")
        if isinstance(incoming_relations_inactivated, list):
            for item in incoming_relations_inactivated:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                relation = str(item.get("relation") or "").strip()
                if src and dst:
                    iid = item.get("id") or _relation_identity(src, dst)
                    base = relation_map.get(
                        iid,
                        {"id": iid, "from": src, "to": dst, "relation": relation, "is_active": False},
                    )
                    if relation:
                        base["relation"] = relation
                    base["is_active"] = False
                    relation_map[iid] = base
        data["relations"] = list(relation_map.values())

        # 7. Generic Collections: Inventory, Skills, Pets (ID 化)
        def _merge_named_collection_with_id(key: str, changed_key: str):
            prev_items = prev_data.get(key, [])
            changed = delta.get(changed_key)
            item_map: dict[str, dict[str, Any]] = {}
            if isinstance(prev_items, list):
                for x in prev_items:
                    if isinstance(x, dict):
                        name = str(x.get("name") or x.get("label") or "").strip()
                        iid = x.get("id") or _short_id(name)
                        if name: item_map[iid] = {**x, "id": iid, "name": name}
            
            # 移除
            for iid in ids_to_remove: item_map.pop(iid, None)
            # LLM 手动指定的删除
            if isinstance(changed, dict):
                removed = changed.get("removed", [])
                if isinstance(removed, list):
                    for r in removed:
                        rid = str(r).strip()
                        item_map.pop(rid, None)
                        # 兜底：按名删
                        to_del = [k for k, v in item_map.items() if v.get("name") == rid]
                        for k in to_del: item_map.pop(k)

                # 更新/新增
                for field in ("added", "updated"):
                    bucket = changed.get(field)
                    if isinstance(bucket, list):
                        for raw in bucket:
                            if not isinstance(raw, dict): continue
                            name = str(raw.get("name") or raw.get("label") or "").strip()
                            if not name: continue
                            iid = raw.get("id") or _short_id(name)
                            base = item_map.get(iid, {"id": iid, "name": name, "is_active": True})
                            for k, v in raw.items():
                                if k in ("id", "name"): continue
                                base[k] = v
                            item_map[iid] = base
                data[key] = list(item_map.values())

        _merge_named_collection_with_id("inventory", "inventory_changed")
        _merge_named_collection_with_id("skills", "skills_changed")
        _merge_named_collection_with_id("pets", "pets_changed")

        # 8. 移除冗余模块
        for old_key in ("notes", "world_rules", "arcs", "themes", "timeline_archive_summary", "main_plot_history"):
            data.pop(old_key, None)

        if not isinstance(data.get("main_plot"), str) or not str(data.get("main_plot")).strip():
            data["main_plot"] = str(prev_data.get("main_plot") or "")

        data["canonical_timeline"] = ordered_timeline
        data["canonical_timeline_hot"] = []
        data["canonical_timeline_cold"] = []

        return data, stats

    def _postprocess_memory_layers(
        self, payload_json: str, prev_memory_json: str = "{}"
    ) -> str:
        data = _safe_json_dict(payload_json)
        prev_data = _safe_json_dict(prev_memory_json)
        if not data: return payload_json

        # 确保关键列表存在
        for key in ("characters", "relations", "inventory", "skills", "pets", "open_plots", "forbidden_constraints"):
            if not isinstance(data.get(key), list):
                data[key] = prev_data.get(key, []) if isinstance(prev_data.get(key), list) else []
        
        if not isinstance(data.get("main_plot"), str):
            data["main_plot"] = str(prev_data.get("main_plot") or "")

        # 移除已弃用字段
        for old_key in ("notes", "world_rules", "arcs", "themes", "timeline_archive_summary", "main_plot_history"):
            data.pop(old_key, None)

        # 确保 open_plots 都有 ID
        if isinstance(data.get("open_plots"), list):
            for p in data["open_plots"]:
                if isinstance(p, dict) and "id" not in p:
                    p["id"] = _short_id(str(p.get("body") or ""))

        full_entries = _canonical_entries_from_payload(data)
        normalized_entries: list[dict[str, Any]] = []
        for item in full_entries:
            normalized = self._normalize_delta_entry(item)
            if normalized: normalized_entries.append(normalized)
        normalized_entries.sort(key=lambda x: x["chapter_no"])

        hot_n = max(1, int(settings.novel_timeline_hot_n))
        hot = normalized_entries[-hot_n:] if len(normalized_entries) > hot_n else normalized_entries
        cold = normalized_entries[:-hot_n] if len(normalized_entries) > hot_n else []

        data["canonical_timeline_hot"] = hot
        data["canonical_timeline_cold"] = cold
        data["canonical_timeline"] = hot
        return json.dumps(data, ensure_ascii=False)


    def _validate_memory_with_db(
        self,
        db: Session,
        novel_id: str,
        delta: dict[str, Any],
        candidate_json: str,
    ) -> dict[str, list[str]]:
        """
        利用数据库当前状态，校验 LLM 返回的增量是否合法，防止幻觉导致的误删除或冲突。
        """
        result = self._empty_validation_result()

        # 1. 时间线章节号去重（自动修复，不再报错阻断）
        incoming_entries = delta.get("canonical_entries")
        if isinstance(incoming_entries, list):
            seen_nos: set[int] = set()
            for item in incoming_entries:
                cn = self._extract_chapter_no(item)
                if cn is None:
                    continue
                if cn in seen_nos:
                    # 自动去重，记录警告但不阻断
                    result["warnings"].append(
                        f"检测到重复章节号 {cn}，已自动合并"
                    )
                seen_nos.add(cn)

        # 2. 校验角色更新
        incoming_chars = delta.get("characters_updated")
        if isinstance(incoming_chars, list):
            for item in incoming_chars:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                # 如果只有 role/status 更新，检查角色是否存在
                # 如果是全新的角色（没有在 DB 中），这通常意味着模型在“更新”一个它认为存在的但实际不存在的角色
                # 但在这里我们允许 Upsert，所以也许不需要报错，除非它是误删了其他信息
            
            # 自动去重角色更新
            seen_char_names: set[str] = set()
            unique_chars: list[dict[str, Any]] = []
            for item in incoming_chars:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                if name in seen_char_names:
                    result["warnings"].append(f"角色 '{name}' 重复更新，已合并")
                    for idx, existing in enumerate(unique_chars):
                        if str(existing.get("name", "")).strip() == name:
                            unique_chars[idx] = {**existing, **item}
                            break
                else:
                    seen_char_names.add(name)
                    unique_chars.append(item)
            
            if unique_chars:
                delta["characters_updated"] = unique_chars

        return self._merge_validation_results(result)

    @staticmethod
    def _empty_validation_result() -> dict[str, list[str]]:
        return {
            "blocking_errors": [],
            "warnings": [],
            "auto_pass_notes": [],
        }

    @staticmethod
    def _merge_validation_results(*parts: dict[str, list[str]]) -> dict[str, list[str]]:
        merged = NovelLLMService._empty_validation_result()
        for part in parts:
            if not isinstance(part, dict):
                continue
            for key in merged:
                vals = part.get(key)
                if isinstance(vals, list):
                    merged[key].extend(str(v).strip() for v in vals if str(v).strip())
        for key in merged:
            merged[key] = _dedupe_str_list(merged[key])
        return merged

    def _classify_removed_open_plots(
        self,
        db: Session | None,
        novel_id: str | None,
        removed_open: set[str],
    ) -> dict[str, list[str]]:
        result = self._empty_validation_result()
        if not removed_open:
            return result
        if not db or not novel_id:
            result["warnings"].append(
                "活跃 open_plots 被无理由删除：" + "；".join(sorted(removed_open)[:5])
            )
            return result

        latest_chapter_no = (
            db.query(func.max(NovelMemoryNormChapter.chapter_no))
            .filter(NovelMemoryNormChapter.novel_id == novel_id)
            .scalar()
            or 0
        )
        rows = (
            db.query(NovelMemoryNormPlot)
            .filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.body.in_(list(removed_open)),
            )
            .all()
        )
        by_body = {str(row.body or "").strip(): row for row in rows}
        for body in sorted(removed_open):
            row = by_body.get(body)
            if row is None:
                result["warnings"].append(f"活跃 open_plots 疑似被删除：{body}")
                continue
            plot_type = str(getattr(row, "plot_type", "Transient") or "Transient")
            priority = int(getattr(row, "priority", 0) or 0)
            estimated_duration = int(getattr(row, "estimated_duration", 0) or 0)
            touched = max(
                int(getattr(row, "last_touched_chapter", 0) or 0),
                int(getattr(row, "introduced_chapter", 0) or 0),
            )
            is_stale = (
                estimated_duration > 0
                and touched > 0
                and latest_chapter_no > 0
                and (latest_chapter_no - touched)
                > (estimated_duration + settings.novel_open_plot_stale_grace_chapters)
            )
            can_auto_pass = (
                plot_type.lower() == "transient"
                and priority <= 3
                and (is_stale or (0 < estimated_duration <= 3))
            )
            if can_auto_pass:
                note = (
                    f"自动放行：低风险待收束线可移出热层：{body}"
                    f"（plot_type={plot_type}，priority={priority}，estimated_duration={estimated_duration}"
                )
                if is_stale:
                    note += "，已 stale"
                note += "）"
                result["auto_pass_notes"].append(note)
            else:
                result["warnings"].append(
                    f"活跃 open_plots 疑似被删除：{body}"
                    f"（plot_type={plot_type}，priority={priority}，estimated_duration={estimated_duration}）"
                )
        return self._merge_validation_results(result)

    def _classify_removed_characters(
        self,
        db: Session | None,
        novel_id: str | None,
        missing_chars: set[str],
    ) -> dict[str, list[str]]:
        result = self._empty_validation_result()
        if not missing_chars:
            return result
        if not db or not novel_id:
            result["warnings"].append("已有角色被删除：" + "；".join(sorted(missing_chars)[:5]))
            return result

        rows = (
            db.query(NovelMemoryNormCharacter)
            .filter(
                NovelMemoryNormCharacter.novel_id == novel_id,
                NovelMemoryNormCharacter.name.in_(list(missing_chars)),
            )
            .all()
        )
        by_name = {str(row.name or "").strip(): row for row in rows}
        for name in sorted(missing_chars):
            row = by_name.get(name)
            if row is None:
                result["warnings"].append(f"已有角色疑似被删除：{name}")
                continue
            influence_score = int(getattr(row, "influence_score", 0) or 0)
            is_active = bool(getattr(row, "is_active", True))
            if (not is_active) or influence_score <= 2:
                result["auto_pass_notes"].append(
                    f"自动放行：低影响或已退场角色可从热层移出：{name}"
                    f"（影响力={influence_score}，{'活跃' if is_active else '已退场'}）"
                )
            else:
                result["warnings"].append(
                    f"已有角色疑似被删除：{name}"
                    f"（影响力={influence_score}，{'活跃' if is_active else '已退场'}）"
                )
        return self._merge_validation_results(result)

    def _validate_memory_payload(
        self,
        candidate_json: str,
        prev_memory_json: str,
        *,
        delta: dict[str, Any] | None = None,
        db: Session | None = None,
        novel_id: str | None = None,
    ) -> dict[str, list[str]]:
        data = _safe_json_dict(candidate_json)
        prev_data = _safe_json_dict(prev_memory_json)
        result = self._empty_validation_result()
        if not data:
            result["blocking_errors"].append("候选记忆不是合法 JSON 对象")
            return result

        for key in ("characters", "relations", "inventory", "skills", "pets", "open_plots"):
            if not isinstance(data.get(key), list):
                result["blocking_errors"].append(f"{key} 必须为数组")
        for key in ("world_rules", "arcs", "themes", "notes", "timeline_archive_summary"):
            if key in data and not isinstance(data.get(key), list):
                result["blocking_errors"].append(f"{key} 必须为数组")
        if "main_plot" in data and not isinstance(data.get("main_plot"), str):
            result["blocking_errors"].append("main_plot 必须为字符串")

        entries = _canonical_entries_from_payload(data)
        last_no = 0
        seen: set[int] = set()
        for entry in entries:
            normalized = self._normalize_delta_entry(entry)
            if normalized is None:
                result["blocking_errors"].append("canonical_timeline 存在非法条目")
                continue
            chapter_no = normalized["chapter_no"]
            if chapter_no in seen:
                result["blocking_errors"].append(f"canonical_timeline 第 {chapter_no} 章重复")
            if chapter_no < last_no:
                result["blocking_errors"].append("canonical_timeline 章节号必须递增")
            seen.add(chapter_no)
            last_no = max(last_no, chapter_no)

        prev_open = set(self._open_plot_bodies_from_mixed(prev_data.get("open_plots", [])))
        new_open = set(self._open_plot_bodies_from_mixed(data.get("open_plots", [])))
        removed_open = prev_open - new_open
        resolved = set()
        for entry in entries:
            if isinstance(entry, dict):
                resolved.update(
                    _dedupe_str_list(
                        NovelLLMService._open_plot_bodies_from_mixed(entry.get("open_plots_resolved"))
                    )
                )
        if delta:
            resolved.update(
                _dedupe_str_list(
                    NovelLLMService._open_plot_bodies_from_mixed(delta.get("open_plots_resolved"))
                )
            )
        unexpected_removed = removed_open - resolved
        if unexpected_removed:
            result = self._merge_validation_results(
                result,
                self._classify_removed_open_plots(db, novel_id, unexpected_removed),
            )

        # 不再校验 open_plots_resolved 是否落在「历史激活池」内，避免表述微差导致阻断；格式与非空由 JSON 结构保证。

        prev_chars = {
            str(item.get("name") or "").strip()
            for item in prev_data.get("characters", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        new_chars = {
            str(item.get("name") or "").strip()
            for item in data.get("characters", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        missing_chars = prev_chars - new_chars
        if missing_chars:
            result = self._merge_validation_results(
                result,
                self._classify_removed_characters(db, novel_id, missing_chars),
            )

        return self._merge_validation_results(result)

    @staticmethod
    def _get_latest_memory_version(db: Session, novel_id: str) -> int:
        return db.query(func.max(NovelMemory.version)).filter(
            NovelMemory.novel_id == novel_id
        ).scalar() or 0

    async def _apply_memory_delta_batch(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        skip_snapshot: bool = False,
    ) -> dict[str, Any]:
        router = self._router(db=db)
        raw = await self._chat_text_with_timeout_retry(
            router=router,
            operation="memory_refresh",
            novel_id=novel.id,
            messages=self._memory_delta_messages(novel, chapters_summary, prev_memory, db=db if isinstance(db, Session) else None),
            temperature=0.2,
            web_search=self._novel_web_search(db, flow="memory_refresh"),
            timeout=settings.novel_memory_refresh_batch_timeout,
            max_tokens=settings.novel_memory_delta_max_tokens,
            response_format={"type": "json_object"},
            **self._bill_kw(db, self._billing_user_id),
        )
        delta = self._parse_refresh_memory_response(raw)
        if not delta:
            logger.warning(
                "memory delta invalid json(async) | novel_id=%s provider=%s model=%s raw_preview=%r",
                novel.id,
                "ai302",
                router.model or "-",
                (raw or "")[:800],
            )
            delta = await self._repair_refresh_memory_response(
                router=router,
                raw=raw,
                db=db,
            )
        if delta:
            delta, supplemented_nos = self._supplement_missing_canonical_entries(
                delta, chapters_summary
            )
            if supplemented_nos:
                logger.warning(
                    "memory delta canonical supplemented(async) | novel_id=%s chapters=%s",
                    novel.id,
                    supplemented_nos,
                )
        if not delta:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": "{}",
                "errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "blocking_errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "warnings": [],
                "auto_pass_notes": [],
                "stats": {},
                "stage_status": {
                    "delta": "failed",
                    "validation": "skipped",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }
        
        # 1. 计算合并后的 JSON (用于校验和快照)
        merged, stats = self._merge_memory_delta(prev_memory, delta, replace_timeline=replace_timeline)
        candidate_json = self._postprocess_memory_layers(
            json.dumps(merged, ensure_ascii=False), prev_memory_json=prev_memory
        )
        
        # 2. 校验
        validation = self._validate_memory_payload(
            candidate_json,
            prev_memory,
            delta=delta,
            db=db if isinstance(db, Session) else None,
            novel_id=novel.id if db else None,
        )
        if db:
            db_validation = self._validate_memory_with_db(db, novel.id, delta, candidate_json)
            validation = self._merge_validation_results(validation, db_validation)

        blocking_errors = validation["blocking_errors"]
        warnings = validation["warnings"]
        auto_pass_notes = validation["auto_pass_notes"]

        if blocking_errors:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": candidate_json,
                "errors": blocking_errors,
                "blocking_errors": blocking_errors,
                "warnings": warnings,
                "auto_pass_notes": auto_pass_notes,
                "stats": stats,
                "delta": delta,
                "stage_status": {
                    "delta": "ok",
                    "validation": "blocked",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }

        # 3. 如果没有 blocking_errors 且有 db，则执行规范化表更新
        new_version = 0
        norm_status = "skipped"
        snapshot_status = "skipped" if skip_snapshot else "pending"
        if db and not blocking_errors:
            try:
                # 使用 Savepoint 保护事务，防止局部失败导致全局回滚（如章节审批状态丢失）
                with db.begin_nested():
                    new_version = self._get_latest_memory_version(db, novel.id) + 1
                    db_stats = self._upsert_normalized_memory_from_delta(
                        db,
                        novel.id,
                        delta,
                        new_version,
                        replace_timeline=replace_timeline,
                        chapters_summary=chapters_summary,
                    )
                    # 合并统计信息
                    for k, v in db_stats.items():
                        stats[k] = max(stats.get(k, 0), v)
                    norm_status = "ok"
                    
                    # 确保大纲表存在，防止 sync 时由于缺少 outline 行导致快照为空
                    from app.models.novel_memory_norm import NovelMemoryNormOutline
                    outline = db.get(NovelMemoryNormOutline, novel.id)
                    if not outline:
                        outline = NovelMemoryNormOutline(
                            novel_id=novel.id,
                            memory_version=new_version,
                            main_plot=novel.intro or "",
                        )
                        db.add(outline)
                    else:
                        outline.memory_version = new_version

                    # 真源为规范化表：快照由分表派生
                    if not skip_snapshot:
                        snap_ver = sync_json_snapshot_from_normalized(
                            db, novel.id, summary="规范化存储自动快照（batch/incremental）"
                        )
                        new_version = snap_ver
                        snapshot_status = "ok"
                    else:
                        snapshot_status = "skipped"
                
                # 显式 flush 确保状态可见，但由外部调用者（Router）负责最终 commit
                db.flush()
                
                if not skip_snapshot:
                    latest_row = (
                        db.query(NovelMemory)
                        .filter(NovelMemory.novel_id == novel.id)
                        .order_by(NovelMemory.version.desc())
                        .first()
                    )
                    if latest_row and latest_row.payload_json:
                        candidate_json = latest_row.payload_json
            except Exception as e:
                # 局部回滚 Savepoint，不影响外部事务（如章节审批状态）
                logger.exception("Failed to update normalized memory tables (savepoint rolled back): %s", e)
                return {
                    "ok": False,
                    "status": "failed",
                    "payload_json": prev_memory,
                    "candidate_json": candidate_json,
                    "errors": [f"更新规范化表失败：{e}"],
                    "blocking_errors": [],
                    "warnings": warnings,
                    "auto_pass_notes": auto_pass_notes,
                    "stats": stats,
                    "delta": delta,
                    "error": f"更新规范化表失败: {e}",
                    "stage_status": {
                        "delta": "ok",
                        "validation": "ok",
                        "norm": "failed",
                        "snapshot": "failed" if not skip_snapshot else "skipped",
                    },
                }
        
        return {
            "ok": True,
            "status": "warning" if warnings else "ok",
            "payload_json": candidate_json,
            "candidate_json": candidate_json,
            "errors": [],
            "blocking_errors": [],
            "warnings": warnings,
            "auto_pass_notes": auto_pass_notes,
            "stats": stats,
            "delta": delta,
            "version": new_version,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if warnings else "ok",
                "norm": norm_status,
                "snapshot": snapshot_status,
            },
        }

    def _apply_memory_delta_batch_sync(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        skip_snapshot: bool = False,
    ) -> dict[str, Any]:
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="memory_refresh",
            novel_id=novel.id,
            messages=self._memory_delta_messages(novel, chapters_summary, prev_memory, db=db if isinstance(db, Session) else None),
            temperature=0.2,
            timeout=settings.novel_memory_refresh_batch_timeout,
            web_search=self._novel_web_search(db, flow="memory_refresh"),
            max_tokens=settings.novel_memory_delta_max_tokens,
            response_format={"type": "json_object"},
            **self._bill_kw(db, self._billing_user_id),
        )
        delta = self._parse_refresh_memory_response(raw)
        if not delta:
            logger.warning(
                "memory delta invalid json(sync) | novel_id=%s provider=%s model=%s raw_preview=%r",
                novel.id,
                "ai302",
                router.model or "-",
                (raw or "")[:800],
            )
            delta = self._repair_refresh_memory_response_sync(
                router=router,
                raw=raw,
                db=db,
            )
        if delta:
            delta, supplemented_nos = self._supplement_missing_canonical_entries(
                delta, chapters_summary
            )
            if supplemented_nos:
                logger.warning(
                    "memory delta canonical supplemented(sync) | novel_id=%s chapters=%s",
                    novel.id,
                    supplemented_nos,
                )
        if not delta:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": "{}",
                "errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "blocking_errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "warnings": [],
                "auto_pass_notes": [],
                "stats": {},
                "stage_status": {
                    "delta": "failed",
                    "validation": "skipped",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }
        
        # 1. 计算合并后的 JSON (用于校验和快照)
        merged, stats = self._merge_memory_delta(prev_memory, delta, replace_timeline=replace_timeline)
        candidate_json = self._postprocess_memory_layers(
            json.dumps(merged, ensure_ascii=False), prev_memory_json=prev_memory
        )
        
        # 2. 校验
        validation = self._validate_memory_payload(
            candidate_json,
            prev_memory,
            delta=delta,
            db=db if isinstance(db, Session) else None,
            novel_id=novel.id if db else None,
        )
        if db:
            db_validation = self._validate_memory_with_db(db, novel.id, delta, candidate_json)
            validation = self._merge_validation_results(validation, db_validation)

        blocking_errors = validation["blocking_errors"]
        warnings = validation["warnings"]
        auto_pass_notes = validation["auto_pass_notes"]

        if blocking_errors:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": candidate_json,
                "errors": blocking_errors,
                "blocking_errors": blocking_errors,
                "warnings": warnings,
                "auto_pass_notes": auto_pass_notes,
                "stats": stats,
                "delta": delta,
                "stage_status": {
                    "delta": "ok",
                    "validation": "blocked",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }

        # 3. 如果没有 blocking_errors 且有 db，则执行规范化表更新
        new_version = 0
        norm_status = "skipped"
        snapshot_status = "skipped" if skip_snapshot else "pending"
        if db and not blocking_errors:
            try:
                with db.begin_nested():
                    new_version = self._get_latest_memory_version(db, novel.id) + 1
                    db_stats = self._upsert_normalized_memory_from_delta(
                        db,
                        novel.id,
                        delta,
                        new_version,
                        replace_timeline=replace_timeline,
                        chapters_summary=chapters_summary,
                    )
                    # 合并统计信息
                    for k, v in db_stats.items():
                        stats[k] = max(stats.get(k, 0), v)
                    norm_status = "ok"
                    
                    # 确保大纲表存在
                    from app.models.novel_memory_norm import NovelMemoryNormOutline
                    outline = db.get(NovelMemoryNormOutline, novel.id)
                    if not outline:
                        outline = NovelMemoryNormOutline(
                            novel_id=novel.id,
                            memory_version=new_version,
                            main_plot=novel.intro or "",
                        )
                        db.add(outline)
                    else:
                        outline.memory_version = new_version

                    if not skip_snapshot:
                        snap_ver = sync_json_snapshot_from_normalized(
                            db, novel.id, summary="规范化存储自动快照（batch_sync/incremental）"
                        )
                        new_version = snap_ver
                        snapshot_status = "ok"
                    else:
                        snapshot_status = "skipped"
                
                db.flush()
                
                if not skip_snapshot:
                    latest_row = (
                        db.query(NovelMemory)
                        .filter(NovelMemory.novel_id == novel.id)
                        .order_by(NovelMemory.version.desc())
                        .first()
                    )
                    if latest_row and latest_row.payload_json:
                        candidate_json = latest_row.payload_json
            except Exception as e:
                logger.exception("Failed to update normalized memory tables (sync savepoint): %s", e)
                return {
                    "ok": False,
                    "status": "failed",
                    "error": f"更新规范化表失败: {e}",
                    "payload_json": prev_memory,
                    "candidate_json": candidate_json,
                    "errors": [f"更新规范化表失败：{e}"],
                    "blocking_errors": [],
                    "warnings": warnings,
                    "auto_pass_notes": auto_pass_notes,
                    "stats": stats,
                    "delta": delta,
                    "stage_status": {
                        "delta": "ok",
                        "validation": "ok",
                        "norm": "failed",
                        "snapshot": "failed" if not skip_snapshot else "skipped",
                    },
                }
        
        return {
            "ok": True,
            "status": "warning" if warnings else "ok",
            "payload_json": candidate_json,
            "candidate_json": candidate_json,
            "errors": [],
            "blocking_errors": [],
            "warnings": warnings,
            "auto_pass_notes": auto_pass_notes,
            "stats": stats,
            "delta": delta,
            "version": new_version,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if warnings else "ok",
                "norm": norm_status,
                "snapshot": snapshot_status,
            },
        }

    async def refresh_memory_from_chapters(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """刷新记忆，采用增量抽取 + 代码合并。"""
        batch_chars = settings.novel_memory_refresh_batch_chars
        summary_len = len(chapters_summary or "")
        logger.info(
            "refresh_memory start | summary_len=%d batch_chars=%d",
            summary_len,
            batch_chars,
        )
        current_memory = prev_memory
        total_stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
        }
        collected_warnings: list[str] = []
        collected_auto_pass_notes: list[str] = []
        batch_num = 0
        pos = 0
        while pos < summary_len:
            batch_num += 1
            end = summary_len if batch_chars <= 0 else min(pos + batch_chars, summary_len)
            if batch_chars > 0 and end < summary_len:
                boundary = chapters_summary.rfind("\n\n第", pos, end)
                if boundary > pos + batch_chars // 2:
                    end = boundary
            batch_summary = chapters_summary[pos:end].strip()
            if not batch_summary:
                pos = end
                continue
            
            # 解析该批次包含的章节号，用于进度显示
            chapter_nos = sorted([int(n) for n in re.findall(r"第(\d+)章", batch_summary)])
            ch_info = f"第 {chapter_nos[0]}-{chapter_nos[-1]} 章" if len(chapter_nos) > 1 else (f"第 {chapter_nos[0]} 章" if chapter_nos else "未知章节")

            is_last_batch = (end >= summary_len)
            try:
                result = await self._apply_memory_delta_batch(
                    novel,
                    batch_summary,
                    current_memory,
                    db=db,
                    replace_timeline=replace_timeline,
                    skip_snapshot=not is_last_batch,
                )
                if not result["ok"]:
                    result["batch"] = batch_num
                    return result
                
                # 实时持久化：每批次成功后立即提交
                if db:
                    db.commit()
                    logger.info("refresh_memory (async) batch commit success | batch=%d | chapters=%s", batch_num, ch_info)
                    if progress_callback:
                        progress_callback(batch_num, ch_info, result.get("stats"))

                current_memory = result["payload_json"]
                collected_warnings.extend(_dedupe_str_list(result.get("warnings", [])))
                collected_auto_pass_notes.extend(_dedupe_str_list(result.get("auto_pass_notes", [])))
                for key in total_stats:
                    total_stats[key] += int(result.get("stats", {}).get(key, 0))
            except Exception as e:
                if db:
                    db.rollback()
                logger.exception("refresh_memory (async) batch failed | batch=%d", batch_num)
                return {"ok": False, "error": f"批次 {batch_num} ({ch_info}) 执行异常: {e}", "batch": batch_num}
            pos = end
        
        out: dict[str, Any] = {
            "ok": True,
            "status": "warning" if collected_warnings else "ok",
            "payload_json": current_memory,
            "candidate_json": current_memory,
            "errors": [],
            "blocking_errors": [],
            "warnings": _dedupe_str_list(collected_warnings),
            "auto_pass_notes": _dedupe_str_list(collected_auto_pass_notes),
            "stats": total_stats,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if collected_warnings else "ok",
                "norm": "ok" if db else "skipped",
                "snapshot": "ok" if db else "skipped",
            },
        }
        if db:
            out["version"] = self._get_latest_memory_version(db, novel.id)
        return out

    def refresh_memory_from_chapters_sync(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """同步版本的记忆刷新，采用增量抽取 + 代码合并。"""
        # 不再根据 MD5 跳过，确保每一章都经过 LLM 重新扫描提取
        active_summary = chapters_summary.strip()
        
        if not active_summary:
            return {
                "ok": True,
                "status": "ok",
                "payload_json": prev_memory,
                "candidate_json": prev_memory,
                "errors": [],
                "blocking_errors": [],
                "warnings": [],
                "auto_pass_notes": ["无需更新：章节摘要为空"],
                "stats": {},
            }

        batch_chars = settings.novel_memory_refresh_batch_chars
        summary_len = len(active_summary)
        current_memory = prev_memory
        total_stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
        }
        collected_warnings: list[str] = []
        collected_auto_pass_notes: list[str] = []
            
        batch_num = 0
        pos = 0
        while pos < summary_len:
            batch_num += 1
            end = summary_len if batch_chars <= 0 else min(pos + batch_chars, summary_len)
            if batch_chars > 0 and end < summary_len:
                # 寻找章节标题标记作为物理切分点，确保章节完整性
                boundary = active_summary.find("\n\n第", min(pos + batch_chars // 2, summary_len))
                if boundary != -1 and boundary < pos + batch_chars * 1.5:
                    end = boundary
            
            batch_summary = active_summary[pos:end].strip()
            if not batch_summary:
                pos = end
                continue
            
            # 解析该批次包含的章节号，用于进度显示
            chapter_nos = sorted([int(n) for n in re.findall(r"第(\d+)章", batch_summary)])
            ch_info = f"第 {chapter_nos[0]}-{chapter_nos[-1]} 章" if len(chapter_nos) > 1 else (f"第 {chapter_nos[0]} 章" if chapter_nos else "未知章节")

            # 如果还有下一批，则跳过快照生成，只更新规范化表
            is_last_batch = (end >= summary_len)
            try:
                result = self._apply_memory_delta_batch_sync(
                    novel,
                    batch_summary,
                    current_memory,
                    db=db,
                    replace_timeline=replace_timeline,
                    skip_snapshot=not is_last_batch,
                )
                if not result["ok"]:
                    result["batch"] = batch_num
                    return result
                
                # 实时持久化：每批次成功后立即提交
                if db:
                    db.commit()
                    logger.info("refresh_memory batch commit success | batch=%d | chapters=%s", batch_num, ch_info)
                    if progress_callback:
                        progress_callback(batch_num, ch_info, result.get("stats"))

                current_memory = result["payload_json"]
                collected_warnings.extend(_dedupe_str_list(result.get("warnings", [])))
                collected_auto_pass_notes.extend(_dedupe_str_list(result.get("auto_pass_notes", [])))
                for key in total_stats:
                    total_stats[key] += int(result.get("stats", {}).get(key, 0))
            except Exception as e:
                if db:
                    db.rollback()
                logger.exception("refresh_memory batch failed | batch=%d", batch_num)
                return {"ok": False, "error": f"批次 {batch_num} ({ch_info}) 执行异常: {e}", "batch": batch_num}
            
            pos = end
        
        out_sync: dict[str, Any] = {
            "ok": True,
            "status": "warning" if collected_warnings else "ok",
            "payload_json": current_memory,
            "candidate_json": current_memory,
            "errors": [],
            "blocking_errors": [],
            "warnings": _dedupe_str_list(collected_warnings),
            "auto_pass_notes": _dedupe_str_list(collected_auto_pass_notes),
            "stats": total_stats,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if collected_warnings else "ok",
                "norm": "ok" if db else "skipped",
                "snapshot": "ok" if db else "skipped",
            },
        }
        if db:
            out_sync["version"] = self._get_latest_memory_version(db, novel.id)
        return out_sync
        
        out_sync: dict[str, Any] = {
            "ok": True,
            "status": "warning" if collected_warnings else "ok",
            "payload_json": current_memory,
            "candidate_json": current_memory,
            "errors": [],
            "blocking_errors": [],
            "warnings": _dedupe_str_list(collected_warnings),
            "auto_pass_notes": _dedupe_str_list(collected_auto_pass_notes),
            "stats": total_stats,
        }
        if db:
            out_sync["version"] = self._get_latest_memory_version(db, novel.id)
        return out_sync

    def consolidate_memory_archive_sync(
        self,
        novel: Novel,
        db: Any,
    ) -> dict[str, Any]:
        """
        将较早章节的 key_facts 压缩并入 outline.timeline_archive_json，
        并裁剪过久章节的 key_facts，降低 token 与噪声。
        """
        novel_id = novel.id
        outline = db.get(NovelMemoryNormOutline, novel_id)
        if not outline:
            return {"ok": False, "reason": "no_outline"}
        hot_n = max(1, int(settings.novel_timeline_hot_n))
        rows = (
            db.query(NovelMemoryNormChapter)
            .filter(NovelMemoryNormChapter.novel_id == novel_id)
            .order_by(NovelMemoryNormChapter.chapter_no.asc())
            .all()
        )
        if len(rows) <= hot_n + 3:
            return {"ok": True, "skipped": True, "reason": "too_few_chapters"}
        max_no = max(r.chapter_no for r in rows)
        cutoff = max_no - hot_n
        old_rows = [r for r in rows if r.chapter_no <= cutoff]
        facts: list[str] = []
        for r in old_rows:
            kf = json.loads(r.key_facts_json or "[]")
            if isinstance(kf, list):
                facts.extend([str(x).strip() for x in kf if str(x).strip()])
        if not facts:
            return {"ok": True, "skipped": True, "reason": "no_facts"}
        irreversible = [fact for fact in facts if is_irreversible_fact(fact)]
        reversible = [fact for fact in facts if fact not in irreversible]
        facts = [*irreversible[:150], *reversible[:100]]
        router = self._router(db=db)
        sys = (
            "你是长篇连载编辑。将下列「早期章节关键事实」压缩为 3～12 条阶段性摘要短句，"
            "每条独立一行，不要编号，不要编造新事实，可合并同义表述。"
        )
        user = "\n".join(facts[:200])
        raw = router.chat_text_sync(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.25,
            web_search=False,
            timeout=180.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        bullets = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()][:16]
        arch = json.loads(outline.timeline_archive_json or "[]")
        if not isinstance(arch, list):
            arch = []
        merged = _dedupe_str_list([*arch, *bullets])[-48:]
        outline.timeline_archive_json = json.dumps(merged, ensure_ascii=False)
        trimmed = 0
        for r in old_rows:
            kf = json.loads(r.key_facts_json or "[]")
            if isinstance(kf, list) and len(kf) > 2:
                r.key_facts_json = json.dumps(kf[-2:], ensure_ascii=False)
                trimmed += 1
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        try:
            sync_json_snapshot_from_normalized(db, novel_id, summary="记忆压缩后同步快照")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "consolidate_memory_archive_sync: snapshot sync failed | novel_id=%s",
                novel_id,
            )
        return {
            "ok": True,
            "skipped": False,
            "archive_lines_added": len(bullets),
            "chapters_trimmed": trimmed,
        }

    def audit_chapter_against_constraints_sync(
        self,
        novel: Novel,
        chapter_text: str,
        db: Any,
    ) -> dict[str, Any]:
        """
        轻量 LLM 审计：正文是否违反规范化记忆中的 forbidden_constraints。
        """
        if not settings.novel_setting_audit_on_approve:
            return {"ok": True, "violations": [], "skipped": True}
        outline = db.get(NovelMemoryNormOutline, novel.id)
        if not outline:
            return {"ok": True, "violations": [], "skipped": True}
        try:
            fc = json.loads(getattr(outline, "forbidden_constraints_json", None) or "[]")
        except json.JSONDecodeError:
            fc = []
        if not isinstance(fc, list) or not fc:
            return {"ok": True, "violations": [], "skipped": True}
        router = self._router(db=db)
        sys = (
            "你是小说设定审计员。只输出一个 JSON 对象，不要 Markdown。"
            '格式：{"violations":["..."]}；violations 列出正文明确违反的禁止项，无则 []。'
        )
        user = (
            "【禁止项】\n"
            f"{json.dumps(fc, ensure_ascii=False)}\n\n"
            "【待审计正文】\n"
            f"{(chapter_text or '')[:14000]}"
        )
        raw = router.chat_text_sync(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.15,
            web_search=False,
            timeout=180.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = self._parse_refresh_memory_response(raw)
        v = parsed.get("violations") if isinstance(parsed, dict) else []
        if not isinstance(v, list):
            v = []
        violations = [str(x).strip() for x in v if str(x).strip()]
        return {"ok": len(violations) == 0, "violations": violations}

    async def propose_memory_update_from_chapter(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        chapter_title: str,
        chapter_text: str,
        prev_memory: str,
        db: Any = None,
    ) -> dict[str, Any]:
        chapter_blob = f"第{chapter_no}章《{chapter_title or f'第{chapter_no}章'}》\n{chapter_text}"
        return await self._apply_memory_delta_batch(novel, chapter_blob, prev_memory, db=db)

    def propose_memory_update_from_chapter_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        chapter_title: str,
        chapter_text: str,
        prev_memory: str,
        db: Any = None,
    ) -> dict[str, Any]:
        chapter_blob = f"第{chapter_no}章《{chapter_title or f'第{chapter_no}章'}》\n{chapter_text}"
        return self._apply_memory_delta_batch_sync(novel, chapter_blob, prev_memory, db=db)

    async def revise_chapter(
        self,
        novel: Novel,
        chapter: Chapter,
        memory_json: str,
        feedback_bodies: list[str],
        user_prompt: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return await router.chat_text(
            messages=self._budget_chapter_messages(
                _revise_chapter_messages(
                    novel, chapter, memory_json, feedback_bodies, user_prompt, db
                )
            ),
            temperature=0.65,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )

    def revise_chapter_sync(
        self,
        novel: Novel,
        chapter: Chapter,
        memory_json: str,
        feedback_bodies: list[str],
        user_prompt: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return router.chat_text_sync(
            messages=self._budget_chapter_messages(
                _revise_chapter_messages(
                    novel, chapter, memory_json, feedback_bodies, user_prompt, db
                )
            ),
            temperature=0.65,
            timeout=600.0,
            web_search=self._novel_web_search(db, flow="default"),
            **self._bill_kw(db, self._billing_user_id),
        )
