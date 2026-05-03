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
    "【语言风格】\n"
    "用自然的人类语言写作，像一个有经验的故事讲述者。\n"
    "- 禁止技术/学术黑话：不用说「熵增/锚点/临界点/坍缩/耦合/迭代/闭环/系统性/结构性/颗粒度/灰度/底层逻辑」这类词，换成具体描述。\n"
    "- 禁止空洞套话：不说「命运的齿轮开始转动」「时间仿佛在这一刻凝固」「空气中弥漫着不安的气息」「一切都在朝着不可预知的方向发展」。\n"
    "- 禁止抽象概括：不说「局势发生了变化」「矛盾进一步激化」「双方进行了博弈」，要写出具体是什么事、谁做了什么、后果如何。\n"
    "- 对话像真人：短句、口语、有情绪，不要逻辑严密的长篇独白。\n"
    "- 描写靠感官和动作：写「她攥紧拳头，指甲嵌进掌心」而不写「她情绪到达临界点」；写「他咬着牙，眼睛死死盯着前方」而不写「他完成了一次心理迭代」。"
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
    use_cold_recall: bool | None,
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
    # use_cold_recall: True=强制开启, False=强制关闭, None=自动(按章号阈值)
    effective_cold_recall = use_cold_recall
    if effective_cold_recall is None:
        effective_cold_recall = (
            settings.novel_cold_recall_auto_threshold > 0
            and chapter_no >= settings.novel_cold_recall_auto_threshold
        )
    if effective_cold_recall:
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
    use_cold_recall: bool | None = None,
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
            "【第1章强制要求：必须介绍背景】\n"
            "这是读者第一次接触本书。正文第一段（最迟不超过前三段）必须明确回答以下三个问题：\n"
            "1. 这是什么世界/时代/地方（哪怕只是一句话的暗示）\n"
            "2. 主角是谁，他现在在哪里、什么处境\n"
            "3. 有什么事情正在发生，或有什么危机/机会出现，导致故事必然推进\n"
            "禁止用「时间回到几小时前」「忽然有一天」「一切都要从那场变故说起」这种事后补叙方式引入背景；"
            "背景信息必须在场景推进中自然带出，不能用整段独立的环境描写来交代。\n"
            "如果本章有执行卡，仍必须在前三段内回答上述三个问题，执行卡不得覆盖此约束。"
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


