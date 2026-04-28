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
    coerce_int,
    dedupe_clean_strs,
    extract_aliases,
    normalize_plot_type,
)
from app.services.novel_entity_lifecycle import infer_lifecycle_state


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


def _str_list_from_json(raw: str) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(x).strip() for x in data if str(x).strip()]


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
            lc = str(item.get("lifecycle_state") or "").strip() or infer_lifecycle_state(
                is_active=is_active,
                introduced_chapter=introduced_chapter,
                last_seen_chapter=max(introduced_chapter, last_used_chapter),
                expired_chapter=expired_chapter,
            )
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
                    "lifecycle_state": lc,
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
                    "lifecycle_state": "usable",
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
            lc = str(item.get("lifecycle_state") or "").strip() or infer_lifecycle_state(
                is_active=is_active,
                introduced_chapter=introduced_chapter,
                last_seen_chapter=max(introduced_chapter, last_used_chapter),
                expired_chapter=expired_chapter,
            )
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
                    "lifecycle_state": lc,
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
                    "lifecycle_state": "usable",
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
                if k
                not in (
                    "name",
                    "influence_score",
                    "is_active",
                    "introduced_chapter",
                    "source_chapter_no",
                    "last_seen_chapter_no",
                    "expired_chapter",
                )
            }
            intro = coerce_int(
                item.get("introduced_chapter") or item.get("source_chapter_no"),
                default=0,
            )
            scn = coerce_int(item.get("source_chapter_no"), default=0) or intro
            lsn = coerce_int(item.get("last_seen_chapter_no"), default=0)
            ex = item.get("expired_chapter")
            ex_c: int | None
            if ex is None or ex == "":
                ex_c = None
            else:
                try:
                    ex_c = int(ex) if not isinstance(ex, str) or ex.strip() else None
                except (TypeError, ValueError):
                    ex_c = None
            lc = str(item.get("lifecycle_state") or "").strip() or infer_lifecycle_state(
                is_active=is_active,
                introduced_chapter=intro,
                last_seen_chapter=max(intro, lsn),
                expired_chapter=ex_c,
            )
            out.append(
                {
                    "sort_order": i,
                    "name": name or f"宠物{i + 1}",
                    "detail_json": json.dumps(rest, ensure_ascii=False),
                    "influence_score": inf,
                    "is_active": is_active,
                    "introduced_chapter": intro,
                    "source_chapter_no": scn,
                    "last_seen_chapter_no": lsn,
                    "expired_chapter": ex_c,
                    "lifecycle_state": lc,
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
                        "source_chapter_no": 0,
                        "last_seen_chapter_no": 0,
                        "expired_chapter": None,
                        "lifecycle_state": "usable",
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
            if k
            not in (
                "name",
                "role",
                "status",
                "traits",
                "influence_score",
                "is_active",
                "aliases",
                "tags",
                "introduced_chapter",
                "source_chapter_no",
                "last_seen_chapter_no",
                "expired_chapter",
                "identity_stage",
                "exposed_identity_level",
                "lifecycle_state",
            )
        }
        raw_al = item.get("aliases")
        if not isinstance(raw_al, list):
            al2 = item.get("alias")
            if isinstance(al2, str) and al2.strip():
                raw_al = [al2]
            else:
                raw_al = []
        aliases = dedupe_clean_strs(raw_al)
        if not aliases:
            try:
                d0 = item.get("detail")
                if isinstance(d0, dict) and d0.get("aliases"):
                    aliases = dedupe_clean_strs(d0.get("aliases"))
            except Exception:
                aliases = []
        aliases_j = (
            json.dumps(aliases, ensure_ascii=False) if aliases else "[]"
        )
        tag_list = item.get("tags")
        if isinstance(tag_list, list) and tag_list:
            tag_j = json.dumps(
                [str(x) for x in tag_list if str(x).strip()],
                ensure_ascii=False,
            )
        else:
            tag_j = "[]"
        intro = coerce_int(
            item.get("introduced_chapter")
            or item.get("first_seen_chapter")
            or item.get("source_chapter_no"),
            default=0,
        )
        scn = coerce_int(item.get("source_chapter_no"), default=0) or intro
        lsn = coerce_int(item.get("last_seen_chapter_no"), default=0)
        exp = item.get("expired_chapter")
        exp_c: int | None
        if exp is None or exp == "":
            exp_c = None
        else:
            try:
                exp_c = int(exp) if not isinstance(exp, str) or exp.strip() else None
            except (TypeError, ValueError):
                exp_c = None
        id_st = str(item.get("identity_stage") or "public")[:64]
        ex_l = str(item.get("exposed_identity_level") or "0")[:32]
        lc = (str(item.get("lifecycle_state") or "").strip()) or infer_lifecycle_state(
            is_active=is_active,
            introduced_chapter=intro,
            last_seen_chapter=max(intro, lsn),
            expired_chapter=exp_c,
        )
        out.append(
            {
                "sort_order": i,
                "name": name,
                "role": str(item.get("role") or ""),
                "status": str(item.get("status") or ""),
                "traits_json": traits_j,
                "aliases_json": aliases_j,
                "tags_json": tag_j,
                "detail_json": json.dumps(rest, ensure_ascii=False),
                "influence_score": inf,
                "is_active": is_active,
                "introduced_chapter": intro,
                "source_chapter_no": scn,
                "last_seen_chapter_no": lsn,
                "expired_chapter": exp_c,
                "identity_stage": id_st,
                "exposed_identity_level": ex_l,
                "lifecycle_state": lc,
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
        rest = {
            k: v
            for k, v in item.items()
            if k
            not in (
                "from",
                "to",
                "relation",
                "is_active",
                "source_chapter_no",
                "last_seen_chapter_no",
            )
        }
        out.append(
            {
                "sort_order": i,
                "src": src,
                "dst": dst,
                "relation": rel,
                "is_active": True if active is None else bool(active),
                "detail_json": json.dumps(rest, ensure_ascii=False),
                "source_chapter_no": coerce_int(
                    item.get("source_chapter_no")
                    or item.get("introduced_chapter")
                    or item.get("established_chapter"),
                    default=0,
                ),
                "last_seen_chapter_no": coerce_int(
                    item.get("last_seen_chapter_no")
                    or item.get("touched_chapter")
                    or item.get("last_mentioned_chapter"),
                    default=0,
                ),
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


def _detail_dict(raw_json: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_json or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_visible_in_chapter(
    *,
    chapter_no: int,
    introduced_chapter: int = 0,
    expired_chapter: int | None = None,
    is_active: bool = True,
) -> bool:
    if introduced_chapter and introduced_chapter > chapter_no:
        return False
    if isinstance(expired_chapter, int) and expired_chapter and expired_chapter <= chapter_no:
        return False
    return bool(is_active)


def _build_state_snapshot(db: Session, novel_id: str, chapter_no: int) -> dict[str, Any]:
    characters: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []
    pets: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []

    for row in (
        db.query(NovelMemoryNormCharacter)
        .filter(
            NovelMemoryNormCharacter.novel_id == novel_id,
            NovelMemoryNormCharacter.introduced_chapter <= chapter_no,
        )
        .order_by(NovelMemoryNormCharacter.sort_order.asc())
        .all()
    ):
        if not _is_visible_in_chapter(
            chapter_no=chapter_no,
            introduced_chapter=getattr(row, "introduced_chapter", 0) or 0,
            expired_chapter=getattr(row, "expired_chapter", None),
            is_active=bool(getattr(row, "is_active", True)),
        ):
            continue
        characters.append(
            {
                "id": row.id,
                "name": row.name,
                "lifecycle_state": getattr(row, "lifecycle_state", "usable") or "usable",
                "identity_stage": getattr(row, "identity_stage", "public") or "public",
                "status": getattr(row, "status", "") or "",
            }
        )

    for row in (
        db.query(NovelMemoryNormItem)
        .filter(
            NovelMemoryNormItem.novel_id == novel_id,
            NovelMemoryNormItem.introduced_chapter <= chapter_no,
        )
        .order_by(NovelMemoryNormItem.sort_order.asc())
        .all()
    ):
        if not _is_visible_in_chapter(
            chapter_no=chapter_no,
            introduced_chapter=getattr(row, "introduced_chapter", 0) or 0,
            expired_chapter=getattr(row, "expired_chapter", None),
            is_active=bool(getattr(row, "is_active", True)),
        ):
            continue
        items.append(
            {
                "id": row.id,
                "label": row.label,
                "lifecycle_state": getattr(row, "lifecycle_state", "usable") or "usable",
            }
        )

    for row in (
        db.query(NovelMemoryNormSkill)
        .filter(
            NovelMemoryNormSkill.novel_id == novel_id,
            NovelMemoryNormSkill.introduced_chapter <= chapter_no,
        )
        .order_by(NovelMemoryNormSkill.sort_order.asc())
        .all()
    ):
        if not _is_visible_in_chapter(
            chapter_no=chapter_no,
            introduced_chapter=getattr(row, "introduced_chapter", 0) or 0,
            expired_chapter=getattr(row, "expired_chapter", None),
            is_active=bool(getattr(row, "is_active", True)),
        ):
            continue
        skills.append(
            {
                "id": row.id,
                "name": row.name,
                "lifecycle_state": getattr(row, "lifecycle_state", "usable") or "usable",
            }
        )

    for row in (
        db.query(NovelMemoryNormPet)
        .filter(
            NovelMemoryNormPet.novel_id == novel_id,
            NovelMemoryNormPet.introduced_chapter <= chapter_no,
        )
        .order_by(NovelMemoryNormPet.sort_order.asc())
        .all()
    ):
        if not _is_visible_in_chapter(
            chapter_no=chapter_no,
            introduced_chapter=getattr(row, "introduced_chapter", 0) or 0,
            expired_chapter=getattr(row, "expired_chapter", None),
            is_active=bool(getattr(row, "is_active", True)),
        ):
            continue
        pets.append(
            {
                "id": row.id,
                "name": row.name,
                "lifecycle_state": getattr(row, "lifecycle_state", "usable") or "usable",
            }
        )

    for row in (
        db.query(NovelMemoryNormRelation)
        .filter(
            NovelMemoryNormRelation.novel_id == novel_id,
            NovelMemoryNormRelation.source_chapter_no <= chapter_no,
            NovelMemoryNormRelation.is_active == True,
        )
        .order_by(NovelMemoryNormRelation.sort_order.asc())
        .all()
    ):
        relations.append(
            {
                "id": row.id,
                "src": row.src,
                "dst": row.dst,
                "relation": row.relation,
                "src_entity_id": getattr(row, "src_entity_id", None),
                "dst_entity_id": getattr(row, "dst_entity_id", None),
            }
        )

    return {
        "chapter_no": chapter_no,
        "counts": {
            "characters": len(characters),
            "items": len(items),
            "skills": len(skills),
            "pets": len(pets),
            "relations": len(relations),
        },
        "characters": characters,
        "items": items,
        "skills": skills,
        "pets": pets,
        "relations": relations,
    }


def _build_state_transition_summary(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> list[str]:
    if not isinstance(current, dict):
        return []
    previous = previous if isinstance(previous, dict) else {}

    def _index(seq: Any, key_name: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(seq, list):
            return out
        for item in seq:
            if not isinstance(item, dict):
                continue
            key = str(item.get(key_name) or "").strip()
            if not key:
                continue
            out[key] = item
        return out

    transitions: list[str] = []
    prev_chars = _index(previous.get("characters"), "id")
    curr_chars = _index(current.get("characters"), "id")
    prev_items = _index(previous.get("items"), "id")
    curr_items = _index(current.get("items"), "id")
    prev_skills = _index(previous.get("skills"), "id")
    curr_skills = _index(current.get("skills"), "id")
    prev_rel = _index(previous.get("relations"), "id")
    curr_rel = _index(current.get("relations"), "id")

    for cid, item in curr_chars.items():
        if cid not in prev_chars:
            transitions.append(f"角色进入可用态：{item.get('name') or '未知角色'}")
            continue
        prev_item = prev_chars[cid]
        if prev_item.get("identity_stage") != item.get("identity_stage"):
            transitions.append(
                f"角色身份阶段变化：{item.get('name') or '未知角色'} -> {item.get('identity_stage') or 'unknown'}"
            )
        if prev_item.get("lifecycle_state") != item.get("lifecycle_state"):
            transitions.append(
                f"角色生命周期变化：{item.get('name') or '未知角色'} -> {item.get('lifecycle_state') or 'unknown'}"
            )
    for cid, item in prev_chars.items():
        if cid not in curr_chars:
            transitions.append(f"角色离开当前可用态：{item.get('name') or '未知角色'}")

    for iid, item in curr_items.items():
        if iid not in prev_items:
            transitions.append(f"物品进入可用态：{item.get('label') or '未命名物品'}")
    for iid, item in prev_items.items():
        if iid not in curr_items:
            transitions.append(f"物品退出当前可用态：{item.get('label') or '未命名物品'}")

    for sid, item in curr_skills.items():
        if sid not in prev_skills:
            transitions.append(f"技能进入可用态：{item.get('name') or '未知技能'}")
    for sid, item in prev_skills.items():
        if sid not in curr_skills:
            transitions.append(f"技能退出当前可用态：{item.get('name') or '未知技能'}")

    for rid, item in curr_rel.items():
        if rid not in prev_rel:
            transitions.append(
                f"关系新增：{item.get('src') or '未知'} - {item.get('relation') or '关联'} - {item.get('dst') or '未知'}"
            )

    return transitions[:16]


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
                lifecycle_state=str(row.get("lifecycle_state") or "usable")[:32],
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
                lifecycle_state=str(row.get("lifecycle_state") or "usable")[:32],
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
                introduced_chapter=int(row.get("introduced_chapter") or 0),
                source_chapter_no=int(row.get("source_chapter_no") or 0)
                or int(row.get("introduced_chapter") or 0),
                last_seen_chapter_no=int(row.get("last_seen_chapter_no") or 0),
                expired_chapter=row.get("expired_chapter"),
                lifecycle_state=str(row.get("lifecycle_state") or "usable")[:32],
            )
        )
    name_to_entity_id: dict[str, str] = {}
    for row in _character_rows(data):
        ch = NovelMemoryNormCharacter(
            novel_id=novel_id,
            memory_version=memory_version,
            sort_order=row["sort_order"],
            name=row["name"],
            role=row["role"],
            status=row["status"],
            aliases_json=row.get("aliases_json", "[]"),
            tags_json=row.get("tags_json", "[]"),
            traits_json=row["traits_json"],
            detail_json=row["detail_json"],
            influence_score=int(row.get("influence_score") or 0),
            is_active=bool(row.get("is_active", True)),
            introduced_chapter=int(row.get("introduced_chapter") or 0),
            source_chapter_no=int(row.get("source_chapter_no") or 0)
            or int(row.get("introduced_chapter") or 0),
            last_seen_chapter_no=int(row.get("last_seen_chapter_no") or 0),
            expired_chapter=row.get("expired_chapter"),
            identity_stage=str(row.get("identity_stage") or "public")[:64],
            exposed_identity_level=str(row.get("exposed_identity_level") or "0")[:32],
            lifecycle_state=str(row.get("lifecycle_state") or "usable")[:32],
        )
        db.add(ch)
        db.flush()
        key = (ch.name or "").strip().lower()
        if key:
            name_to_entity_id[key] = ch.id
        for al in _str_list_from_json(getattr(ch, "aliases_json", "[]") or "[]"):
            if al:
                name_to_entity_id[al.lower()] = ch.id
        for al in _str_list_from_json(getattr(ch, "tags_json", "[]") or "[]"):
            if al:
                name_to_entity_id[al.lower()] = ch.id
    for row in _relation_rows(data):
        s_key = (row.get("src") or "").strip().lower()
        d_key = (row.get("dst") or "").strip().lower()
        sid = name_to_entity_id.get(s_key) if s_key else None
        did = name_to_entity_id.get(d_key) if d_key else None
        db.add(
            NovelMemoryNormRelation(
                novel_id=novel_id,
                memory_version=memory_version,
                sort_order=row["sort_order"],
                src=row["src"],
                dst=row["dst"],
                relation=row["relation"],
                detail_json=row.get("detail_json") or "{}",
                is_active=bool(row.get("is_active", True)),
                source_chapter_no=int(row.get("source_chapter_no") or 0),
                last_seen_chapter_no=int(row.get("last_seen_chapter_no") or 0),
                src_entity_id=sid,
                dst_entity_id=did,
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
        scene_facts = item.get("scene_facts") if isinstance(item.get("scene_facts"), list) else []
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
                scene_facts_json=json.dumps(scene_facts, ensure_ascii=False),
                emotional_state=emotional,
                unresolved_hooks_json=uh_j,
                state_snapshot_json="{}",
                state_transition_summary_json="[]",
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

    db.flush()
    chapter_rows = (
        db.query(NovelMemoryNormChapter)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .order_by(NovelMemoryNormChapter.chapter_no.asc())
        .all()
    )
    previous_snapshot: dict[str, Any] | None = None
    for chapter_row in chapter_rows:
        snapshot = _build_state_snapshot(db, novel_id, int(chapter_row.chapter_no or 0))
        chapter_row.state_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        chapter_row.state_transition_summary_json = json.dumps(
            _build_state_transition_summary(previous_snapshot, snapshot),
            ensure_ascii=False,
        )
        previous_snapshot = snapshot


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
                "lifecycle_state": getattr(s, "lifecycle_state", "usable") or "usable",
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
                "lifecycle_state": getattr(s, "lifecycle_state", "usable") or "usable",
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
                "introduced_chapter": getattr(p, "introduced_chapter", 0) or 0,
                "source_chapter_no": getattr(p, "source_chapter_no", 0) or 0,
                "last_seen_chapter_no": getattr(p, "last_seen_chapter_no", 0) or 0,
                "expired_chapter": getattr(p, "expired_chapter", None),
                "lifecycle_state": getattr(p, "lifecycle_state", "usable") or "usable",
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
                "introduced_chapter": getattr(c, "introduced_chapter", 0) or 0,
                "source_chapter_no": getattr(c, "source_chapter_no", 0) or 0,
                "last_seen_chapter_no": getattr(c, "last_seen_chapter_no", 0) or 0,
                "expired_chapter": getattr(c, "expired_chapter", None),
                "identity_stage": getattr(c, "identity_stage", "public") or "public",
                "exposed_identity_level": getattr(c, "exposed_identity_level", "0") or "0",
                "lifecycle_state": getattr(c, "lifecycle_state", "usable") or "usable",
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
                "detail_json": getattr(r, "detail_json", "{}") or "{}",
                "source_chapter_no": getattr(r, "source_chapter_no", 0) or 0,
                "last_seen_chapter_no": getattr(r, "last_seen_chapter_no", 0) or 0,
                "src_entity_id": getattr(r, "src_entity_id", None),
                "dst_entity_id": getattr(r, "dst_entity_id", None),
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
                "scene_facts": json.loads(getattr(c, "scene_facts_json", None) or "[]"),
                "emotional_state": getattr(c, "emotional_state", "") or "",
                "unresolved_hooks": json.loads(
                    getattr(c, "unresolved_hooks_json", None) or "[]"
                ),
                "state_snapshot": json.loads(
                    getattr(c, "state_snapshot_json", None) or "{}"
                ),
                "state_transition_summary": json.loads(
                    getattr(c, "state_transition_summary_json", None) or "[]"
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
        if "introduced_chapter" in s:
            d["introduced_chapter"] = s["introduced_chapter"]
        if "last_used_chapter" in s:
            d["last_used_chapter"] = s["last_used_chapter"]
        if "expired_chapter" in s:
            d["expired_chapter"] = s["expired_chapter"]
        if "lifecycle_state" in s:
            d["lifecycle_state"] = s["lifecycle_state"]
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
        if "introduced_chapter" in s:
            d["introduced_chapter"] = s["introduced_chapter"]
        if "last_used_chapter" in s:
            d["last_used_chapter"] = s["last_used_chapter"]
        if "expired_chapter" in s:
            d["expired_chapter"] = s["expired_chapter"]
        if "lifecycle_state" in s:
            d["lifecycle_state"] = s["lifecycle_state"]
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
        if "introduced_chapter" in s:
            d["introduced_chapter"] = s["introduced_chapter"]
        if "source_chapter_no" in s:
            d["source_chapter_no"] = s["source_chapter_no"]
        if "last_seen_chapter_no" in s:
            d["last_seen_chapter_no"] = s["last_seen_chapter_no"]
        if "expired_chapter" in s:
            d["expired_chapter"] = s["expired_chapter"]
        if "lifecycle_state" in s:
            d["lifecycle_state"] = s["lifecycle_state"]
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
        if "introduced_chapter" in c:
            entry["introduced_chapter"] = c["introduced_chapter"]
        if "source_chapter_no" in c:
            entry["source_chapter_no"] = c["source_chapter_no"]
        if "last_seen_chapter_no" in c:
            entry["last_seen_chapter_no"] = c["last_seen_chapter_no"]
        if "expired_chapter" in c:
            entry["expired_chapter"] = c["expired_chapter"]
        if "identity_stage" in c:
            entry["identity_stage"] = c["identity_stage"]
        if "exposed_identity_level" in c:
            entry["exposed_identity_level"] = c["exposed_identity_level"]
        if "lifecycle_state" in c:
            entry["lifecycle_state"] = c["lifecycle_state"]
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
