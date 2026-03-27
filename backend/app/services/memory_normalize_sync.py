"""
从记忆 payload JSON 同步到规范化表；每次写入 NovelMemory 新版本后调用。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

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
    inf = 0
    raw_inf = item.get("influence_score")
    if raw_inf is not None:
        try:
            inf = int(raw_inf)
        except (TypeError, ValueError):
            inf = 0
    active = item.get("is_active")
    is_active = True if active is None else bool(active)
    return inf, is_active


def _skill_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("skills")
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
                    "name": name or f"技能{i + 1}",
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


def _item_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = payload.get("inventory")
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
                    "label": name or json.dumps(rest, ensure_ascii=False)[:200],
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
                        "label": s,
                        "detail_json": "{}",
                        "influence_score": 0,
                        "is_active": True,
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
        if not (src and dst):
            continue
        out.append(
            {
                "sort_order": i,
                "src": src,
                "dst": dst,
                "relation": rel,
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
                try:
                    prio = int(x.get("priority") or 0)
                except (TypeError, ValueError):
                    prio = 0
                try:
                    est = int(x.get("estimated_duration") or 0)
                except (TypeError, ValueError):
                    est = 0
                ptype = str(x.get("plot_type") or "Transient").strip()[:32] or "Transient"
                out.append(
                    {
                        "sort_order": i,
                        "body": body,
                        "plot_type": ptype,
                        "priority": prio,
                        "estimated_duration": est,
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
        world_rules_json=_json_list(data.get("world_rules")),
        arcs_json=_json_list(data.get("arcs")),
        themes_json=_json_list(data.get("themes")),
        notes_json=_json_list(data.get("notes")),
        timeline_archive_json=_json_list(data.get("timeline_archive_summary")),
        forbidden_constraints_json=json.dumps(
            [str(x).strip() for x in fc_raw if str(x).strip()],
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

    return {
        "memory_version": outline.memory_version,
        "outline": {
            "main_plot": outline.main_plot,
            "world_rules": json.loads(outline.world_rules_json or "[]"),
            "arcs": json.loads(outline.arcs_json or "[]"),
            "themes": json.loads(outline.themes_json or "[]"),
            "notes": json.loads(outline.notes_json or "[]"),
            "timeline_archive_summary": json.loads(outline.timeline_archive_json or "[]"),
            "forbidden_constraints": json.loads(
                getattr(outline, "forbidden_constraints_json", None) or "[]"
            ),
        },
        "skills": [
            {
                "name": s.name,
                "detail": json.loads(s.detail_json or "{}"),
                "influence_score": getattr(s, "influence_score", 0) or 0,
                "is_active": getattr(s, "is_active", True),
            }
            for s in skills
        ],
        "inventory": [
            {
                "label": s.label,
                "detail": json.loads(s.detail_json or "{}"),
                "influence_score": getattr(s, "influence_score", 0) or 0,
                "is_active": getattr(s, "is_active", True),
            }
            for s in items
        ],
        "pets": [
            {
                "name": p.name,
                "detail": json.loads(p.detail_json or "{}"),
                "influence_score": getattr(p, "influence_score", 0) or 0,
                "is_active": getattr(p, "is_active", True),
            }
            for p in pets
        ],
        "characters": [
            {
                "name": c.name,
                "role": c.role,
                "status": c.status,
                "traits": json.loads(c.traits_json or "[]"),
                "detail": json.loads(c.detail_json or "{}"),
                "influence_score": getattr(c, "influence_score", 0) or 0,
                "is_active": getattr(c, "is_active", True),
            }
            for c in chars
        ],
        "relations": [
            {"from": r.src, "to": r.dst, "relation": r.relation} for r in rels
        ],
        "open_plots": [
            {
                "body": p.body,
                "plot_type": getattr(p, "plot_type", "Transient") or "Transient",
                "priority": getattr(p, "priority", 0) or 0,
                "estimated_duration": getattr(p, "estimated_duration", 0) or 0,
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
        "world_rules": outline.get("world_rules", []),
        "arcs": outline.get("arcs", []),
        "themes": outline.get("themes", []),
        "notes": outline.get("notes", []),
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
        if "influence_score" in s:
            d["influence_score"] = s["influence_score"]
        if "is_active" in s:
            d["is_active"] = s["is_active"]
        payload["skills"].append({"name": s["name"], **d})
    for s in norm.get("inventory", []):
        d = dict(s.get("detail") or {})
        if "influence_score" in s:
            d["influence_score"] = s["influence_score"]
        if "is_active" in s:
            d["is_active"] = s["is_active"]
        payload["inventory"].append({"name": s["label"], **d})
    for s in norm.get("pets", []):
        d = dict(s.get("detail") or {})
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
