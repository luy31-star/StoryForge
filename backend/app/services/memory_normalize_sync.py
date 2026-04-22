"""
从记忆 payload JSON 同步到规范化表；每次写入 NovelMemory 新版本后调用。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
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
from app.services.memory_schema import (
    clamp_int,
    dedupe_clean_strs,
    extract_aliases,
    normalize_plot_type,
)


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


def _dedupe_chapters_by_no(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_no: dict[int, dict[str, Any]] = {}
    for item in entries:
        cn = item.get("chapter_no")
        if isinstance(cn, str) and cn.strip().isdigit():
            cn = int(cn.strip())
        if not isinstance(cn, int) or cn <= 0:
            continue
        prev = by_no.get(cn)
        if prev is None:
            by_no[cn] = dict(item)
        else:
            merged = dict(prev)
            merged.update(item)
            by_no[cn] = merged
    return [by_no[k] for k in sorted(by_no.keys())]


def _json_list(val: Any) -> str:
    if val is None:
        return "[]"
    if isinstance(val, str):
        return json.dumps([val], ensure_ascii=False)
    if isinstance(val, list):
        return json.dumps(val, ensure_ascii=False)
    return json.dumps([str(val)], ensure_ascii=False)


def _parse_influence_active(item: dict[str, Any]) -> tuple[int, bool]:
    inf = clamp_int(item.get("influence_score"), minimum=0, maximum=100, default=0)
    active = item.get("is_active")
    is_active = True if active is None else bool(active)
    return inf, is_active


def _inventory_label_from_detail(item: dict[str, Any]) -> str:
    for key in ("item_name", "name", "item", "label", "title"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _skill_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("skills")
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            inf, is_active = _parse_influence_active(item)
            introduced_chapter = coerce_int(item.get("introduced_chapter"), default=0)
            last_used_chapter = coerce_int(item.get("last_used_chapter"), default=0)
            expired_raw = item.get("expired_chapter")
            expired_chapter = coerce_int(expired_raw, default=0) if expired_raw is not None else None
            rest = {
                k: v
                for k, v in item.items()
                if k not in ("name", "influence_score", "is_active", "introduced_chapter", "last_used_chapter", "expired_chapter")
            }
            out.append(
                {
                    "sort_order": i,
                    "name": name or f"技能{i + 1}",
                    "detail_json": json.dumps(rest, ensure_ascii=False),
                    "influence_score": inf,
                    "is_active": is_active,
                    "introduced_chapter": introduced_chapter,
                    "last_used_chapter": last_used_chapter,
                    "expired_chapter": expired_chapter,
                }
            )
        else:
            s = str(item or "").strip()
            if s:
                out.append(
                    {
                        "sort_order": i,
                        "name": s,
                        "detail_json": "{}",
                        "influence_score": 0,
                        "is_active": True,
                        "introduced_chapter": 0,
                        "last_used_chapter": 0,
                        "expired_chapter": None,
                    }
                )
    return out


def _item_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("inventory")
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            name = _inventory_label_from_detail(item)
            inf, is_active = _parse_influence_active(item)
            introduced_chapter = coerce_int(item.get("introduced_chapter"), default=0)
            last_used_chapter = coerce_int(item.get("last_used_chapter"), default=0)
            expired_raw = item.get("expired_chapter")
            expired_chapter = coerce_int(expired_raw, default=0) if expired_raw is not None else None
            rest = {
                k: v
                for k, v in item.items()
                if k not in ("influence_score", "is_active", "introduced_chapter", "last_used_chapter", "expired_chapter")
            }
            out.append(
                {
                    "sort_order": i,
                    "label": name or json.dumps(rest, ensure_ascii=False)[:200],
                    "detail_json": json.dumps(rest, ensure_ascii=False),
                    "influence_score": inf,
                    "is_active": is_active,
                    "introduced_chapter": introduced_chapter,
                    "last_used_chapter": last_used_chapter,
                    "expired_chapter": expired_chapter,
                }
            )
        else:
            s = str(item or "").strip()
            if s:
                out.append(
                    {
                        "sort_order": i,
                        "label": s,
                        "detail_json": "{}",
                        "influence_score": 0,
                        "is_active": True,
                        "introduced_chapter": 0,
                        "last_used_chapter": 0,
                        "expired_chapter": None,
                    }
                )
    return out


def _pet_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("pets")
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            inf, is_active = _parse_influence_active(item)
            rest = {
                k: v
                for k, v in item.items()
                if k not in ("name", "influence_score", "is_active")
            }
            out.append(
                {
                    "sort_order": i,
                    "name": name or f"宠物{i + 1}",
                    "detail_json": json.dumps(rest, ensure_ascii=False),
                    "influence_score": inf,
                    "is_active": is_active,
                }
            )
        else:
            s = str(item or "").strip()
            if s:
                out.append(
                    {
                        "sort_order": i,
                        "name": s,
                        "detail_json": "{}",
                        "influence_score": 0,
                        "is_active": True,
                    }
                )
    return out


def _character_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("characters")
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        traits = item.get("traits")
        traits_j = (
            json.dumps(traits, ensure_ascii=False)
            if isinstance(traits, list)
            else json.dumps([str(traits)], ensure_ascii=False)
            if traits
            else "[]"
        )
        inf, is_active = _parse_influence_active(item)
        rest = {
            k: v
            for k, v in item.items()
            if k not in ("name", "role", "status", "traits", "influence_score", "is_active")
        }
        out.append(
            {
                "sort_order": i,
                "name": name,
                "role": str(item.get("role") or ""),
                "status": str(item.get("status") or ""),
                "traits_json": traits_j,
                "detail_json": json.dumps(rest, ensure_ascii=False),
                "influence_score": inf,
                "is_active": is_active,
            }
        )
    return out


def _relation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("relations")
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        src = str(item.get("from") or "").strip()
        dst = str(item.get("to") or "").strip()
        rel = str(item.get("relation") or "").strip()
        active = item.get("is_active")
        if not (src and dst):
            continue
        out.append(
            {
                "sort_order": i,
                "src": src,
                "dst": dst,
                "relation": rel,
                "is_active": True if active is None else bool(active),
            }
        )
    return out


def _plot_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("open_plots")
    if isinstance(raw, list):
        for i, x in enumerate(raw):
            if isinstance(x, dict):
                body = str(x.get("body") or x.get("text") or "").strip()
                if not body:
                    continue
                prio = clamp_int(x.get("priority"), minimum=0, maximum=100, default=0)
                est = max(0, clamp_int(x.get("estimated_duration"), minimum=0, maximum=999, default=0))
                ptype = normalize_plot_type(x.get("plot_type"))
                out.append(
                    {
                        "sort_order": i,
                        "body": body,
                        "plot_type": ptype,
                        "priority": prio,
                        "estimated_duration": est,
                        "current_stage": str(x.get("current_stage") or "").strip(),
                        "resolve_when": str(x.get("resolve_when") or "").strip(),
                        "introduced_chapter": max(
                            0, clamp_int(x.get("introduced_chapter"), minimum=0, maximum=20000, default=0)
                        ),
                        "last_touched_chapter": max(
                            0, clamp_int(x.get("last_touched_chapter"), minimum=0, maximum=20000, default=0)
                        ),
                    }
                )
            else:
                s = str(x or "").strip()
                if s:
                    out.append(
                        {
                            "sort_order": i,
                            "body": s,
                            "plot_type": "Transient",
                            "priority": 0,
                            "estimated_duration": 0,
                            "current_stage": "",
                            "resolve_when": "",
                            "introduced_chapter": 0,
                            "last_touched_chapter": 0,
                        }
                    )
    elif isinstance(raw, str) and raw.strip():
        out.append(
            {
                "sort_order": 0,
                "body": raw.strip(),
                "plot_type": "Transient",
                "priority": 0,
                "estimated_duration": 0,
                "current_stage": "",
                "resolve_when": "",
                "introduced_chapter": 0,
                "last_touched_chapter": 0,
            }
        )
    return out


def replace_normalized_from_payload(
    db: Session,
    novel_id: str,
    memory_version: int,
    payload_json: str,
) -> None:
    """删除该小说全部规范化行后，按当前 payload 重写。"""
    try:
        data = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    for model in (
        NovelMemoryNormSkill,
        NovelMemoryNormItem,
        NovelMemoryNormPet,
        NovelMemoryNormCharacter,
        NovelMemoryNormRelation,
        NovelMemoryNormPlot,
        NovelMemoryNormChapter,
    ):
        db.query(model).filter(model.novel_id == novel_id).delete(synchronize_session=False)

    db.query(NovelMemoryNormOutline).filter(
        NovelMemoryNormOutline.novel_id == novel_id
    ).delete(synchronize_session=False)

    fc_raw = data.get("forbidden_constraints")
    if not isinstance(fc_raw, list):
        fc_raw = []
    outline = NovelMemoryNormOutline(
        novel_id=novel_id,
        memory_version=memory_version,
        main_plot=str(data.get("main_plot") or ""),
        timeline_archive_json=_json_list(data.get("timeline_archive_summary")),
        forbidden_constraints_json=json.dumps(
            [x for x in fc_raw if x],
            ensure_ascii=False,
        ),
    )
    db.add(outline)

    for row in _skill_rows(data):
        db.add(
            NovelMemoryNormSkill(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                name=row["name"],
                detail_json=row["detail_json"],
                influence_score=int(row.get("influence_score") or 0),
                is_active=bool(row.get("is_active", True)),
                introduced_chapter=int(row.get("introduced_chapter") or 0),
                last_used_chapter=int(row.get("last_used_chapter") or 0),
                expired_chapter=row.get("expired_chapter"),
            )
        )
    for row in _item_rows(data):
        db.add(
            NovelMemoryNormItem(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                label=row["label"],
                detail_json=row["detail_json"],
                influence_score=int(row.get("influence_score") or 0),
                is_active=bool(row.get("is_active", True)),
                introduced_chapter=int(row.get("introduced_chapter") or 0),
                last_used_chapter=int(row.get("last_used_chapter") or 0),
                expired_chapter=row.get("expired_chapter"),
            )
        )
    for row in _pet_rows(data):
        db.add(
            NovelMemoryNormPet(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                name=row["name"],
                detail_json=row["detail_json"],
                influence_score=int(row.get("influence_score") or 0),
                is_active=bool(row.get("is_active", True)),
            )
        )
    for row in _character_rows(data):
        db.add(
            NovelMemoryNormCharacter(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                name=row["name"],
                role=row["role"],
                status=row["status"],
                traits_json=row["traits_json"],
                detail_json=row["detail_json"],
                influence_score=int(row.get("influence_score") or 0),
                is_active=bool(row.get("is_active", True)),
            )
        )
    for row in _relation_rows(data):
        db.add(
            NovelMemoryNormRelation(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                src=row["src"],
                dst=row["dst"],
                relation=row["relation"],
                is_active=bool(row.get("is_active", True)),
            )
        )
    for row in _plot_rows(data):
        db.add(
            NovelMemoryNormPlot(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                body=row["body"],
                plot_type=str(row.get("plot_type") or "Transient")[:32],
                priority=int(row.get("priority") or 0),
                estimated_duration=int(row.get("estimated_duration") or 0),
                current_stage=str(row.get("current_stage") or ""),
                resolve_when=str(row.get("resolve_when") or ""),
                introduced_chapter=int(row.get("introduced_chapter") or 0),
                last_touched_chapter=int(row.get("last_touched_chapter") or 0),
            )
        )

    merged = _dedupe_chapters_by_no(_canonical_entries_from_payload(data))
    for item in merged:
        cn = item.get("chapter_no")
        if isinstance(cn, str) and str(cn).strip().isdigit():
            cn = int(str(cn).strip())
        if not isinstance(cn, int):
            continue
        title = str(item.get("chapter_title") or "").strip()
        kf = item.get("key_facts") if isinstance(item.get("key_facts"), list) else []
        cr = item.get("causal_results") if isinstance(item.get("causal_results"), list) else []
        oa = (
            item.get("open_plots_added")
            if isinstance(item.get("open_plots_added"), list)
            else []
        )
        or_ = (
            item.get("open_plots_resolved")
            if isinstance(item.get("open_plots_resolved"), list)
            else []
        )
        emotional = str(item.get("emotional_state") or "").strip()
        uh = item.get("unresolved_hooks")
        if not isinstance(uh, list):
            uh = []
        uh_j = json.dumps(
            [str(x).strip() for x in uh if str(x).strip()],
            ensure_ascii=False,
        )
        db.add(
            NovelMemoryNormChapter(
                novel_id=novel_id,
                memory_version=memory_version,
                chapter_no=cn,
                chapter_title=title,
                key_facts_json=json.dumps(kf, ensure_ascii=False),
                causal_results_json=json.dumps(cr, ensure_ascii=False),
                open_plots_added_json=json.dumps(oa, ensure_ascii=False),
                open_plots_resolved_json=json.dumps(or_, ensure_ascii=False),
                emotional_state=emotional,
                unresolved_hooks_json=uh_j,
            )
        )

    # 过期清理：expired_chapter <= 当前最新章节号 且 is_active=True 的记录，自动设置 is_active=False
    latest_chapter = (
        db.query(NovelMemoryNormChapter.chapter_no)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .order_by(NovelMemoryNormChapter.chapter_no.desc())
        .limit(1)
        .scalar()
    ) or 0
    if latest_chapter > 0:
        expired_items = (
            db.query(NovelMemoryNormItem)
            .filter(
                NovelMemoryNormItem.novel_id == novel_id,
                NovelMemoryNormItem.is_active == True,
                NovelMemoryNormItem.expired_chapter != None,
                NovelMemoryNormItem.expired_chapter <= latest_chapter,
            )
            .all()
        )
        for item_row in expired_items:
            item_row.is_active = False

        expired_skills = (
            db.query(NovelMemoryNormSkill)
            .filter(
                NovelMemoryNormSkill.novel_id == novel_id,
                NovelMemoryNormSkill.is_active == True,
                NovelMemoryNormSkill.expired_chapter != None,
                NovelMemoryNormSkill.expired_chapter <= latest_chapter,
            )
            .all()
        )
        for skill_row in expired_skills:
            skill_row.is_active = False


def normalized_memory_to_dict(db: Session, novel_id: str) -> dict[str, Any] | None:
    """从表组装为前端可用的嵌套结构；若无 outline 行则返回 None。"""
    outline = db.get(NovelMemoryNormOutline, novel_id)
    if not outline:
        return None

    def rows(model: Any, order: Any) -> list[Any]:
        return (
            db.query(model)
            .filter(model.novel_id == novel_id)
            .order_by(order)
            .all()
        )

    skills = rows(NovelMemoryNormSkill, NovelMemoryNormSkill.sort_order)
    items = rows(NovelMemoryNormItem, NovelMemoryNormItem.sort_order)
    pets = rows(NovelMemoryNormPet, NovelMemoryNormPet.sort_order)
    chars = rows(NovelMemoryNormCharacter, NovelMemoryNormCharacter.sort_order)
    rels = rows(NovelMemoryNormRelation, NovelMemoryNormRelation.sort_order)
    plots = rows(NovelMemoryNormPlot, NovelMemoryNormPlot.sort_order)
    chs = rows(NovelMemoryNormChapter, NovelMemoryNormChapter.chapter_no)
    latest_chapter_no = chs[-1].chapter_no if chs else 0

    def _detail_with_aliases(raw_json: str) -> tuple[dict[str, Any], list[str]]:
        try:
            detail = json.loads(raw_json or "{}")
        except json.JSONDecodeError:
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        aliases = extract_aliases(detail)
        return detail, aliases

    def _display_inventory_label(raw_label: str, detail: dict[str, Any]) -> str:
        label = str(raw_label or "").strip()
        if label and not label.startswith("{") and not label.startswith("["):
            return label
        inferred = _inventory_label_from_detail(detail)
        if inferred:
            return inferred
        return label or "未命名物品"

    return {
        "memory_version": outline.memory_version,
        "outline": {
            "main_plot": outline.main_plot,
            "timeline_archive_summary": json.loads(outline.timeline_archive_json or "[]"),
            "forbidden_constraints": json.loads(
                getattr(outline, "forbidden_constraints_json", None) or "[]"
            ),
        },
        "skills": [
            (lambda detail, aliases: {
                "id": s.id,
                "name": s.name,
                "detail": detail,
                "aliases": aliases,
                "influence_score": getattr(s, "influence_score", 0) or 0,
                "is_active": getattr(s, "is_active", True),
                "introduced_chapter": getattr(s, "introduced_chapter", 0) or 0,
                "last_used_chapter": getattr(s, "last_used_chapter", 0) or 0,
                "expired_chapter": getattr(s, "expired_chapter", None),
            })(*_detail_with_aliases(s.detail_json))
            for s in skills
        ],
        "inventory": [
            (lambda detail, aliases: {
                "id": s.id,
                "label": _display_inventory_label(s.label, detail),
                "detail": detail,
                "aliases": aliases,
                "influence_score": getattr(s, "influence_score", 0) or 0,
                "is_active": getattr(s, "is_active", True),
                "introduced_chapter": getattr(s, "introduced_chapter", 0) or 0,
                "last_used_chapter": getattr(s, "last_used_chapter", 0) or 0,
                "expired_chapter": getattr(s, "expired_chapter", None),
            })(*_detail_with_aliases(s.detail_json))
            for s in items
        ],
        "pets": [
            (lambda detail, aliases: {
                "id": p.id,
                "name": p.name,
                "detail": detail,
                "aliases": aliases,
                "influence_score": getattr(p, "influence_score", 0) or 0,
                "is_active": getattr(p, "is_active", True),
            })(*_detail_with_aliases(p.detail_json))
            for p in pets
        ],
        "characters": [
            (lambda detail, aliases: {
                "id": c.id,
                "name": c.name,
                "role": c.role,
                "status": c.status,
                "traits": json.loads(c.traits_json or "[]"),
                "detail": detail,
                "aliases": aliases,
                "influence_score": getattr(c, "influence_score", 0) or 0,
                "is_active": getattr(c, "is_active", True),
            })(*_detail_with_aliases(c.detail_json))
            for c in chars
        ],
        "relations": [
            {
                "id": r.id,
                "from": r.src,
                "to": r.dst,
                "relation": r.relation,
                "is_active": getattr(r, "is_active", True),
            }
            for r in rels
        ],
        "open_plots": [
            {
                "body": p.body,
                "plot_type": getattr(p, "plot_type", "Transient") or "Transient",
                "priority": getattr(p, "priority", 0) or 0,
                "estimated_duration": getattr(p, "estimated_duration", 0) or 0,
                "current_stage": getattr(p, "current_stage", "") or "",
                "resolve_when": getattr(p, "resolve_when", "") or "",
                "introduced_chapter": getattr(p, "introduced_chapter", 0) or 0,
                "last_touched_chapter": getattr(p, "last_touched_chapter", 0) or 0,
                "is_stale": bool(
                    latest_chapter_no > 0
                    and getattr(p, "estimated_duration", 0)
                    and (
                        latest_chapter_no
                        - max(
                            getattr(p, "last_touched_chapter", 0) or 0,
                            getattr(p, "introduced_chapter", 0) or 0,
                        )
                    )
                    > settings.novel_open_plot_stale_grace_chapters
                    + int(getattr(p, "estimated_duration", 0) or 0)
                ),
            }
            for p in plots
        ],
        "chapters": [
            {
                "chapter_no": c.chapter_no,
                "chapter_title": c.chapter_title,
                "key_facts": json.loads(c.key_facts_json or "[]"),
                "causal_results": json.loads(c.causal_results_json or "[]"),
                "open_plots_added": json.loads(c.open_plots_added_json or "[]"),
                "open_plots_resolved": json.loads(c.open_plots_resolved_json or "[]"),
                "emotional_state": getattr(c, "emotional_state", "") or "",
                "unresolved_hooks": json.loads(
                    getattr(c, "unresolved_hooks_json", None) or "[]"
                ),
            }
            for c in chs
        ],
    }


def sync_json_snapshot_from_normalized(
    db: Session, novel_id: str, summary: str = "从规范化存储同步快照"
) -> int:
    """
    将当前规范化存储中的数据反向同步到 NovelMemory (JSON 快照) 中。
    规范化分表为唯一真源；快照为派生视图，便于版本历史与导出。
    会保留上一份快照中的展示类字段（如 readable_zh_override），因其未落分表。
    返回新快照的版本号；若无规范化数据则返回 0。
    """
    norm = normalized_memory_to_dict(db, novel_id)
    if not norm:
        return 0

    from app.models.novel import NovelMemory
    from sqlalchemy import func

    # 1) 组装旧格式 Payload
    outline = norm.get("outline", {})
    payload = {
        "main_plot": outline.get("main_plot", ""),
        "timeline_archive_summary": outline.get("timeline_archive_summary", []),
        "forbidden_constraints": outline.get("forbidden_constraints", []),
        "skills": [],
        "inventory": [],
        "pets": [],
        "characters": [],
        "relations": norm.get("relations", []),
        "open_plots": norm.get("open_plots", []),
        "canonical_timeline": norm.get("chapters", []),
    }
    for s in norm.get("skills", []):
        d = dict(s.get("detail") or {})
        aliases = dedupe_clean_strs(s.get("aliases"))
        if aliases:
            d["aliases"] = aliases
        if "influence_score" in s:
            d["influence_score"] = s["influence_score"]
        if "is_active" in s:
            d["is_active"] = s["is_active"]
        payload["skills"].append({"name": s["name"], **d})
    for s in norm.get("inventory", []):
        d = dict(s.get("detail") or {})
        aliases = dedupe_clean_strs(s.get("aliases"))
        if aliases:
            d["aliases"] = aliases
        if "influence_score" in s:
            d["influence_score"] = s["influence_score"]
        if "is_active" in s:
            d["is_active"] = s["is_active"]
        payload["inventory"].append({"name": s["label"], **d})
    for s in norm.get("pets", []):
        d = dict(s.get("detail") or {})
        aliases = dedupe_clean_strs(s.get("aliases"))
        if aliases:
            d["aliases"] = aliases
        if s.get("id"):
            d["id"] = s["id"]
        if "influence_score" in s:
            d["influence_score"] = s["influence_score"]
        if "is_active" in s:
            d["is_active"] = s["is_active"]
        payload["pets"].append({"name": s["name"], **d})
    for c in norm.get("characters", []):
        d = dict(c.get("detail") or {})
        entry = {
            "name": c["name"],
            "role": c["role"],
            "status": c["status"],
            "traits": c["traits"],
            **d,
        }
        aliases = dedupe_clean_strs(c.get("aliases"))
        if aliases:
            entry["aliases"] = aliases
        if c.get("id"):
            entry["id"] = c["id"]
        if "influence_score" in c:
            entry["influence_score"] = c["influence_score"]
        if "is_active" in c:
            entry["is_active"] = c["is_active"]
        payload["characters"].append(entry)

    # 1b) 未落分表的展示类字段从上一份快照继承
    prev_row = (
        db.query(NovelMemory)
        .filter(NovelMemory.novel_id == novel_id)
        .order_by(NovelMemory.version.desc())
        .first()
    )
    if prev_row:
        try:
            prev_p = json.loads(prev_row.payload_json or "{}")
        except json.JSONDecodeError:
            prev_p = {}
        if isinstance(prev_p, dict):
            for k in ("readable_zh_override",):
                if k in prev_p and prev_p[k]:
                    payload[k] = prev_p[k]

    # 2) 写入 NovelMemory
    ver = (
        db.query(func.max(NovelMemory.version))
        .filter(NovelMemory.novel_id == novel_id)
        .scalar()
        or 0
    )
    new_ver = ver + 1

    mem = NovelMemory(
        novel_id=novel_id,
        version=new_ver,
        payload_json=json.dumps(payload, ensure_ascii=False),
        summary=summary,
    )
    db.add(mem)
    return new_ver
