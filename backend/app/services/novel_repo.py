from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Chapter, NovelMemory
from app.models.volume import NovelChapterPlan, NovelVolume
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
from app.services.chapter_plan_schema import (
    chapter_plan_goal,
    chapter_plan_turn,
    normalize_beats_to_v2,
)
from app.services.memory_schema import extract_aliases, memory_schema_guide


def chapter_content_metrics(content: str) -> dict[str, int]:
    """
    统计章节可读性相关基础指标：
    - total_chars: 含标题在内，去除空白后的总字符数
    - body_chars: 去掉首行章节标题后的正文字符数
    - paragraph_count: 正文非空行数，近似视为段落数
    """
    raw = (content or "").replace("\r\n", "\n").strip()
    if not raw:
        return {"total_chars": 0, "body_chars": 0, "paragraph_count": 0}

    lines = raw.splitlines()
    first_line = lines[0].strip() if lines else ""
    has_heading = bool(re.match(r"^第\s*\d+\s*章", first_line))
    body = "\n".join(lines[1:]).strip() if has_heading else raw

    def _compact_len(text: str) -> int:
        return len(re.sub(r"\s+", "", text or ""))

    paragraph_count = len([line for line in body.splitlines() if line.strip()])
    return {
        "total_chars": _compact_len(raw),
        "body_chars": _compact_len(body),
        "paragraph_count": paragraph_count,
    }


def format_approved_chapters_summary(
    chapters: list[Chapter],
    tail_chars: int,
    *,
    head_chars: int | None = None,
    mode: str = "tail",
    max_chapters: int = 15,
) -> str:
    """
    已审定章节正文截断后拼接，供记忆合并。
    同时在文本中嵌入内容哈希，供 NovelLLMService 实现断点跳过逻辑。
    """
    if not chapters:
        return ""
    tail_chapters = (
        chapters[-max_chapters:] if len(chapters) > max_chapters else chapters
    )

    mode = (mode or "tail").strip().lower()
    if mode not in ("tail", "head", "both"):
        mode = "tail"

    if head_chars is None:
        head_chars = tail_chars

    def slice_one(c: Chapter) -> str:
        t = c.content or ""
        # 构造正文截断
        if mode == "tail":
            body = t[-tail_chars:]
        elif mode == "head":
            body = t[:head_chars]
        else:
            # both：开头 + 结尾
            body = f"{t[:head_chars]}\n…（续写结尾）…\n{t[-tail_chars:]}"
            
        return body

    return "\n\n".join(
        f"第{c.chapter_no}章 {c.title}\n{slice_one(c)}"
        for c in tail_chapters
    )


def latest_memory_json(db: Session, novel_id: str) -> str:
    row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    return row.payload_json if row else "{}"


def next_chapter_no(db: Session, novel_id: str) -> int:
    m = (
        db.query(func.max(Chapter.chapter_no))
        .filter(Chapter.novel_id == novel_id)
        .scalar()
    )
    return (m or 0) + 1


def next_chapter_no_from_approved(db: Session, novel_id: str) -> int:
    """按“已审定章节”续写下一章号，避免被待审草稿干扰。"""
    m = (
        db.query(func.max(Chapter.chapter_no))
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .scalar()
    )
    return (m or 0) + 1


def has_any_chapter_plan(db: Session, novel_id: str) -> bool:
    """是否存在任意章计划条目。"""
    return (
        db.query(NovelChapterPlan.id)
        .filter(NovelChapterPlan.novel_id == novel_id)
        .limit(1)
        .first()
    ) is not None


def chapter_plan_exists(db: Session, novel_id: str, chapter_no: int) -> bool:
    return (
        db.query(NovelChapterPlan.id)
        .filter(
            NovelChapterPlan.novel_id == novel_id,
            NovelChapterPlan.chapter_no == chapter_no,
        )
        .first()
    ) is not None


def chapter_needs_body_per_plan(db: Session, novel_id: str, chapter_no: int) -> bool:
    """
    该章在章计划中存在，且当前尚未形成「可视为已写完」的正文。
    已审定、或已有非空待审正文，视为不需要再自动生成。
    """
    if not chapter_plan_exists(db, novel_id, chapter_no):
        return False
    ch = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.chapter_no == chapter_no)
        .order_by(Chapter.updated_at.desc())
        .first()
    )
    if not ch:
        return True
    if ch.status == "approved":
        return False
    if (ch.content or "").strip():
        return False
    return True


def planned_chapter_numbers_needing_body(
    db: Session, novel_id: str, limit: int
) -> list[int]:
    """
    按全局章号升序，取前 limit 个「有计划且尚缺正文」的章号（用于批量续写，串行生成以保持连贯）。
    """
    if limit <= 0:
        return []
    rows = (
        db.query(NovelChapterPlan.chapter_no)
        .filter(NovelChapterPlan.novel_id == novel_id)
        .distinct()
        .all()
    )
    nos = sorted({int(r[0]) for r in rows})
    out: list[int] = []
    for no in nos:
        if len(out) >= limit:
            break
        if chapter_needs_body_per_plan(db, novel_id, no):
            out.append(no)
    return out


def truncate_framework_json(framework_json: str, max_len: int = 8000) -> str:
    raw = (framework_json or "").strip()
    if not raw:
        return "（无框架 JSON）"
    if len(raw) <= max_len:
        return raw
    return raw[:max_len] + "\n…(framework_json 已截断)"


def format_open_plots_block(memory_json: str) -> str:
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    op = data.get("open_plots")
    if op is None or op == [] or op == "":
        return ""
    lines: list[str] = ["【须承接的未完结剧情线（open_plots）】"]
    if isinstance(op, list):
        for i, x in enumerate(op[:24], 1):
            if isinstance(x, str):
                lines.append(f"  {i}. {x}")
            else:
                body = str(x.get("body") or x.get("text") or "").strip()
                iid = x.get("id")
                meta: list[str] = []
                ptype = str(x.get("plot_type") or "").strip()
                if ptype and ptype != "Transient":
                    meta.append(ptype)
                pr = x.get("priority")
                if isinstance(pr, int) and pr > 0:
                    meta.append(f"prio={pr}")
                est = x.get("estimated_duration")
                if isinstance(est, int) and est > 0:
                    meta.append(f"约{est}章")
                current_stage = str(x.get("current_stage") or "").strip()
                resolve_when = str(x.get("resolve_when") or "").strip()
                id_tag = f"[{iid}] " if iid else ""
                line = id_tag + (f"[{' / '.join(meta)}] " if meta else "") + (body or json.dumps(x, ensure_ascii=False))
                if current_stage:
                    line += f"｜当前阶段：{current_stage[:120]}"
                if resolve_when:
                    line += f"｜收束条件：{resolve_when[:120]}"
                lines.append(f"  {i}. {line}")
    else:
        lines.append(f"  {op}")
    return "\n".join(lines)


def _compact_characters_for_hot(chars: Any, max_items: int) -> list[dict[str, str]]:
    if not isinstance(chars, list):
        return []
    out: list[dict[str, str]] = []
    for x in chars[:max_items]:
        if not isinstance(x, dict):
            continue
        item: dict[str, str] = {}
        name = x.get("name")
        role = x.get("role")
        traits = x.get("traits")
        state = x.get("state") or x.get("status")
        iid = x.get("id")
        if isinstance(name, str) and name.strip():
            item["name"] = name.strip()
        if isinstance(role, str) and role.strip():
            item["role"] = role.strip()
        if isinstance(traits, str) and traits.strip():
            item["traits"] = traits.strip()[:120]
        if isinstance(state, str) and state.strip():
            item["state"] = state.strip()[:120]
        if iid:
            item["id"] = str(iid)
        if item:
            out.append(item)
    return out


def _dedupe_preserve_order(items: list[str], *, max_items: int | None = None) -> list[str]:
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


def _compact_relations_for_hot(relations: Any, max_items: int = 10) -> list[dict[str, str]]:
    if not isinstance(relations, list):
        return []
    out: list[dict[str, str]] = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        src = str(rel.get("from") or "").strip()
        dst = str(rel.get("to") or "").strip()
        relation = str(rel.get("relation") or "").strip()
        iid = rel.get("id")
        if not (src and dst and relation):
            continue
        item = {"from": src, "to": dst, "relation": relation[:140]}
        if iid:
            item["id"] = str(iid)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _compact_inventory_for_hot(inventory: Any, max_items: int = 12) -> list[dict[str, Any]]:
    if not isinstance(inventory, list):
        return []
    out: list[dict[str, Any]] = []
    seen = set()
    for item in inventory:
        if isinstance(item, dict):
            label = str(
                item.get("name") or item.get("item") or item.get("label") or ""
            ).strip()
            iid = item.get("id")
            if label and label not in seen:
                out.append({"name": label[:120], "id": str(iid) if iid else None})
                seen.add(label)
        else:
            text = str(item).strip()
            if text and text not in seen:
                out.append({"name": text[:120]})
                seen.add(text)
        if len(out) >= max_items:
            break
    return out


def _compact_named_state_for_hot(items: Any, max_items: int = 8) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        compact: dict[str, str] = {"name": name}
        description = str(item.get("description") or item.get("role") or "").strip()
        cost = str(item.get("cost") or item.get("status") or "").strip()
        iid = item.get("id")
        if description:
            compact["description"] = description[:140]
        if cost:
            compact["status"] = cost[:120]
        if iid:
            compact["id"] = str(iid)
        out.append(compact)
        if len(out) >= max_items:
            break
    return out


def build_hot_memory_for_prompt(
    memory_json: str,
    *,
    timeline_hot_n: int = 20,
    open_plots_hot_max: int = 20,
    characters_hot_max: int = 12,
) -> str:
    """
    冷热分层：仅把热层注入写章 prompt，降低 token。
    - canonical_timeline_hot: 最近 N 条
    - open_plots_hot: 活跃未完结线前 M 条
    - characters_hot: 精简人物状态
    """
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return memory_json or "{}"
    if not isinstance(data, dict):
        return memory_json or "{}"

    timeline_hot = data.get("canonical_timeline_hot")
    if not isinstance(timeline_hot, list):
        base = data.get("canonical_timeline")
        if isinstance(base, list):
            timeline_hot = base[-timeline_hot_n:] if len(base) > timeline_hot_n else base
        else:
            timeline_hot = []

    open_plots = data.get("open_plots")
    if isinstance(open_plots, list):
        open_plots_hot = open_plots[:open_plots_hot_max]
    elif isinstance(open_plots, str) and open_plots.strip():
        open_plots_hot = [open_plots.strip()]
    else:
        open_plots_hot = []

    hot_payload = {
        "forbidden_constraints_hot": [
            x if isinstance(x, dict) else {"body": str(x).strip()}
            for x in data.get("forbidden_constraints", [])
        ][:12],
        "main_plot_hot": str(data.get("main_plot") or "").strip()[:240],
        "open_plots_hot": open_plots_hot,
        "canonical_timeline_hot": timeline_hot,
        "characters_hot": _compact_characters_for_hot(
            data.get("characters"), characters_hot_max
        ),
        "relations_hot": _compact_relations_for_hot(data.get("relations"), max_items=10),
        "inventory_hot": _compact_inventory_for_hot(data.get("inventory"), max_items=12),
        "skills_hot": _compact_named_state_for_hot(data.get("skills"), max_items=8),
        "pets_hot": _compact_named_state_for_hot(data.get("pets"), max_items=6),
    }
    if isinstance(data.get("timeline_archive_summary"), list):
        hot_payload["timeline_archive_summary"] = data.get("timeline_archive_summary")[:6]
    return json.dumps(hot_payload, ensure_ascii=False)


def _extract_recall_terms(memory_json: str, query_text: str) -> list[str]:
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    query = str(query_text or "").strip()
    if not query:
        return []

    candidates: list[str] = []
    for key in ("characters", "skills", "pets"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if name and name in query:
                    candidates.append(name)
                for alias in extract_aliases(item):
                    if alias and alias in query:
                        candidates.append(alias)
    for raw in data.get("inventory", []) if isinstance(data.get("inventory"), list) else []:
        if isinstance(raw, dict):
            item = str(raw.get("name") or raw.get("item") or raw.get("label") or "").strip()
            aliases = extract_aliases(raw)
        else:
            item = str(raw or "").strip()
            aliases = []
        if not item:
            continue
        short = re.split(r"[（(，,:：]", item)[0].strip()
        if short and short in query:
            candidates.append(short)
        for alias in aliases:
            if alias in query:
                candidates.append(alias)
    for raw in data.get("open_plots", []) if isinstance(data.get("open_plots"), list) else []:
        if isinstance(raw, dict):
            plot = str(raw.get("body") or raw.get("text") or "").strip()
        else:
            plot = str(raw or "").strip()
        if not plot:
            continue
        for token in re.split(r"[，、：:；。,.\\s]", plot):
            t = token.strip()
            if len(t) >= 2 and t in query:
                candidates.append(t)
    return _dedupe_preserve_order(candidates, max_items=10)


def format_entity_recall_block(
    memory_json: str,
    query_text: str,
    *,
    max_items: int = 6,
) -> str:
    """
    按章节计划/线索关键词，定向召回与当前章节最相关的人物、关系、道具、技能与历史事实。
    """
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""

    terms = _extract_recall_terms(memory_json, query_text)
    if not terms:
        return ""

    lines: list[str] = ["【与本章最相关的记忆召回】", "命中实体：" + "、".join(terms)]

    chars = data.get("characters")
    if isinstance(chars, list):
        matched_chars: list[str] = []
        for item in chars:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            aliases = extract_aliases(item)
            if not name or not (name in terms or any(alias in terms for alias in aliases)):
                continue
            role = str(item.get("role") or "").strip()
            state = str(item.get("status") or item.get("state") or "").strip()
            matched_chars.append(
                f"- {name}"
                + (f"｜身份：{role[:80]}" if role else "")
                + (f"｜当前状态：{state[:140]}" if state else "")
                + (f"｜别名：{'、'.join(aliases[:4])}" if aliases else "")
            )
            if len(matched_chars) >= max_items:
                break
        if matched_chars:
            lines.append("相关人物：")
            lines.extend(matched_chars)

    relations = data.get("relations")
    if isinstance(relations, list):
        matched_rel: list[str] = []
        for item in relations:
            if not isinstance(item, dict):
                continue
            src = str(item.get("from") or "").strip()
            dst = str(item.get("to") or "").strip()
            relation = str(item.get("relation") or "").strip()
            if not relation:
                continue
            if any(term in src or term in dst or term in relation for term in terms):
                matched_rel.append(f"- {src} -> {dst}：{relation[:140]}")
            if len(matched_rel) >= max_items:
                break
        if matched_rel:
            lines.append("相关关系：")
            lines.extend(matched_rel)

    inventory = data.get("inventory")
    if isinstance(inventory, list):
        matched_items: list[str] = []
        for item in inventory:
            if isinstance(item, dict):
                blob = json.dumps(item, ensure_ascii=False)
                aliases = extract_aliases(item)
                if not (
                    any(term in blob for term in terms)
                    or any(alias in terms for alias in aliases)
                ):
                    continue
                label = str(
                    item.get("name") or item.get("item") or item.get("label") or ""
                ).strip()
                if not label:
                    continue
                matched_items.append(
                    f"- {label[:160]}" + (f"｜别名：{'、'.join(aliases[:4])}" if aliases else "")
                )
            else:
                text = str(item).strip()
                if text and any(term in text for term in terms):
                    matched_items.append(f"- {text[:160]}")
            if len(matched_items) >= max_items:
                break
        if matched_items:
            lines.append("相关物品：")
            lines.extend(matched_items)

    for section_key, title in (("skills", "相关技能"), ("pets", "相关同伴")):
        items = data.get(section_key)
        if not isinstance(items, list):
            continue
        matched: list[str] = []
        for item in items:
            if isinstance(item, dict):
                blob = json.dumps(item, ensure_ascii=False)
            else:
                blob = str(item)
            if any(term in blob for term in terms):
                matched.append(f"- {blob[:180]}")
            if len(matched) >= max_items:
                break
        if matched:
            lines.append(title + "：")
            lines.extend(matched)

    timeline = data.get("canonical_timeline_cold")
    if not isinstance(timeline, list):
        timeline = data.get("canonical_timeline_hot")
    if isinstance(timeline, list):
        matched_events: list[str] = []
        for item in timeline:
            blob = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
            if any(term in blob for term in terms):
                if isinstance(item, dict):
                    cn = item.get("chapter_no")
                    key_facts = item.get("key_facts") if isinstance(item.get("key_facts"), list) else []
                    causal_results = (
                        item.get("causal_results")
                        if isinstance(item.get("causal_results"), list)
                        else []
                    )
                    snippet = "；".join(
                        [str(x).strip() for x in [*key_facts[:2], *causal_results[:1]] if str(x).strip()]
                    )
                    matched_events.append(f"- 第{cn}章：{snippet[:180]}")
                else:
                    matched_events.append(f"- {blob[:180]}")
            if len(matched_events) >= max_items:
                break
        if matched_events:
            lines.append("相关历史事实：")
            lines.extend(matched_events)

    return "\n".join(lines) if len(lines) > 2 else ""


def format_cold_recall_block(memory_json: str, *, max_items: int = 5) -> str:
    """
    按需召回冷层：从 canonical_timeline_cold/timeline_archive_summary 抽取少量历史条目。
    默认不注入写章，只有用户开启“冷层召回”时才加入 prompt。
    """
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""

    lines: list[str] = ["【冷层历史召回（按需）】"]
    cold = data.get("canonical_timeline_cold")
    if isinstance(cold, list) and cold:
        tail = cold[-max_items:] if len(cold) > max_items else cold
        lines.append("最近冷层条目：")
        for i, x in enumerate(tail, 1):
            if isinstance(x, dict):
                cn = x.get("chapter_no")
                key = x.get("key_facts")
                key_text = ""
                if isinstance(key, list) and key:
                    key_text = "；".join(str(v) for v in key[:2] if str(v).strip())
                lines.append(
                    f"  {i}. 第{cn}章"
                    + (f"：{key_text[:120]}" if key_text else "")
                )
            elif isinstance(x, str) and x.strip():
                lines.append(f"  {i}. {x.strip()[:140]}")

    arch = data.get("timeline_archive_summary")
    if isinstance(arch, list) and arch:
        lines.append("阶段压缩摘要：")
        for i, x in enumerate(arch[: max(1, min(3, max_items))], 1):
            if isinstance(x, str) and x.strip():
                lines.append(f"  - {x.strip()[:180]}")
            elif isinstance(x, dict):
                lines.append(f"  - {json.dumps(x, ensure_ascii=False)[:180]}")

    return "\n".join(lines) if len(lines) > 1 else ""


def format_canonical_timeline_block(memory_json: str, chapter_no: int) -> str:
    """
    从结构化记忆 JSON 中提取 canonical_timeline，并格式化为可读“硬约束”区块。

    兼容历史数据：若 canonical_timeline 不存在或结构不符合预期，则返回空字符串。
    """
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""

    ct = data.get("canonical_timeline_hot")
    if not isinstance(ct, list):
        ct = data.get("canonical_timeline")
    if ct is None or ct == "":
        return ""

    if not isinstance(ct, list) or not ct:
        return ""

    # 只取目标章之前的最后若干条（降低 token）
    prev_no = chapter_no - 1
    entries: list[dict[str, object] | str] = []
    for x in ct:
        if isinstance(x, dict):
            cn = x.get("chapter_no")
            if isinstance(cn, int) and cn <= prev_no:
                entries.append(x)
            continue
        if isinstance(x, str):
            entries.append(x)

    if not entries:
        # 若过滤后为空，退化为取最后几条
        entries = ct[-10:]

    last = entries[-6:] if len(entries) > 6 else entries
    lines: list[str] = ["【规范时间线账本（canonical_timeline）硬约束】"]
    for i, x in enumerate(last, 1):
        if isinstance(x, str):
            lines.append(f"  {i}. {x}")
            continue
        cn = x.get("chapter_no")
        key_facts = x.get("key_facts")
        causal_results = x.get("causal_results")
        added = x.get("open_plots_added")
        resolved = x.get("open_plots_resolved")
        title = x.get("chapter_title")

        head = f"  {i}. 第{cn}章" + (f"《{title}》" if title else "")
        lines.append(head)
        if isinstance(key_facts, list) and key_facts:
            facts = [str(k) for k in key_facts if str(k).strip()][:8]
            lines.append("     关键事实：" + "；".join(facts))
        if isinstance(causal_results, list) and causal_results:
            causals = [str(c) for c in causal_results if str(c).strip()][:6]
            lines.append("     因果结果：" + "；".join(causals))
        if isinstance(added, list) and added:
            adds = [str(a) for a in added if str(a).strip()][:6]
            lines.append("     新增未完结线：" + "；".join(adds))
        if isinstance(resolved, list) and resolved:
            ress = [str(r) for r in resolved if str(r).strip()][:6]
            lines.append("     已收束/解决线：" + "；".join(ress))
    return "\n".join(lines)


def outline_beat_hint(chapter_no: int, framework_json: str) -> str:
    """根据章序号与框架 JSON 生成简短节奏提示（容错）。"""
    phases = (
        "铺陈矛盾与人物目标",
        "推进主线并升级冲突",
        "制造阶段性张力或信息反转",
        "收束支线、埋设更大悬念",
    )
    base = (
        f"【本章大纲节拍】第 {chapter_no} 章：请与已生成正文无缝衔接，保持跌宕起伏；"
        f"阶段侧重：{phases[(max(chapter_no, 1) - 1) % len(phases)]}。"
    )
    raw = (framework_json or "").strip()
    if not raw:
        return base
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return base + "（框架 JSON 无法解析为对象，已略过卷/弧匹配）"

    if not isinstance(data, dict):
        return base

    arcs = data.get("arcs")
    if isinstance(arcs, list) and len(arcs) > 0:
        for arc in arcs:
            if not isinstance(arc, dict):
                continue
            title = str(arc.get("title") or arc.get("name") or "本卷/阶段")
            summary = arc.get("summary") or arc.get("beats") or arc.get("outline")
            cr = arc.get("chapter_range") or arc.get("chapters") or arc.get("chapter_nos")
            b = arc_bounds_from_dict(arc)
            if not b:
                continue
            lo, hi = b
            if chapter_no < lo:
                continue
            if chapter_no > hi:
                continue
            hint_parts = [f"当前阶段大纲弧「{title}」（第{lo}—{hi}章）"]
            if summary:
                st = str(summary)[:500]
                hint_parts.append(f"要点：{st}")
            if cr is not None:
                hint_parts.append(f"范围提示：{cr}")
            return base + "\n" + "；".join(hint_parts) + "。"
        # 未命中任一区间：不回退到第一条弧（防止把后段大纲摘要提前注入）
        return (
            base
            + "\n（当前章未落在框架 arcs 任一章节区间内；请按主线与卷进度推进，勿提前进入后续大阶段。）"
        )

    mp = data.get("main_plot")
    if isinstance(mp, str) and mp.strip():
        return base + f"\n主线参考：{mp.strip()[:450]}"

    return base


def _parse_int(v: object) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        try:
            return int(v.strip())
        except Exception:
            return None
    return None


def _parse_chapter_range(v: object) -> tuple[int | None, int | None]:
    """
    兼容多种写法：
    - {"from_chapter": 1, "to_chapter": 50}
    - "1-50" / "1~50" / "1—50" / "1–50"
    - [1, 50]
    """
    if v is None:
        return None, None
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        lo = _parse_int(v[0])
        hi = _parse_int(v[1])
        return lo, hi
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None, None
        m = re.search(r"(\d+)\s*[-~—–]\s*(\d+)", s)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def arc_bounds_from_dict(arc: dict) -> tuple[int, int] | None:
    """解析单条 arc 的章节起止（与 _select_arc_for_chapter 一致）。"""
    lo = _parse_int(arc.get("from_chapter") or arc.get("from"))
    hi = _parse_int(arc.get("to_chapter") or arc.get("to"))
    if lo is None or hi is None:
        lo2, hi2 = _parse_chapter_range(arc.get("chapter_range") or arc.get("chapters"))
        lo = lo if lo is not None else lo2
        hi = hi if hi is not None else hi2
    if isinstance(lo, int) and isinstance(hi, int):
        return lo, hi
    return None


def pacing_boundary_chapter_no(chapter_no: int, framework_json: str) -> int:
    """
    当前章所在「阶段」的右边界（含）：后续 arcs（起章号 > 边界）视为未来阶段，不得提前剧透。
    若未命中弧，则边界为当前章号。
    """
    cur = _select_arc_for_chapter(framework_json, chapter_no)
    if cur:
        b = arc_bounds_from_dict(cur)
        if b:
            lo, hi = b
            return max(chapter_no, hi)
    return chapter_no


def forbidden_future_arcs_block(chapter_no: int, framework_json: str) -> str:
    """
    列出「当前阶段之后」的大纲弧标题与章节范围，作为强禁止项（不注入后续弧的长摘要，避免诱导抢跑）。
    """
    raw = (framework_json or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    arcs = data.get("arcs")
    if not isinstance(arcs, list) or not arcs:
        return ""

    boundary = pacing_boundary_chapter_no(chapter_no, framework_json)
    lines: list[str] = []
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        b = arc_bounds_from_dict(arc)
        if not b:
            continue
        lo, hi = b
        if lo <= boundary:
            continue
        title = str(arc.get("title") or arc.get("name") or "未命名阶段").strip()
        lines.append(f"- 第{lo}—{hi}章阶段「{title}」（禁止在本章及此前阶段正文与对话中提前实现、点名真相或完成该阶段核心转折）")

    if not lines:
        return ""

    return (
        "【后续阶段（严禁提前推进/剧透）】\n"
        f"- 当前为第{chapter_no}章；下列为更后阶段才应展开的大纲分区。\n"
        "- 本章不得让剧情实质进入下列阶段的核心事件、不得揭露下列阶段才允许出现的身份/真相/能力/阵营结果。\n"
        "- 若必须铺垫，只能写「悬念/误解/局部线索」，不得写后验结论。\n"
        + "\n".join(lines[:20])
    )


def _select_arc_for_chapter(framework_json: str, chapter_no: int) -> dict[str, object] | None:
    """
    从 framework_json.arcs 中选取命中 chapter_no 的弧线。
    约定：arc 可包含 from_chapter/to_chapter 或 chapter_range/chapters。
    """
    raw = (framework_json or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    arcs = data.get("arcs")
    if not isinstance(arcs, list):
        return None

    # 1) 优先命中明确数值区间
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        lo = _parse_int(arc.get("from_chapter") or arc.get("from"))
        hi = _parse_int(arc.get("to_chapter") or arc.get("to"))
        if lo is None or hi is None:
            # 兼容 chapter_range/chapters 字段
            lo2, hi2 = _parse_chapter_range(arc.get("chapter_range") or arc.get("chapters"))
            lo = lo if lo is not None else lo2
            hi = hi if hi is not None else hi2
        if isinstance(lo, int) and isinstance(hi, int) and lo <= chapter_no <= hi:
            return arc

    # 2) 若没命中，返回“最近的下一弧”或第一弧（容错）
    fallback = None
    min_lo = None
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        lo = _parse_int(arc.get("from_chapter") or arc.get("from"))
        hi = _parse_int(arc.get("to_chapter") or arc.get("to"))
        if lo is None or hi is None:
            lo2, hi2 = _parse_chapter_range(arc.get("chapter_range") or arc.get("chapters"))
            lo = lo if lo is not None else lo2
            hi = hi if hi is not None else hi2
        if isinstance(lo, int) and isinstance(hi, int) and chapter_no < lo:
            if min_lo is None or lo < min_lo:
                min_lo = lo
                fallback = arc
    if fallback:
        return fallback
    # 3) 章号已越过所有弧的上界：取列表中最后一条弧（避免误用第一条弧导致节奏抢跑）
    last_arc: dict | None = None
    for arc in reversed(arcs):
        if isinstance(arc, dict):
            last_arc = arc
            break
    return last_arc


def pacing_guard_block(chapter_no: int, framework_json: str, memory_json: str) -> str:
    """
    节奏闸门：把“章号 → 大纲弧线/节拍”落到 prompt，防止一章跨越多个大节点。
    依赖：framework_json.arcs 提供章节范围与 beats/outline/summary（任一即可）。
    """
    arc = _select_arc_for_chapter(framework_json, chapter_no)
    if not arc:
        return (
            "【节奏闸门（弱约束）】\n"
            f"- 本章：第{chapter_no}章\n"
            "- 由于框架 JSON 未提供可匹配的 arcs 章节范围，本章仅执行“单一目标 + 一次受阻 + 小结果 + 钩子”。\n"
            "- 严禁在一章内完成多个大事件（例如：发现线索→验证→抓到真凶）。"
        )

    title = str(arc.get("title") or arc.get("name") or "当前大纲弧").strip()
    lo = _parse_int(arc.get("from_chapter") or arc.get("from"))
    hi = _parse_int(arc.get("to_chapter") or arc.get("to"))
    if lo is None or hi is None:
        lo2, hi2 = _parse_chapter_range(arc.get("chapter_range") or arc.get("chapters"))
        lo = lo if lo is not None else lo2
        hi = hi if hi is not None else hi2

    beats = arc.get("beats") or arc.get("outline")
    beat_lines: list[str] = []
    if isinstance(beats, list):
        for x in beats[:24]:
            if isinstance(x, str) and x.strip():
                beat_lines.append(x.strip())
            elif isinstance(x, dict):
                # 常见结构：{title, goal, conflict, turn, hook}
                bits = []
                for k in ("title", "goal", "conflict", "turn", "hook", "result"):
                    v = x.get(k)
                    if isinstance(v, str) and v.strip():
                        bits.append(v.strip())
                if bits:
                    beat_lines.append(" / ".join(bits)[:220])
    elif isinstance(beats, str) and beats.strip():
        # 允许用 summary 代替
        beat_lines.append(beats.strip()[:240])
    else:
        s = arc.get("summary")
        if isinstance(s, str) and s.strip():
            beat_lines.append(s.strip()[:240])

    # 估算本章在弧内的“推荐节拍索引”（只用于提示，不当作硬事实）
    idx = 0
    if isinstance(lo, int) and isinstance(hi, int) and hi >= lo:
        span = max(1, hi - lo + 1)
        pos = max(0, min(span - 1, chapter_no - lo))
        if beat_lines:
            idx = int(round((pos / max(1, span - 1)) * (len(beat_lines) - 1)))
            idx = max(0, min(len(beat_lines) - 1, idx))

    # open_plots 作为“不得过快收束/跳跃”的刹车
    open_plots_preview: list[str] = []
    try:
        mem = json.loads(memory_json or "{}")
        if isinstance(mem, dict):
            op = mem.get("open_plots") or mem.get("open_plots_hot")
            if isinstance(op, list):
                open_plots_preview = [str(x).strip() for x in op if str(x).strip()][:8]
            elif isinstance(op, str) and op.strip():
                open_plots_preview = [op.strip()]
    except Exception:
        open_plots_preview = []

    arc_range_text = ""
    if isinstance(lo, int) and isinstance(hi, int):
        arc_range_text = f"（第{lo}—{hi}章）"

    lines: list[str] = [
        "【节奏闸门（强约束，防止推进过快）】",
        f"- 你正在写：第{chapter_no}章",
        f"- 当前大纲弧：{title}{arc_range_text}",
        "- 本章只允许推进“一个小节拍”，并以“受阻/代价/钩子”收束；不得跨越到下一大纲弧的关键事件。",
        "- 禁止把多个关键步骤合并在同一章（线索出现→验证→解决/击杀/收编/觉醒 等不得连跳）。",
        "- 若本章涉及 open_plots：最多只允许“新增 1 条”或“收束 1 条”，不得批量清坑。",
    ]
    if open_plots_preview:
        lines.append("- 当前活跃 open_plots（摘录）：")
        for i, x in enumerate(open_plots_preview, 1):
            lines.append(f"  {i}. {x[:180]}")
    if beat_lines:
        lines.append("- 当前弧可参考节拍（摘录）：")
        start = max(0, idx - 1)
        end = min(len(beat_lines), idx + 2)
        for i in range(start, end):
            tag = "（优先）" if i == idx else ""
            lines.append(f"  - {beat_lines[i]}{tag}")
        lines.append(
            "- 交付要求：本章结尾必须留下“下一章立即可写”的明确钩子（一个新问题/新威胁/新期限）。"
        )
    return "\n".join(lines)


def chapter_execution_rules_block(chapter_no: int) -> str:
    """
    章内执行规则：把“每章三段式 + 限制单章推进量”变成硬约束。
    目的：避免一章跨多个事件，强制出现受阻与钩子。
    """
    return (
        "【章内执行规则（强约束）】\n"
        f"- 本章：第{chapter_no}章\n"
        "- 结构必须满足：开头一个明确目标；中段一次行动→受阻→调整；结尾一个小结果 + 一个新钩子。\n"
        "- 本章只允许完成“关键事件链”的一个小环节：只拿到线索/只达成交易/只失败一次并留下代价；禁止顺便把后续环节也写完。\n"
        "- 必须写成可视化场景（行动/对话/观察），避免用总结性叙述把过程带过。\n"
        "- 角色动机与信息必须在场景中自然落地：读者能看出‘他为什么这么做’与‘他凭什么这么做’。\n"
        "- 若涉及冲突升级：优先用“代价递增”（暴露、损失、人情债、误会扩大），而不是直接用更大的结果跳级。"
    )


def process_chapter_suggestions_block(
    chapter_no: int, framework_json: str, memory_json: str
) -> str:
    """
    插章建议：在不改主线结果的前提下，自动建议“准备/阻碍/善后”三类过程章素材，
    帮助把一个大事件自然拆成多章而不注水。
    """
    arc = _select_arc_for_chapter(framework_json, chapter_no)
    title = ""
    if isinstance(arc, dict):
        title = str(arc.get("title") or arc.get("name") or "").strip()

    active_op: list[str] = []
    try:
        mem = json.loads(memory_json or "{}")
        if isinstance(mem, dict):
            op = mem.get("open_plots") or mem.get("open_plots_hot")
            if isinstance(op, list):
                active_op = [str(x).strip() for x in op if str(x).strip()][:10]
            elif isinstance(op, str) and op.strip():
                active_op = [op.strip()]
    except Exception:
        active_op = []

    lines: list[str] = [
        "【过程章素材（用于降速但不拖沓）】",
        "- 你可以在不改变主线终点的前提下，把本章写成以下任一类型（选其一即可）：",
        "  1) 准备章：谈条件/踩点/试探/立规矩/建立临时同盟（目标更具体，风险更可见）",
        "  2) 阻碍章：资源不够/规则卡住/误会扩大/对手先手（本章以失败或半成功收束）",
        "  3) 善后章：复盘/追责/疗伤/补漏洞/名声与代价落地（为下一章埋钩子）",
        "- 默认优先写“阻碍章”，它最能自然拉长节奏且不水。",
        "- 本章至少出现一个可量化的变化：获得/失去/承诺/暴露/关系转冷或转热。",
    ]
    if title:
        lines.insert(1, f"- 当前弧线：{title}")
    if active_op:
        lines.append("- 可直接承接的 open_plots（挑 1 条写‘推进但不收束’）：")
        for i, x in enumerate(active_op[:6], 1):
            lines.append(f"  {i}. {x[:180]}")
    return "\n".join(lines)


def format_continuity_excerpts(
    db: Session, novel_id: str, *, approved_only: bool = False
) -> str:
    """倒数两章结尾：再前一章约 1200 字 + 上一章约 2500 字，总长约上限 4200。"""
    q = db.query(Chapter).filter(Chapter.novel_id == novel_id)
    if approved_only:
        q = q.filter(Chapter.status == "approved")
    rows = q.order_by(Chapter.chapter_no.desc()).limit(2).all()
    if not rows:
        return "（首章：尚无已写章节，请从已确认框架起笔，自然开篇。）"
    parts: list[str] = []
    if len(rows) >= 2:
        ch_last, ch_prev = rows[0], rows[1]
        if ch_prev.content:
            ex = ch_prev.content[-1200:]
            parts.append(
                f"【再前一章（第{ch_prev.chapter_no}章《{ch_prev.title}》）结尾摘录】\n{ex}"
            )
        if ch_last.content:
            ex = ch_last.content[-2500:]
            parts.append(
                f"【紧接上一章（第{ch_last.chapter_no}章《{ch_last.title}》）结尾摘录】\n{ex}"
            )
    else:
        ch = rows[0]
        if ch.content:
            parts.append(
                f"【上一章（第{ch.chapter_no}章《{ch.title}》）结尾摘录】\n{ch.content[-2500:]}"
            )
    text = "\n\n".join(parts)
    if len(text) > 4200:
        text = text[-4200:]
    return text if text.strip() else "（前文为空，请从框架起笔。）"


def format_recent_approved_fulltext_context(
    db: Session, novel_id: str, *, max_chapters: int = 5, per_chapter_max_chars: int = 12000
) -> str:
    """
    最近已审定章节“完整正文”上下文（带安全上限），用于增强长程衔接。
    """
    rows = (
        db.query(Chapter)
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .order_by(Chapter.chapter_no.desc())
        .limit(max_chapters)
        .all()
    )
    if not rows:
        return ""
    chunks: list[str] = ["【最近已审定章节完整正文（增强衔接）】"]
    total_chars = len(chunks[0])
    for ch in reversed(rows):
        content = (ch.content or "").strip()
        if not content:
            continue
        if len(content) > per_chapter_max_chars:
            content = content[-per_chapter_max_chars:]
        chunk = f"第{ch.chapter_no}章《{ch.title}》\n{content}"
        total_chars += len(chunk)
        if total_chars > settings.novel_recent_full_context_total_chars:
            remaining = settings.novel_recent_full_context_total_chars - (total_chars - len(chunk))
            if remaining <= 200:
                continue
            chunk = chunk[-remaining:]
            total_chars = settings.novel_recent_full_context_total_chars
        chunks.append(chunk)
    return "\n\n".join(chunks) if len(chunks) > 1 else ""


def format_volume_progress_anchor(
    db: Session,
    novel_id: str,
    chapter_no: int,
    framework_json: str,
) -> str:
    """
    卷进度锚点：显示当前章节在卷内的位置、在整个大纲弧中的节拍位置。

    解决"章节不知道自己在哪里"的问题，让LLM明确知道：
    - 当前是卷的第几章/共几章
    - 当前处于大纲弧的什么位置（起/承/转/合）
    - 距离下一个关键节点还有多少章
    """
    from app.models.volume import NovelVolume, NovelChapterPlan

    # 找到当前章节所属的卷
    volume = (
        db.query(NovelVolume)
        .filter(
            NovelVolume.novel_id == novel_id,
            NovelVolume.from_chapter <= chapter_no,
            NovelVolume.to_chapter >= chapter_no,
        )
        .first()
    )

    if not volume:
        return "【卷进度锚点】当前章节暂未归属任何卷"

    vol_index = chapter_no - volume.from_chapter + 1
    vol_total = volume.to_chapter - volume.from_chapter + 1
    vol_progress_pct = int((vol_index / max(1, vol_total)) * 100)

    # 获取已完成的章节计划数
    completed_plans = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.novel_id == novel_id,
            NovelChapterPlan.volume_id == volume.id,
            NovelChapterPlan.chapter_no < chapter_no,
        )
        .count()
    )

    # 确定当前在大纲弧中的位置
    arc = _select_arc_for_chapter(framework_json, chapter_no)
    arc_position = "未知"
    arc_phase = ""
    next_milestone = ""

    if arc:
        arc_title = str(arc.get("title") or arc.get("name") or "当前大纲弧").strip()
        lo = _parse_int(arc.get("from_chapter") or arc.get("from"))
        hi = _parse_int(arc.get("to_chapter") or arc.get("to"))

        if lo and hi:
            arc_index = chapter_no - lo + 1
            arc_total = hi - lo + 1
            arc_pct = int((arc_index / max(1, arc_total)) * 100)

            # 确定三幕位置
            if arc_pct <= 25:
                arc_phase = "起（设定/引入）"
            elif arc_pct <= 50:
                arc_phase = "承（发展/复杂化）"
            elif arc_pct <= 75:
                arc_phase = "转（危机/转折）"
            else:
                arc_phase = "合（高潮/收束）"

            arc_position = f"第{arc_index}章/共{arc_total}章（{arc_pct}%）"

            # 找出下一个关键节点
            beats = arc.get("beats") or arc.get("outline")
            if isinstance(beats, list) and beats:
                # 估算当前应执行的节拍
                beat_idx = int((arc_index / max(1, arc_total)) * len(beats))
                beat_idx = max(0, min(len(beats) - 1, beat_idx))
                remaining = len(beats) - beat_idx - 1
                if remaining > 0:
                    next_beat = beats[beat_idx + 1]
                    if isinstance(next_beat, dict):
                        next_milestone = str(next_beat.get("title") or next_beat.get("goal", "下一个节拍"))
                    elif isinstance(next_beat, str):
                        next_milestone = next_beat[:100]
                else:
                    next_milestone = "本章弧即将收束"

    lines = [
        "【卷进度锚点（位置感知）】",
        f"- 当前位置：第{chapter_no}章",
        f"- 所属卷：{volume.title}（第{vol_index}章/共{vol_total}章，{vol_progress_pct}%）",
        f"- 卷内已完成章节数：{completed_plans}",
        f"- 大纲弧位置：{arc_position} - {arc_phase}",
    ]

    if next_milestone:
        lines.append(f"- 下一关键节点：{next_milestone}")

    # 添加进度限制提示
    lines.append("")
    if arc_phase == "起":
        lines.append("【当前阶段限制】只允许：引入冲突/建立关系/埋下伏笔，禁止提前解决")
    elif arc_phase == "承":
        lines.append("【当前阶段限制】只允许：推进尝试/遭遇阻碍/代价升级，禁止直达目标")
    elif arc_phase == "转":
        lines.append("【当前阶段限制】只允许：危机爆发/意外反转/关系破裂，禁止顺利收场")
    else:
        lines.append("【当前阶段限制】允许收束，但需为新卷留下钩子，禁止一次性清完所有线索")

    return "\n".join(lines)


def format_volume_event_summary(
    db: Session,
    novel_id: str,
    current_chapter_no: int,
    max_events: int = 8,
) -> str:
    """
    卷级事件摘要：基于当前卷已写章节，生成事件级别的摘要（而非摘录）。

    解决"只有摘录，没有整体卷上下文"的问题。
    通过 NovelChapterPlan 获取已写章节的事件摘要。
    """
    from app.models.volume import NovelVolume, NovelChapterPlan

    # 找到当前卷
    volume = (
        db.query(NovelVolume)
        .filter(
            NovelVolume.novel_id == novel_id,
            NovelVolume.from_chapter <= current_chapter_no,
            NovelVolume.to_chapter >= current_chapter_no,
        )
        .first()
    )

    if not volume:
        return "【卷事件摘要】当前章节暂未归属任何卷"

    # 获取当前卷中已写章节（< current_chapter_no）的计划
    plans = (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.novel_id == novel_id,
            NovelChapterPlan.volume_id == volume.id,
            NovelChapterPlan.chapter_no < current_chapter_no,
        )
        .order_by(NovelChapterPlan.chapter_no.asc())
        .limit(max_events)
        .all()
    )

    if not plans:
        return f"【卷事件摘要】本卷（{volume.title}）尚无已写章节，本章为开篇章节"

    lines = [
        f"【卷事件摘要 - {volume.title}（最近{len(plans)}章）】",
        f"本卷范围：第{volume.from_chapter}章 至 第{volume.to_chapter}章",
        "",
        "=== 已发生的关键事件 ===",
    ]

    for plan in plans:
        try:
            beats = json.loads(plan.beats_json or "{}")
        except json.JSONDecodeError:
            beats = {}
        beats = normalize_beats_to_v2(beats)

        goal = chapter_plan_goal(beats)
        turn = chapter_plan_turn(beats)

        event_desc = ""
        if turn:
            event_desc = f"{goal} → {turn}" if goal else turn
        elif goal:
            event_desc = goal
        else:
            event_desc = plan.chapter_title or f"第{plan.chapter_no}章"

        lines.append(f"  · 第{plan.chapter_no}章：{event_desc}")

    # 添加卷级累积状态
    lines.append("")
    lines.append("=== 卷级累积状态（承接本章时必须保持一致）===")

    # 从 beats 中提取进展
    all_added_plots: list[str] = []
    all_resolved_plots: list[str] = []

    for plan in plans:
        try:
            added = json.loads(plan.open_plots_intent_added_json or "[]")
            resolved = json.loads(plan.open_plots_intent_resolved_json or "[]")
            if isinstance(added, list):
                all_added_plots.extend([str(x) for x in added if x])
            if isinstance(resolved, list):
                all_resolved_plots.extend([str(x) for x in resolved if x])
        except json.JSONDecodeError:
            continue

    # 计算当前活跃的 plots
    active_plots = [p for p in all_added_plots if p not in all_resolved_plots]
    resolved_in_vol = [p for p in all_resolved_plots if p in all_added_plots]

    if active_plots:
        lines.append("当前活跃线索（须在后续章节中保持或收束）：")
        for p in active_plots[-5:]:
            lines.append(f"  · {p}")
    else:
        lines.append("当前无活跃线索")

    if resolved_in_vol:
        lines.append("")
        lines.append("本卷已收束线索（禁止重复收束）：")
        for p in resolved_in_vol[-3:]:
            lines.append(f"  ✓ {p}")

    return "\n".join(lines)


def hot_memory_bullets_preview(memory_json: str, max_items: int = 20) -> str:
    """
    生成“热记忆”文本预览（项目符号），用于调试/展示。

    注意：写章 prompt 使用的是上方同名的 `build_hot_memory_for_prompt(...)`（热层 JSON），
    这里保留为单独函数以避免覆盖其签名。
    """
    try:
        data = json.loads(memory_json or "{}")
    except json.JSONDecodeError:
        return ""

    if not isinstance(data, dict):
        return ""

    hot = data.get("canonical_timeline_hot")
    if isinstance(hot, list) and hot:
        items = [str(x).strip() for x in hot if str(x).strip()]
        return "\n".join(f"  · {x}" for x in items[:max_items])

    full = data.get("canonical_timeline")
    if isinstance(full, list) and full:
        items = [str(x).strip() for x in full if str(x).strip()]
        return "\n".join(f"  · {x}" for x in items[-max_items:])

    parts: list[str] = []
    chars = data.get("characters")
    if isinstance(chars, list) and chars:
        parts.append("【角色状态】")
        for c in chars[:10]:
            if isinstance(c, dict):
                name = c.get("name", "")
                status = c.get("status", "")
                if name:
                    parts.append(f"  · {name}: {status}")

    open_plots = data.get("open_plots") or data.get("open_plots_hot")
    if isinstance(open_plots, list) and open_plots:
        parts.append("【活跃线索】")
        for p in open_plots[:10]:
            parts.append(f"  · {p}")

    return "\n".join(parts)


def format_constraints_block(db: Session, novel_id: str) -> str:
    """从 outline.forbidden_constraints 生成设定防火墙提示块。"""
    outline = db.get(NovelMemoryNormOutline, novel_id)
    if not outline:
        return ""
    raw = getattr(outline, "forbidden_constraints_json", None) or "[]"
    try:
        fc = json.loads(raw)
    except json.JSONDecodeError:
        fc = []
    if not isinstance(fc, list) or not fc:
        return ""
    lines = ["【设定防火墙（正文禁止违反）】"]
    for i, x in enumerate(fc[:24], 1):
        if isinstance(x, dict):
            body = str(x.get("body") or "").strip()
            iid = x.get("id")
            if body:
                id_tag = f"[{iid}] " if iid else ""
                lines.append(f"  {i}. {id_tag}{body[:400]}")
        else:
            s = str(x).strip()
            if s:
                lines.append(f"  {i}. {s[:400]}")
    return "\n".join(lines)


def format_volume_memory_context_block(
    db: Session, novel_id: str, chapter_no: int
) -> str:
    """当前卷范围与卷摘要，作为层级记忆注入。"""
    if chapter_no <= 0:
        return ""
    volume = (
        db.query(NovelVolume)
        .filter(
            NovelVolume.novel_id == novel_id,
            NovelVolume.from_chapter <= chapter_no,
            NovelVolume.to_chapter >= chapter_no,
        )
        .first()
    )
    if not volume:
        return ""
    idx = chapter_no - volume.from_chapter + 1
    total = max(1, volume.to_chapter - volume.from_chapter + 1)
    lines = [
        "【本卷层级上下文】",
        f"- 第{volume.volume_no}卷《{volume.title}》：卷内第{idx}/{total}章（全书第{chapter_no}章）",
    ]
    if (volume.summary or "").strip():
        lines.append(f"- 卷摘要：{volume.summary.strip()[:800]}")
    return "\n".join(lines)


def format_chapter_continuity_bridge_from_db(
    db: Session, novel_id: str, chapter_no: int
) -> str:
    """上一章情绪与章末悬念，强制下一章承接。"""
    if chapter_no <= 1:
        return ""
    prev = (
        db.query(NovelMemoryNormChapter)
        .filter(
            NovelMemoryNormChapter.novel_id == novel_id,
            NovelMemoryNormChapter.chapter_no == chapter_no - 1,
        )
        .first()
    )
    if not prev:
        return ""
    hooks = json.loads(getattr(prev, "unresolved_hooks_json", None) or "[]")
    emotional = (getattr(prev, "emotional_state", None) or "").strip()
    title = (prev.chapter_title or "").strip()
    lines = [
        "【上一章衔接桥梁（必须承接）】",
        f"- 上一章：第{chapter_no - 1}章" + (f"《{title}》" if title else ""),
    ]
    if emotional:
        lines.append(f"- 情绪/基调锚点：{emotional[:500]}")
    if isinstance(hooks, list) and hooks:
        lines.append("- 章末未解悬念/钩子：")
        for h in hooks[:12]:
            hs = str(h).strip()
            if hs:
                lines.append(f"  · {hs[:240]}")
    return "\n".join(lines)


def _norm_active(obj: Any) -> bool:
    v = getattr(obj, "is_active", True)
    return True if v is None else bool(v)


def _norm_influence(obj: Any) -> int:
    try:
        return int(getattr(obj, "influence_score", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _detail_json(obj: Any) -> dict[str, Any]:
    raw = getattr(obj, "detail_json", None) or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _entity_aliases(obj: Any) -> list[str]:
    return extract_aliases(_detail_json(obj))


def _plot_is_stale(plot: Any, latest_chapter_no: int) -> bool:
    est = max(0, int(getattr(plot, "estimated_duration", 0) or 0))
    if est <= 0 or latest_chapter_no <= 0:
        return False
    touched = max(
        int(getattr(plot, "last_touched_chapter", 0) or 0),
        int(getattr(plot, "introduced_chapter", 0) or 0),
    )
    if touched <= 0:
        return False
    return (latest_chapter_no - touched) > (est + settings.novel_open_plot_stale_grace_chapters)


def build_memory_schema_guide() -> dict[str, Any]:
    return memory_schema_guide()


def build_memory_health_summary(db: Session, novel_id: str) -> dict[str, Any]:
    latest_chapter_no = (
        db.query(func.max(NovelMemoryNormChapter.chapter_no))
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .scalar()
        or 0
    )
    plots = (
        db.query(NovelMemoryNormPlot)
        .filter(NovelMemoryNormPlot.novel_id == novel_id)
        .order_by(NovelMemoryNormPlot.priority.desc(), NovelMemoryNormPlot.sort_order.asc())
        .all()
    )
    stale: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    for p in plots:
        est = int(getattr(p, "estimated_duration", 0) or 0)
        touched = max(
            int(getattr(p, "last_touched_chapter", 0) or 0),
            int(getattr(p, "introduced_chapter", 0) or 0),
        )
        if est <= 0 or touched <= 0 or latest_chapter_no <= 0:
            continue
        exceeded = latest_chapter_no - touched - est
        row = {
            "body": p.body,
            "plot_type": getattr(p, "plot_type", "Transient") or "Transient",
            "priority": getattr(p, "priority", 0) or 0,
            "estimated_duration": est,
            "introduced_chapter": getattr(p, "introduced_chapter", 0) or 0,
            "last_touched_chapter": getattr(p, "last_touched_chapter", 0) or 0,
            "current_stage": getattr(p, "current_stage", "") or "",
            "resolve_when": getattr(p, "resolve_when", "") or "",
            "overdue_chapters": max(0, exceeded),
        }
        if exceeded > 0:
            overdue.append(row)
        if _plot_is_stale(p, latest_chapter_no):
            stale.append(row)
    return {
        "latest_chapter_no": latest_chapter_no,
        "stale_plots": stale[:12],
        "overdue_plots": overdue[:12],
    }


def build_hot_memory_from_db(
    db: Session,
    novel_id: str,
    *,
    timeline_hot_n: int = 20,
    open_plots_hot_max: int = 20,
    characters_hot_max: int = 12,
    chapter_no: int | None = None,
) -> str:
    """
    从规范化表构建“热层”记忆 JSON，用于注入 LLM Prompt。
    """
    outline = db.get(NovelMemoryNormOutline, novel_id)
    if not outline:
        return "{}"
    latest_chapter_no = (
        db.query(func.max(NovelMemoryNormChapter.chapter_no))
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .scalar()
        or 0
    )

    # 1. 最近时间线
    timeline_entries = (
        db.query(NovelMemoryNormChapter)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .order_by(NovelMemoryNormChapter.chapter_no.desc())
        .limit(timeline_hot_n)
        .all()
    )
    timeline_hot = []
    for entry in reversed(timeline_entries):
        timeline_hot.append({
            "chapter_no": entry.chapter_no,
            "chapter_title": entry.chapter_title,
            "key_facts": json.loads(entry.key_facts_json or "[]"),
            "causal_results": json.loads(entry.causal_results_json or "[]"),
            "open_plots_added": json.loads(entry.open_plots_added_json or "[]"),
            "open_plots_resolved": json.loads(entry.open_plots_resolved_json or "[]"),
            "emotional_state": (getattr(entry, "emotional_state", None) or "")[:500],
            "unresolved_hooks": json.loads(
                getattr(entry, "unresolved_hooks_json", None) or "[]"
            ),
        })

    # 2. 活跃线索（优先高 priority / 核心线）
    plots = (
        db.query(NovelMemoryNormPlot)
        .filter(NovelMemoryNormPlot.novel_id == novel_id)
        .order_by(
            NovelMemoryNormPlot.priority.desc(),
            NovelMemoryNormPlot.sort_order.asc(),
        )
        .limit(open_plots_hot_max)
        .all()
    )
    open_plots_hot = []
    for p in plots:
        item: dict[str, Any] = {
            "body": p.body,
            "plot_type": getattr(p, "plot_type", None) or "Transient",
            "priority": getattr(p, "priority", 0) or 0,
            "estimated_duration": getattr(p, "estimated_duration", 0) or 0,
        }
        current_stage = str(getattr(p, "current_stage", "") or "").strip()
        resolve_when = str(getattr(p, "resolve_when", "") or "").strip()
        if current_stage:
            item["current_stage"] = current_stage[:240]
        if resolve_when:
            item["resolve_when"] = resolve_when[:240]
        introduced_chapter = getattr(p, "introduced_chapter", 0) or 0
        last_touched = getattr(p, "last_touched_chapter", 0) or 0
        if introduced_chapter:
            item["introduced_chapter"] = introduced_chapter
        if last_touched:
            item["last_touched_chapter"] = last_touched
        if _plot_is_stale(p, latest_chapter_no):
            item["is_stale"] = True
        open_plots_hot.append(item)

    # 3. 角色状态（影响力优先 + 仅活跃）
    chars = (
        db.query(NovelMemoryNormCharacter)
        .filter(
            NovelMemoryNormCharacter.novel_id == novel_id,
            NovelMemoryNormCharacter.is_active.is_(True),
        )
        .order_by(
            NovelMemoryNormCharacter.influence_score.desc(),
            NovelMemoryNormCharacter.sort_order.asc(),
        )
        .limit(characters_hot_max)
        .all()
    )
    characters_hot = []
    for c in chars:
        characters_hot.append({
            "name": c.name,
            "role": c.role,
            "traits": json.loads(c.traits_json or "[]"),
            "state": c.status,
            "aliases": _entity_aliases(c),
            "influence_score": _norm_influence(c),
        })

    # 4. 关系
    rels = (
        db.query(NovelMemoryNormRelation)
        .filter(NovelMemoryNormRelation.novel_id == novel_id)
        .order_by(NovelMemoryNormRelation.sort_order.asc())
        .limit(10)
        .all()
    )
    relations_hot = [{"from": r.src, "to": r.dst, "relation": r.relation} for r in rels]

    # 5. 物品与技能（影响力优先 + 仅活跃）
    inventory_items = (
        db.query(NovelMemoryNormItem)
        .filter(
            NovelMemoryNormItem.novel_id == novel_id,
            NovelMemoryNormItem.is_active.is_(True),
        )
        .order_by(
            NovelMemoryNormItem.influence_score.desc(),
            NovelMemoryNormItem.sort_order.asc(),
        )
        .limit(12)
        .all()
    )
    inventory_hot = []
    for item in inventory_items:
        inv = {"label": item.label, "influence_score": _norm_influence(item)}
        aliases = _entity_aliases(item)
        if aliases:
            inv["aliases"] = aliases
        inventory_hot.append(inv)

    skills_objs = (
        db.query(NovelMemoryNormSkill)
        .filter(
            NovelMemoryNormSkill.novel_id == novel_id,
            NovelMemoryNormSkill.is_active.is_(True),
        )
        .order_by(
            NovelMemoryNormSkill.influence_score.desc(),
            NovelMemoryNormSkill.sort_order.asc(),
        )
        .limit(8)
        .all()
    )
    skills_hot = []
    for s in skills_objs:
        item = {"name": s.name}
        detail = _detail_json(s)
        if detail.get("description"):
            item["description"] = detail["description"]
        if detail.get("status") or detail.get("cost"):
            item["status"] = detail.get("status") or detail.get("cost")
        aliases = _entity_aliases(s)
        if aliases:
            item["aliases"] = aliases
        item["influence_score"] = _norm_influence(s)
        skills_hot.append(item)

    pets_objs = (
        db.query(NovelMemoryNormPet)
        .filter(
            NovelMemoryNormPet.novel_id == novel_id,
            NovelMemoryNormPet.is_active.is_(True),
        )
        .order_by(
            NovelMemoryNormPet.influence_score.desc(),
            NovelMemoryNormPet.sort_order.asc(),
        )
        .limit(6)
        .all()
    )
    pets_hot = []
    for p in pets_objs:
        item = {"name": p.name, **_detail_json(p), "influence_score": _norm_influence(p)}
        aliases = _entity_aliases(p)
        if aliases:
            item["aliases"] = aliases
        pets_hot.append(item)

    hot_payload: dict[str, Any] = {
        "forbidden_constraints_hot": json.loads(
            getattr(outline, "forbidden_constraints_json", None) or "[]"
        )[:12],
        "main_plot_hot": (outline.main_plot or "")[:240],
        "open_plots_hot": open_plots_hot,
        "canonical_timeline_hot": timeline_hot,
        "characters_hot": characters_hot,
        "relations_hot": relations_hot,
        "inventory_hot": inventory_hot,
        "skills_hot": skills_hot,
        "pets_hot": pets_hot,
        "timeline_archive_summary": json.loads(outline.timeline_archive_json or "[]")[:6],
    }
    if chapter_no is not None and chapter_no > 0:
        vc = format_volume_memory_context_block(db, novel_id, chapter_no)
        if vc:
            hot_payload["volume_context_text"] = vc
    return json.dumps(hot_payload, ensure_ascii=False)


def format_open_plots_from_db(db: Session, novel_id: str) -> str:
    latest_chapter_no = (
        db.query(func.max(NovelMemoryNormChapter.chapter_no))
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .scalar()
        or 0
    )
    plots = (
        db.query(NovelMemoryNormPlot)
        .filter(NovelMemoryNormPlot.novel_id == novel_id)
        .order_by(
            NovelMemoryNormPlot.priority.desc(),
            NovelMemoryNormPlot.sort_order.asc(),
        )
        .limit(24)
        .all()
    )
    if not plots:
        return ""
    lines = ["【须承接的未完结剧情线（open_plots）】"]
    for i, p in enumerate(plots, 1):
        meta = ""
        pt = getattr(p, "plot_type", None) or ""
        if pt and str(pt).strip() and str(pt) != "Transient":
            meta += f"[{pt}]"
        pr = getattr(p, "priority", 0) or 0
        if pr:
            meta += f"[prio={pr}]"
        est = getattr(p, "estimated_duration", 0) or 0
        if est:
            meta += f"[约{est}章]"
        if _plot_is_stale(p, latest_chapter_no):
            meta += "[stale]"
        body = p.body
        current_stage = str(getattr(p, "current_stage", "") or "").strip()
        resolve_when = str(getattr(p, "resolve_when", "") or "").strip()
        if current_stage:
            body += f"｜当前阶段：{current_stage[:120]}"
        if resolve_when:
            body += f"｜收束条件：{resolve_when[:120]}"
        lines.append(f"  {i}. {meta}{body}" if meta else f"  {i}. {body}")
    return "\n".join(lines)


def format_canonical_timeline_from_db(db: Session, novel_id: str, chapter_no: int) -> str:
    """从规范化表提取时间线硬约束。"""
    entries = (
        db.query(NovelMemoryNormChapter)
        .filter(
            NovelMemoryNormChapter.novel_id == novel_id,
            NovelMemoryNormChapter.chapter_no < chapter_no
        )
        .order_by(NovelMemoryNormChapter.chapter_no.desc())
        .limit(6)
        .all()
    )
    if not entries:
        return ""

    lines = ["【规范时间线账本（canonical_timeline）硬约束】"]
    for i, x in enumerate(reversed(entries), 1):
        head = f"  {i}. 第{x.chapter_no}章" + (f"《{x.chapter_title}》" if x.chapter_title else "")
        lines.append(head)
        
        key_facts = json.loads(x.key_facts_json or "[]")
        if key_facts:
            lines.append("     关键事实：" + "；".join(str(k) for k in key_facts[:8]))
            
        causal_results = json.loads(x.causal_results_json or "[]")
        if causal_results:
            lines.append("     因果结果：" + "；".join(str(c) for c in causal_results[:6]))
            
        added = json.loads(x.open_plots_added_json or "[]")
        if added:
            lines.append("     新增未完结线：" + "；".join(str(a) for a in added[:6]))
            
        resolved = json.loads(x.open_plots_resolved_json or "[]")
        if resolved:
            lines.append("     已收束/解决线：" + "；".join(str(r) for r in resolved[:6]))
            
    return "\n".join(lines)


def format_entity_recall_from_db(
    db: Session,
    novel_id: str,
    query_text: str,
    *,
    max_items: int = 6,
) -> str:
    """基于数据库检索召回相关实体（影响力优先、仅活跃实体）。"""
    query = (query_text or "").strip()
    if not query:
        return ""

    lines = ["【与本章最相关的记忆召回】"]
    matched_terms: list[str] = []

    # 1. 检索角色
    chars = (
        db.query(NovelMemoryNormCharacter)
        .filter(
            NovelMemoryNormCharacter.novel_id == novel_id,
            NovelMemoryNormCharacter.is_active.is_(True),
        )
        .all()
    )
    relevant_chars = [
        c
        for c in chars
        if c.name in query or any(alias in query for alias in _entity_aliases(c))
    ]
    for c in relevant_chars:
        if c.name not in matched_terms:
            matched_terms.append(c.name)
        for alias in _entity_aliases(c):
            if alias in query and alias not in matched_terms:
                matched_terms.append(alias)
    relevant_chars.sort(key=lambda x: (-_norm_influence(x), x.name))

    if relevant_chars:
        lines.append("相关人物：")
        for c in relevant_chars[:max_items]:
            inf = _norm_influence(c)
            tag = f"｜影响力:{inf}" if inf else ""
            lines.append(
                f"- {c.name}{tag}"
                + (f"｜身份：{c.role[:80]}" if c.role else "")
                + (f"｜当前状态：{c.status[:140]}" if c.status else "")
                + (
                    f"｜别名：{'、'.join(_entity_aliases(c)[:4])}"
                    if _entity_aliases(c)
                    else ""
                )
            )

    # 2. 检索关系 (基于匹配的角色)
    if matched_terms:
        rels = (
            db.query(NovelMemoryNormRelation)
            .filter(
                NovelMemoryNormRelation.novel_id == novel_id,
                or_(
                    NovelMemoryNormRelation.src.in_(matched_terms),
                    NovelMemoryNormRelation.dst.in_(matched_terms),
                ),
            )
            .limit(max_items)
            .all()
        )
        if rels:
            lines.append("相关关系：")
            for r in rels:
                lines.append(f"- {r.src} -> {r.dst}：{r.relation[:140]}")

    # 3. 检索物品
    items = (
        db.query(NovelMemoryNormItem)
        .filter(
            NovelMemoryNormItem.novel_id == novel_id,
            NovelMemoryNormItem.is_active.is_(True),
        )
        .all()
    )
    relevant_items = [
        it
        for it in items
        if it.label in query
        or any(t in it.label for t in matched_terms)
        or any(alias in query for alias in _entity_aliases(it))
    ]
    relevant_items.sort(key=lambda x: (-_norm_influence(x), x.label))
    if relevant_items:
        lines.append("相关物品：")
        for it in relevant_items[:max_items]:
            alias_text = "、".join(_entity_aliases(it)[:4])
            lines.append(
                f"- {it.label[:160]}" + (f"｜别名：{alias_text}" if alias_text else "")
            )

    # 4. 检索技能与宠物
    skills = (
        db.query(NovelMemoryNormSkill)
        .filter(
            NovelMemoryNormSkill.novel_id == novel_id,
            NovelMemoryNormSkill.is_active.is_(True),
        )
        .all()
    )
    relevant_skills = [
        s
        for s in skills
        if s.name in query
        or any(t in s.name for t in matched_terms)
        or any(alias in query for alias in _entity_aliases(s))
    ]
    relevant_skills.sort(key=lambda x: (-_norm_influence(x), x.name))
    if relevant_skills:
        lines.append("相关技能：")
        for s in relevant_skills[:max_items]:
            alias_text = "、".join(_entity_aliases(s)[:4])
            lines.append(f"- {s.name}" + (f"｜别名：{alias_text}" if alias_text else ""))

    pets = (
        db.query(NovelMemoryNormPet)
        .filter(
            NovelMemoryNormPet.novel_id == novel_id,
            NovelMemoryNormPet.is_active.is_(True),
        )
        .all()
    )
    relevant_pets = [
        p
        for p in pets
        if p.name in query
        or any(t in p.name for t in matched_terms)
        or any(alias in query for alias in _entity_aliases(p))
    ]
    relevant_pets.sort(key=lambda x: (-_norm_influence(x), x.name))
    if relevant_pets:
        lines.append("相关同伴/宠物：")
        for p in relevant_pets[:max_items]:
            alias_text = "、".join(_entity_aliases(p)[:4])
            lines.append(f"- {p.name}" + (f"｜别名：{alias_text}" if alias_text else ""))

    # 5. 检索历史事实 (关键词匹配)
    chapters = (
        db.query(NovelMemoryNormChapter)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .all()
    )
    matched_events = []
    query_tokens = [t for t in re.split(r"[，、：:；。,. ]", query) if len(t) >= 2]
    for ch in chapters:
        kf = json.loads(ch.key_facts_json or "[]")
        cr = json.loads(ch.causal_results_json or "[]")
        combined = " ".join(str(x) for x in kf + cr)
        if any(term in combined for term in matched_terms) or any(
            t in combined for t in query_tokens
        ):
            snippet = "；".join(
                [str(x).strip() for x in [*kf[:2], *cr[:1]] if str(x).strip()]
            )
            matched_events.append(f"- 第{ch.chapter_no}章：{snippet[:180]}")
            if len(matched_events) >= max_items:
                break
    if matched_events:
        lines.append("相关历史事实：")
        lines.extend(matched_events)

    return "\n".join(lines) if len(lines) > 1 else ""


def format_cold_recall_from_db(db: Session, novel_id: str, *, max_items: int = 5) -> str:
    outline = db.get(NovelMemoryNormOutline, novel_id)
    if not outline:
        return ""

    lines = ["【冷层历史召回（按需）】"]
    
    # 抽取较早的章节摘要
    chapters = (
        db.query(NovelMemoryNormChapter)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .order_by(NovelMemoryNormChapter.chapter_no.asc())
        .limit(max_items) # 这里只是示例，实际可能需要更复杂的逻辑选“冷层”
        .all()
    )
    if chapters:
        lines.append("较早历史条目：")
        for i, ch in enumerate(chapters, 1):
            kf = json.loads(ch.key_facts_json or "[]")
            key_text = "；".join(str(v) for v in kf[:2] if str(v).strip())
            lines.append(f"  {i}. 第{ch.chapter_no}章" + (f"：{key_text[:120]}" if key_text else ""))

    arch = json.loads(outline.timeline_archive_json or "[]")
    if arch:
        lines.append("阶段压缩摘要：")
        for i, x in enumerate(arch[:3], 1):
            lines.append(f"  - {str(x)[:180]}")

    return "\n".join(lines) if len(lines) > 1 else ""
