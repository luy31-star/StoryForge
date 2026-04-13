from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re

import httpx
from json_repair import loads as json_repair_loads
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

from app.core.config import settings
from app.core.database import SessionLocal
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.novel import Chapter, Novel, NovelMemory
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
from app.services.llm_router import LLMRouter
from app.services.novel_repo import (
    build_hot_memory_for_prompt,
    build_hot_memory_from_db,
    format_chapter_continuity_bridge_from_db,
    format_cold_recall_block,
    format_cold_recall_from_db,
    format_canonical_timeline_block,
    format_canonical_timeline_from_db,
    format_constraints_block,
    format_entity_recall_block,
    format_entity_recall_from_db,
    format_open_plots_block,
    format_open_plots_from_db,
    format_volume_event_summary,
    format_volume_progress_anchor,
    chapter_execution_rules_block,
    forbidden_future_arcs_block,
    outline_beat_hint,
    pacing_guard_block,
    process_chapter_suggestions_block,
    truncate_framework_json,
)
from app.services.runtime_llm_config import get_runtime_web_search_config
from app.services.novel_storage import load_reference_text_for_llm
from app.services.memory_schema import (
    clamp_int,
    dedupe_clean_strs,
    extract_aliases,
    is_irreversible_fact,
    normalize_plot_type,
)

logger = logging.getLogger(__name__)


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
        open_plots = format_open_plots_from_db(db, novel_id)
        canonical_timeline = format_canonical_timeline_from_db(db, novel_id, chapter_no)
        recall_query = "\n".join(
            [
                f"第{chapter_no}章",
                chapter_title_hint or "",
                chapter_plan_hint or "",
                open_plots or "",
            ]
        ).strip()
        entity_recall = format_entity_recall_from_db(
            db,
            novel_id,
            recall_query,
            max_items=max(2, settings.novel_memory_entity_recall_max_items),
        )
    else:
        hot_memory_json = build_hot_memory_for_prompt(
            memory_json,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
        )
        open_plots = format_open_plots_block(memory_json)
        canonical_timeline = format_canonical_timeline_block(memory_json, chapter_no)
        recall_query = "\n".join(
            [
                f"第{chapter_no}章",
                chapter_title_hint or "",
                chapter_plan_hint or "",
                open_plots or "",
            ]
        ).strip()
        entity_recall = format_entity_recall_block(
            memory_json,
            recall_query,
            max_items=max(2, settings.novel_memory_entity_recall_max_items),
        )

    blocks = [f"【当前结构化记忆（热层 JSON，仅注入最近关键状态）】\n{hot_memory_json}"]
    if canonical_timeline:
        blocks.append(canonical_timeline)
    if db and novel_id:
        cons = format_constraints_block(db, novel_id)
        if cons:
            blocks.append(cons)
        bridge = format_chapter_continuity_bridge_from_db(db, novel_id, chapter_no)
        if bridge:
            blocks.append(bridge)
    if open_plots:
        blocks.append(open_plots)
    if entity_recall:
        blocks.append(entity_recall)
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
    bible = novel.framework_markdown[:12000] if novel.framework_markdown else novel.background
    fj_block = truncate_framework_json(novel.framework_json or "", 8000)
    beat = outline_beat_hint(chapter_no, novel.framework_json or "")
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
    pacing_guard = pacing_guard_block(chapter_no, novel.framework_json or "", memory_json)
    future_arc_guard = forbidden_future_arcs_block(chapter_no, novel.framework_json or "")
    chapter_rules = chapter_execution_rules_block(chapter_no)
    process_suggest = process_chapter_suggestions_block(
        chapter_no, novel.framework_json or "", memory_json
    )

    # 新增：卷进度锚点和卷事件摘要
    volume_progress = ""
    volume_events = ""
    if db:
        try:
            volume_progress = format_volume_progress_anchor(
                db, novel.id, chapter_no, novel.framework_json or ""
            )
            volume_events = format_volume_event_summary(db, novel.id, chapter_no)
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
        "输出本章正文，不要输出元解释。"
        "输出格式强约束：第一行必须是“第N章《章名》”（N 必须与当前章节号一致），第二行空行后再写正文。"
        "正文必须符合中文网文阅读习惯：自然分段，段落长短有变化；对话、动作、心理、环境描写要穿插展开；"
        "必须使用完整标点，禁止输出一整坨几乎不分段、缺少标点或只有超长段落的文本。"
    )
    user_parts = [
        f"【世界观与框架摘要（Markdown）】\n{bible}",
        f"【框架 JSON（大纲/规则锚点，截断）】\n{fj_block}",
    ]
    user_parts.extend(memory_blocks)

    # 新增：卷级上下文（在摘录之前，提供整体视图）
    if volume_progress:
        user_parts.append(volume_progress)
    if volume_events:
        user_parts.append(volume_events)

    user_parts.append(
        f"【前文衔接摘录（含再前一章与上一章结尾，若有）】\n{continuity_excerpt or '（首章）'}"
    )
    if recent_full_context:
        user_parts.append(recent_full_context)
    user_parts.append(beat)
    user_parts.append(pacing_guard)
    if future_arc_guard:
        user_parts.append(future_arc_guard)
    user_parts.append(chapter_rules)
    user_parts.append(process_suggest)
    if chapter_plan_hint:
        user_parts.append(chapter_plan_hint)
    user_parts.append(
        f"请写第 {chapter_no} 章"
        f"{('，章标题建议：' + chapter_title_hint) if chapter_title_hint else ''}。"
    )
    target_words = getattr(novel, "chapter_target_words", 3000) or 3000
    words_min = int(target_words * 0.9)
    words_max = int(target_words * 1.2)
    
    user_parts.append(
        "【统一输出规则】\n"
        f"1) 第一行必须输出：第{chapter_no}章《章名》；\n"
        "2) 若未提供章标题建议，请先拟定一个贴合剧情的章名；\n"
        "3) 第二行留空一行，再开始正文。\n"
        f"4) 正文（不含标题行）目标体量约 {target_words} 汉字左右（建议在 {words_min}～{words_max} 汉字之间）；明显偏短视为不合格；"
        "用场景、对白与细节描写支撑篇幅，避免用一两段概括带过。\n"
        "5) 正文必须按自然阅读节奏分段：一般 2～6 句一段；场景切换、人物对话、动作变化、心理转折处要主动换段。\n"
        "6) 必须使用规范中文标点；禁止连续大段无标点铺陈，禁止整章只有少数几个超长段落。"
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
) -> list[dict[str, str]]:
    bible = novel.framework_markdown[:8000] if novel.framework_markdown else novel.background
    fj_block = truncate_framework_json(novel.framework_json or "", 6000)
    fb = "\n".join(f"- {b}" for b in feedback_bodies) or "（无）"
    sys = (
        "你是资深小说编辑。在保持世界观与人物一致的前提下，根据历史反馈意见与用户最新指令，"
        "对章节全文进行改写。框架 JSON 中的 world_rules 与已定设定不得被改稿推翻；只输出改写后的正文，"
        "不要前言、标题解释或 Markdown 围栏。"
        "改写后的正文必须符合中文阅读习惯：自然分段、标点完整、避免整页只有极少数超长段落。"
    )
    user = (
        f"【框架摘要（Markdown）】\n{bible}\n\n"
        f"【框架 JSON（锚点）】\n{fj_block}\n\n"
        f"【结构化记忆 JSON】\n{memory_json}\n\n"
        f"第 {chapter.chapter_no} 章《{chapter.title}》\n\n"
        f"【当前正文（正式稿）】\n{chapter.content}\n\n"
        f"【历史改进意见】\n{fb}\n\n"
        f"【用户本次指令】\n{user_prompt}"
    )
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
) -> list[dict[str, str]]:
    bible = novel.framework_markdown[:12000] if novel.framework_markdown else novel.background
    fj_block = truncate_framework_json(novel.framework_json or "", 6000)
    sys = (
        "你是小说一致性编辑。你的任务是对「待核对正文」做最小修改，解决设定漂移与前后因果断裂。"
        "严格遵守世界观与人物设定，必要时以【框架 JSON】与 world_rules 为准修正正文。"
        "canonical_timeline 作为规范因果链：若正文与时间线关键事实冲突，必须修正正文。"
        "输出只允许包含「修订后的正文内容本体」，不得输出标题、前言、解释或 Markdown 围栏。"
        "修订时需保留并优化正文可读性：自然分段、标点完整，避免出现一整坨不分段的文本。"
    )
    user = (
        f"【框架 Markdown】\n{bible}\n\n"
        f"【框架 JSON（锚点，截断）】\n{fj_block}\n\n"
        f"【结构化记忆 JSON（含 canonical_timeline 与 open_plots）】\n{memory_json}\n\n"
        f"【本章信息】第 {chapter_no} 章"
        f"{('，章标题建议：' + chapter_title_hint) if chapter_title_hint else ''}\n\n"
        f"【前文衔接摘录（含再前一章与上一章结尾）】\n{continuity_excerpt or '（首章）'}\n\n"
        f"【待核对正文】\n{chapter_text}\n\n"
        "【要求】\n"
        "1) 若发现与 world_rules/canonical_timeline 冲突，必须修正正文；不得只做说明。\n"
        "2) 允许做必要的因果补线、人物状态修正、伏笔承接与收束呈现，但不要大幅重写风格。\n"
        "3) 维持中文小说的正常排版与阅读节奏：对话、动作、场景切换、心理变化处应合理换段。\n"
        "4) 只输出最终正文。"
    )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
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
        bible = novel.framework_markdown[:12000] if novel.framework_markdown else novel.background
        fj_block = truncate_framework_json(novel.framework_json or "", 8000)
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
        bible = novel.framework_markdown[:12000] if novel.framework_markdown else novel.background
        fj_block = truncate_framework_json(novel.framework_json or "", 8000)
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

    async def generate_framework(self, novel: Novel, db: Any = None) -> tuple[str, str]:
        """返回 (markdown 正文, 尽力解析的 json 字符串)。"""
        router = self._router(db=db)
        ref = load_reference_text_for_llm(
            novel.reference_storage_key,
            novel.id,
            novel.reference_public_url,
        )
        sys = (
            "你是资深网文策划与世界观编辑。请输出两部分：1) 完整可读 Markdown 设定与大纲；"
            "2) 末尾单独一个 JSON 代码块，包含 "
            "world_rules, main_plot, arcs, characters[{name,role,traits,motivation}], themes 等键。\n"
            "【框架细化要求】\n"
            "- 世界观 (world_rules)：必须包含核心法则、力量/等级体系详情、特殊设定等。\n"
            "- 人物 (characters)：除了姓名和性格，必须提供“核心动机(motivation)”与各阶段目标。\n"
            "- 剧情分卷 (arcs)：每个 arc 必须进一步拆解为每 10~20 章为一个子阶段/关键事件（sub_arcs 或 key_events），并提供丰富的细节支撑，不能只有一个宽泛的概括。\n"
            "参考文本仅借鉴结构与文风，禁止抄袭原句。"
        )
        target_chapters = int(getattr(novel, "target_chapters", 0) or 0)
        volume_size = 50
        volume_n = (target_chapters + volume_size - 1) // volume_size if target_chapters > 0 else 0
        user = (
            f"书名：{novel.title}\n简介：{novel.intro}\n"
            f"背景设定：{novel.background}\n文风：{novel.style}\n"
            f"目标章节数：{target_chapters}\n"
            f"分卷规则：默认每卷 {volume_size} 章；总卷数约：{volume_n if volume_n else '（请按目标章节数自行估算）'}\n"
            '要求：剧情框架必须按卷拆分 arcs，每个 arc 需明确章节范围（from_chapter/to_chapter 或 chapters: "x-y"），'
            "并确保覆盖第1章到第N章（N=目标章节数）。\n\n"
            f"参考文本节选：\n{ref or '（无）'}"
        )
        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.6,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        json_part = "{}"
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                json.loads(m.group(1).strip())
                json_part = m.group(1).strip()
            except json.JSONDecodeError:
                json_part = json.dumps({"raw_framework_tail": text[-4000:]})
        return text, json_part

    async def regenerate_framework(
        self, novel: Novel, instruction: str, db: Any = None
    ) -> tuple[str, str]:
        router = self._router(db=db)
        ref = load_reference_text_for_llm(
            novel.reference_storage_key,
            novel.id,
            novel.reference_public_url,
        )
        sys = (
            "你是资深网文策划与世界观编辑。你将基于现有框架草案，并严格执行用户的自然语言修改指令，"
            "输出一版新的完整框架。\n"
            "请输出两部分：1) 完整可读 Markdown 设定与大纲；2) 末尾单独一个 JSON 代码块，包含 "
            "world_rules, main_plot, arcs, characters[{name,role,traits,motivation}], themes 等键。\n"
            "【框架细化要求】\n"
            "- 世界观 (world_rules)：必须包含核心法则、力量/等级体系详情、特殊设定等。\n"
            "- 人物 (characters)：除了姓名和性格，必须提供“核心动机(motivation)”与各阶段目标。\n"
            "- 剧情分卷 (arcs)：每个 arc 必须进一步拆解为每 10~20 章为一个子阶段/关键事件（sub_arcs 或 key_events），并提供丰富的细节支撑。\n"
            "参考文本仅借鉴结构与文风，禁止抄袭原句。"
        )
        fj_block = truncate_framework_json(novel.framework_json or "", 9000)
        md_block = (novel.framework_markdown or "")[:9000]
        user = (
            f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风：{novel.style}\n"
            f"目标章节数：{int(getattr(novel, 'target_chapters', 0) or 0)}\n\n"
            f"【当前框架 Markdown（截断）】\n{md_block or '（空）'}\n\n"
            f"【当前框架 JSON（截断）】\n{fj_block}\n\n"
            f"【用户修改指令】\n{(instruction or '').strip()}\n\n"
            f"参考文本节选：\n{ref or '（无）'}"
        )
        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.55,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        json_part = "{}"
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                json.loads(m.group(1).strip())
                json_part = m.group(1).strip()
            except json.JSONDecodeError:
                json_part = json.dumps({"raw_framework_tail": text[-4000:]})
        return text, json_part

    async def update_framework_characters(
        self, novel: Novel, characters: list[dict[str, Any]], db: Any = None
    ) -> tuple[str, str]:
        router = self._router(db=db)
        sys = (
            "你是资深网文策划与世界观编辑。你将基于现有框架草案，对人物设定做定向修订，"
            "并将修订同步反映到剧情大纲、人物关系与冲突设计中。\n"
            "请输出两部分：1) 完整可读 Markdown 设定与大纲；2) 末尾单独一个 JSON 代码块，包含 "
            "world_rules, main_plot, arcs, characters[{name,role,traits,motivation}], themes 等键。\n"
            "【框架细化要求】\n"
            "- 剧情分卷 (arcs)：每个 arc 必须拆解为每 10~20 章为一个子阶段/关键事件，避免宽泛。\n"
            "要求：人物列表以用户提供为准；需要时可以补充少量关键配角，但不得删除用户给出的主角。"
        )
        fj_block = truncate_framework_json(novel.framework_json or "", 9000)
        md_block = (novel.framework_markdown or "")[:9000]
        chars_text = json.dumps(characters or [], ensure_ascii=False)
        user = (
            f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风：{novel.style}\n"
            f"目标章节数：{int(getattr(novel, 'target_chapters', 0) or 0)}\n\n"
            f"【当前框架 Markdown（截断）】\n{md_block or '（空）'}\n\n"
            f"【当前框架 JSON（截断）】\n{fj_block}\n\n"
            f"【用户确认后的人物列表（JSON）】\n{chars_text}\n\n"
            "请将人物变更融入框架：\n"
            "- 若人物改名，需全局替换并保持一致\n"
            "- traits 要落到动机/行为模式/关系张力上\n"
            "- arcs 的关键节点应能体现主角成长与冲突升级"
        )
        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.55,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        json_part = "{}"
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                json.loads(m.group(1).strip())
                json_part = m.group(1).strip()
            except json.JSONDecodeError:
                json_part = json.dumps({"raw_framework_tail": text[-4000:]})
        return text, json_part

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
        db: Any = None,
    ) -> str:
        """
        生成“指定章节区间”的一批章计划，并返回严格 JSON 字符串。

        设计目的：
        - 前端/用户手动点击推进，每次只跑一批，成功即落库，避免整卷循环导致超时白跑。
        - 通过 prev_batch_context 传递上一批末两章关键信息，保证连续性。
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
            "【核心原则】剧情必须递进，禁止原地踏步式的重复！每一章都必须推动故事前进，不得重复已有的冲突模式。"
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
            '        \"progress_allowed\": string 或 string[],\n'
            '        \"must_not\": string[],\n'
            '        \"reserved_for_later\": [ { \"item\": string, \"not_before_chapter\": number } ]\n'
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
            f"{anti_repetition_block}"
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
            "【核心原则】剧情必须递进，禁止原地踏步式的重复！每一章都必须推动故事前进，不得重复已有的冲突模式。"
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
            '        \"progress_allowed\": string 或 string[],\n'
            '        \"must_not\": string[],\n'
            '        \"reserved_for_later\": [ { \"item\": string, \"not_before_chapter\": number } ]\n'
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
            "【防剧情重复硬约束 - 必须遵守】\n"
            "11) 自检：若前批次已出现「质疑-举证-被否定」的冲突循环，本批次不得再使用相同模式，必须让剧情进入新阶段（如：误会加深导致关系破裂、发现新证据、引入新人物、冲突升级等）；\n"
            "12) 禁止重复使用相同的心理活动描写模式：如「心里乱成一团」、「感到深深的疲惫」、「嘴角挂着冷笑」等固定句式，同一卷内不得在不同章重复出现；\n"
            "13) 禁止重复的环境描写开场：如「月光惨白」、「村里的狗吠」、「红木桌子」等，同一卷内各章的场景氛围必须有所变化（时间、天气、环境、氛围）；\n"
            "14) 每章的 conflict 必须与前3章的冲突有本质区别或递进，不得只是换汤不换药的重复争吵；自检：如果本章 conflict 只是前章的「再来一次」，必须重新设计；\n"
            "15) 人物情绪必须递进：如二舅对男主的态度应从信任→怀疑→动摇→愤怒→决裂逐步演变，不得在同一情绪层级反复横跳。\n"
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
            "【JSON 语法要求】字符串值内禁止直接换行；剧情文本避免未转义双引号。"
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
            '    "progress_allowed": string[],\n'
            '    "must_not": string[],\n'
            '    "reserved_for_later": [ { "item": string, "not_before_chapter": number } ]\n'
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
            beats = ch.get("beats", {})
            plot_summary = beats.get("plot_summary", "") if isinstance(beats, dict) else ""
            hook = beats.get("hook", "") if isinstance(beats, dict) else ""

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
                temperature=0.75,
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
                temperature=0.75,
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
                )
            ),
            temperature=settings.novel_consistency_check_temperature,
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
            "characters_updated": [],
            "relations_changed": [],
            "inventory_changed": {"added": [], "removed": []},
            "skills_changed": {"added": [], "updated": []},
            "pets_changed": {"added": [], "updated": []},
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

        # 2. 角色更新去重（按 name）
        raw_chars = normalized.get("characters_updated")
        if isinstance(raw_chars, list):
            unique_chars_map: dict[str, dict[str, Any]] = {}
            for item in raw_chars:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        unique_chars_map[name] = item
            normalized["characters_updated"] = list(unique_chars_map.values())

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
        }

        pets_changed = normalized.get("pets_changed")
        if not isinstance(pets_changed, dict):
            pets_changed = {}
        normalized["pets_changed"] = {
            "added": pets_changed.get("added") if isinstance(pets_changed.get("added"), list) else [],
            "updated": pets_changed.get("updated") if isinstance(pets_changed.get("updated"), list) else [],
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

    def _memory_delta_messages(
        self, novel: Novel, chapters_summary: str, prev_memory: str
    ) -> list[dict[str, str]]:
        fj = truncate_framework_json(novel.framework_json or "", 6000)
        compact_prev = build_hot_memory_for_prompt(
            prev_memory,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
        )
        prev_open_plots = format_open_plots_block(prev_memory)
        sys = (
            "你是小说记忆增量抽取器。"
            "你不能重写整份记忆，只能根据新章节内容输出“本批新增/变更了什么”。"
            "必须输出严格 JSON 对象，不要 Markdown，不要解释。"
            "若某字段没有变化，必须输出空数组或空对象。"
            "若本批输入里包含 1 章或多章内容，则 canonical_entries 必须为本批每一章各输出一条条目，不允许漏章。"
            "输出字段固定为："
            "facts_added[], facts_updated[], open_plots_added[], open_plots_resolved[],"
            "canonical_entries[], characters_updated[], relations_changed[],"
            "inventory_changed{added[],removed[]}, skills_changed{added[],updated[]},"
            "pets_changed{added[],updated[]}, conflicts_detected[],"
            "forbidden_constraints_added[], ids_to_remove[], entity_influence_updates[]。"
            "ids_to_remove[]：非常重要！当你判断某条【待收束线】已收束、某条【硬约束】已失效、或某项技能/道具已遗失/毁坏时，"
            "直接在 ids_to_remove 中填入该条目在下文提供的 4 位短 ID。不要通过文本匹配删除。\n"
            "【同类条目替换与升级规则（通用）】\n"
            "1. 状态/等级更新：若某项属性、技能或物品存在明显的等级递进或阶段更替（如：等级1 -> 等级2，初级 -> 中级），必须在 added 中加入新条目，并务必在 ids_to_remove 中放入旧条目的 ID。严禁同一实体的多个版本/阶段同时处于活跃状态。\n"
            "2. 唯一性冲突：对于在设定上具有唯一性或排他性的条目，新条目出现时必须移除旧条目。"
            "canonical_entries 每项结构："
            "{chapter_no:number, chapter_title:string, key_facts:string[], causal_results:string[],"
            " open_plots_added:(string|{body,plot_type,priority,estimated_duration,current_stage,resolve_when})[],"
            " open_plots_resolved:string[],"
            " emotional_state:string, unresolved_hooks:string[]}。"
            "open_plots_added 可为字符串或对象：对象时 plot_type 取 Core|Arc|Transient，"
            "priority 越大越重要，estimated_duration 为预计持续章节数（估算即可），"
            "current_stage 为当前推进到哪一步，resolve_when 为真正收束所需条件。"
            "characters_updated / entity_influence_updates 可含 influence_score(0-100)、is_active。"
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
            f"【新章节文本/摘要】\n{chapters_summary}\n\n"
            "任务：提取本批章节相对旧记忆的增量事实。\n"
            "特别提醒：若实体状态/等级发生变更（升级、替换），必须找到旧版本的 ID 放入 ids_to_remove！"
            "如果某条线索在本批明确收束，请将该线索的 ID 放入 ids_to_remove；"
            "如果某条硬约束、技能或物品不再适用，也请放入 ids_to_remove。"
            "如果只是推进但未真正解决，不要移除。"
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
                entry.get("name") or entry.get("item") or entry.get("label") or ""
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
        latest_delta_chapter_no = 0
        
        # 0. 处理全局删除：ids_to_remove
        ids_to_remove = set(delta.get("ids_to_remove") or [])
        if ids_to_remove:
            # 尝试在各分表中根据内容哈希删除匹配项
            for table, attr in [
                (NovelMemoryNormPlot, "body"),
                (NovelMemoryNormCharacter, "name"),
                (NovelMemoryNormSkill, "name"),
                (NovelMemoryNormItem, "label"),
                (NovelMemoryNormPet, "name"),
            ]:
                rows = db.query(table).filter(table.novel_id == novel_id).all()
                to_del_ids = []
                for row in rows:
                    val = getattr(row, attr)
                    if val and NovelLLMService._short_id(val) in ids_to_remove:
                        to_del_ids.append(row.id)
                if to_del_ids:
                    db.query(table).filter(table.id.in_(to_del_ids)).delete(synchronize_session=False)
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
                old_oa = json.loads(entry.open_plots_added_json or "[]")
                entry.open_plots_added_json = json.dumps(
                    _dedupe_str_list([*old_oa, *bodies_add]), ensure_ascii=False
                )

                emo = str(item.get("emotional_state") or "").strip()
                if emo:
                    entry.emotional_state = emo[:2000]
                uh = item.get("unresolved_hooks")
                if isinstance(uh, list) and uh:
                    old_uh = json.loads(entry.unresolved_hooks_json or "[]")
                    if not isinstance(old_uh, list):
                        old_uh = []
                    merged_uh = _dedupe_str_list(
                        [
                            *old_uh,
                            *[str(x).strip() for x in uh if str(x).strip()],
                        ]
                    )
                    entry.unresolved_hooks_json = json.dumps(merged_uh, ensure_ascii=False)

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
            ).delete(synchronize_session=False)
            stats["open_plots_resolved"] += len(top_resolved)

        # 3. 更新角色
        incoming_chars = delta.get("characters_updated")
        if isinstance(incoming_chars, list):
            for item in incoming_chars:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                
                char = db.query(NovelMemoryNormCharacter).filter(
                    NovelMemoryNormCharacter.novel_id == novel_id,
                    NovelMemoryNormCharacter.name == name
                ).first()
                
                if not char:
                    max_order = db.query(func.max(NovelMemoryNormCharacter.sort_order)).filter(
                        NovelMemoryNormCharacter.novel_id == novel_id
                    ).scalar() or 0
                    char = NovelMemoryNormCharacter(
                        novel_id=novel_id,
                        name=name,
                        sort_order=max_order + 1,
                        memory_version=memory_version
                    )
                    db.add(char)
                
                if item.get("role"):
                    char.role = str(item["role"]).strip()
                if item.get("status"):
                    char.status = str(item["status"]).strip()
                
                traits = item.get("traits")
                if traits:
                    old_traits = json.loads(char.traits_json or "[]")
                    if isinstance(traits, list):
                        new_traits = _dedupe_str_list([*old_traits, *traits])
                    else:
                        new_traits = _dedupe_str_list([*old_traits, str(traits)])
                    char.traits_json = json.dumps(new_traits, ensure_ascii=False)
                
                # 处理其他字段存入 detail_json
                detail = json.loads(char.detail_json or "{}")
                for k, v in item.items():
                    if k not in ("name", "role", "status", "traits"):
                        detail[k] = v
                char.detail_json = json.dumps(detail, ensure_ascii=False)
                if item.get("influence_score") is not None:
                    try:
                        char.influence_score = int(item["influence_score"])
                    except (TypeError, ValueError):
                        pass
                if item.get("is_active") is not None:
                    char.is_active = bool(item["is_active"])
                char.memory_version = memory_version
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
                            row.is_active = bool(active)
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
                            row.is_active = bool(active)
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

        # 4. 关系
        incoming_relations = delta.get("relations_changed")
        if isinstance(incoming_relations, list):
            for item in incoming_relations:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                relation = str(item.get("relation") or "").strip()
                if not (src and dst and relation):
                    continue
                
                rel = db.query(NovelMemoryNormRelation).filter(
                    NovelMemoryNormRelation.novel_id == novel_id,
                    NovelMemoryNormRelation.src == src,
                    NovelMemoryNormRelation.dst == dst
                ).first()
                
                if not rel:
                    max_order = db.query(func.max(NovelMemoryNormRelation.sort_order)).filter(
                        NovelMemoryNormRelation.novel_id == novel_id
                    ).scalar() or 0
                    rel = NovelMemoryNormRelation(
                        novel_id=novel_id,
                        src=src,
                        dst=dst,
                        sort_order=max_order + 1,
                        memory_version=memory_version
                    )
                    db.add(rel)
                
                rel.relation = relation
                rel.memory_version = memory_version

        # 5. 物品（added/removed 可能为字符串或 dict，禁止把 dict 直接绑到 label 列）
        inv_changed = delta.get("inventory_changed")
        if isinstance(inv_changed, dict):
            added = inv_changed.get("added") or []
            removed = inv_changed.get("removed") or []

            removed_labels: list[str] = []
            for x in removed:
                lab, _ = NovelLLMService._inventory_entry_label_and_detail(x)
                if lab:
                    removed_labels.append(lab)
            if removed_labels:
                db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id,
                    NovelMemoryNormItem.label.in_(removed_labels),
                ).update(
                    {
                        NovelMemoryNormItem.is_active: False,
                        NovelMemoryNormItem.memory_version: memory_version,
                    },
                    synchronize_session=False,
                )

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
                skill.memory_version = memory_version
                stats["skills_updated"] += 1

        # 6b. 宠物 / 同伴
        pets_changed = delta.get("pets_changed")
        if isinstance(pets_changed, dict):
            added = pets_changed.get("added") or []
            updated = pets_changed.get("updated") or []
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
        self, prev_memory_json: str, delta: dict[str, Any]
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
        
        # 移除 ID 在 ids_to_remove 中的项
        char_names_to_del = [n for n, c in characters_by_name.items() if c.get("id") in ids_to_remove]
        for n in char_names_to_del: characters_by_name.pop(n)

        incoming_chars = delta.get("characters_updated")
        if isinstance(incoming_chars, list):
            for item in incoming_chars:
                if not isinstance(item, dict): continue
                name = str(item.get("name") or "").strip()
                if not name: continue
                base = characters_by_name.get(name, {"name": name, "id": _short_id(name)})
                for key in ("role", "status"):
                    val = str(item.get(key) or "").strip()
                    if val: base[key] = val
                traits = item.get("traits")
                if isinstance(traits, list): base["traits"] = _dedupe_str_list(traits)
                if item.get("influence_score") is not None:
                    try: base["influence_score"] = clamp_int(item["influence_score"], minimum=0, maximum=100, default=0)
                    except: pass
                if item.get("is_active") is not None: base["is_active"] = bool(item["is_active"])
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
                    iid = item.get("id") or _short_id(f"{src}-{dst}")
                    relation_map[iid] = {
                        "id": iid, "from": src, "to": dst, 
                        "relation": str(item.get("relation") or "").strip()
                    }
        # 移除
        for iid in ids_to_remove: relation_map.pop(iid, None)
        # 更新/新增
        incoming_relations = delta.get("relations_changed")
        if isinstance(incoming_relations, list):
            for item in incoming_relations:
                if not isinstance(item, dict): continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                relation = str(item.get("relation") or "").strip()
                if src and dst and relation:
                    iid = _short_id(f"{src}-{dst}")
                    relation_map[iid] = {"id": iid, "from": src, "to": dst, "relation": relation}
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
    ) -> dict[str, Any]:
        router = self._router(db=db)
        raw = await self._chat_text_with_timeout_retry(
            router=router,
            operation="memory_refresh",
            novel_id=novel.id,
            messages=self._memory_delta_messages(novel, chapters_summary, prev_memory),
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
            }
        
        # 1. 计算合并后的 JSON (用于校验和快照)
        merged, stats = self._merge_memory_delta(prev_memory, delta)
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
            }

        # 3. 如果没有 blocking_errors 且有 db，则执行规范化表更新
        new_version = 0
        if db and not blocking_errors:
            try:
                # 使用 Savepoint 保护事务，防止局部失败导致全局回滚（如章节审批状态丢失）
                with db.begin_nested():
                    new_version = self._get_latest_memory_version(db, novel.id) + 1
                    db_stats = self._upsert_normalized_memory_from_delta(db, novel.id, delta, new_version)
                    # 合并统计信息
                    for k, v in db_stats.items():
                        stats[k] = max(stats.get(k, 0), v)
                    
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
                    snap_ver = sync_json_snapshot_from_normalized(
                        db, novel.id, summary="规范化存储自动快照（batch/incremental）"
                    )
                    new_version = snap_ver
                
                # 显式 flush 确保状态可见，但由外部调用者（Router）负责最终 commit
                db.flush()
                
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
                # 依然标记 ok=True，因为 JSON 合并已成功，不阻断审定流程
        
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
        }

    def _apply_memory_delta_batch_sync(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
    ) -> dict[str, Any]:
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="memory_refresh",
            novel_id=novel.id,
            messages=self._memory_delta_messages(novel, chapters_summary, prev_memory),
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
            }
        
        # 1. 计算合并后的 JSON (用于校验和快照)
        merged, stats = self._merge_memory_delta(prev_memory, delta)
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
            }

        # 3. 如果没有 blocking_errors 且有 db，则执行规范化表更新
        new_version = 0
        if db and not blocking_errors:
            try:
                with db.begin_nested():
                    new_version = self._get_latest_memory_version(db, novel.id) + 1
                    db_stats = self._upsert_normalized_memory_from_delta(db, novel.id, delta, new_version)
                    # 合并统计信息
                    for k, v in db_stats.items():
                        stats[k] = max(stats.get(k, 0), v)
                    
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

                    snap_ver = sync_json_snapshot_from_normalized(
                        db, novel.id, summary="规范化存储自动快照（batch_sync/incremental）"
                    )
                    new_version = snap_ver
                
                db.flush()
                
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
        }

    async def refresh_memory_from_chapters(
        self, novel: Novel, chapters_summary: str, prev_memory: str, db: Any = None
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
        total_stats = {"canonical_entries": 0, "open_plots_added": 0, "open_plots_resolved": 0, "characters_updated": 0}
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
            result = await self._apply_memory_delta_batch(
                novel, batch_summary, current_memory, db=db
            )
            if not result["ok"]:
                result["batch"] = batch_num
                return result
            current_memory = result["payload_json"]
            collected_warnings.extend(_dedupe_str_list(result.get("warnings", [])))
            collected_auto_pass_notes.extend(_dedupe_str_list(result.get("auto_pass_notes", [])))
            for key in total_stats:
                total_stats[key] += int(result.get("stats", {}).get(key, 0))
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
        }
        if db:
            out["version"] = self._get_latest_memory_version(db, novel.id)
        return out

    def refresh_memory_from_chapters_sync(
        self, novel: Novel, chapters_summary: str, prev_memory: str, db: Any = None
    ) -> dict[str, Any]:
        """同步版本的记忆刷新，采用增量抽取 + 代码合并。"""
        batch_chars = settings.novel_memory_refresh_batch_chars
        summary_len = len(chapters_summary or "")
        current_memory = prev_memory
        total_stats = {"canonical_entries": 0, "open_plots_added": 0, "open_plots_resolved": 0, "characters_updated": 0}
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
            result = self._apply_memory_delta_batch_sync(
                novel, batch_summary, current_memory, db=db
            )
            if not result["ok"]:
                result["batch"] = batch_num
                return result
            current_memory = result["payload_json"]
            collected_warnings.extend(_dedupe_str_list(result.get("warnings", [])))
            collected_auto_pass_notes.extend(_dedupe_str_list(result.get("auto_pass_notes", [])))
            for key in total_stats:
                total_stats[key] += int(result.get("stats", {}).get(key, 0))
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
                    novel, chapter, memory_json, feedback_bodies, user_prompt
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
                    novel, chapter, memory_json, feedback_bodies, user_prompt
                )
            ),
            temperature=0.65,
            timeout=600.0,
            web_search=self._novel_web_search(db, flow="default"),
            **self._bill_kw(db, self._billing_user_id),
        )
