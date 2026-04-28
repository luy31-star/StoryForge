from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.novel import NovelMemory
from app.models.novel_memory_norm import (
    NovelMemoryNormCharacter,
    NovelMemoryNormItem,
    NovelMemoryNormOutline,
    NovelMemoryNormPet,
    NovelMemoryNormPlot,
    NovelMemoryNormRelation,
    NovelMemoryNormSkill,
)
from app.models.novel_story_bible import (
    NovelStoryBibleEntity,
    NovelStoryBibleFact,
    NovelStoryBibleSnapshot,
)


def build_story_bible_summary(db: Session, novel_id: str) -> dict[str, Any]:
    outline = db.get(NovelMemoryNormOutline, novel_id)
    latest_memory_version = (
        db.query(func.max(NovelMemory.version)).filter(NovelMemory.novel_id == novel_id).scalar()
        or 0
    )
    counts = {
        "characters": db.query(NovelMemoryNormCharacter).filter(NovelMemoryNormCharacter.novel_id == novel_id).count(),
        "items": db.query(NovelMemoryNormItem).filter(NovelMemoryNormItem.novel_id == novel_id).count(),
        "skills": db.query(NovelMemoryNormSkill).filter(NovelMemoryNormSkill.novel_id == novel_id).count(),
        "pets": db.query(NovelMemoryNormPet).filter(NovelMemoryNormPet.novel_id == novel_id).count(),
        "plots": db.query(NovelMemoryNormPlot).filter(NovelMemoryNormPlot.novel_id == novel_id).count(),
        "relations": db.query(NovelMemoryNormRelation).filter(NovelMemoryNormRelation.novel_id == novel_id).count(),
    }
    return {
        "latest_memory_version": int(latest_memory_version),
        "main_plot": getattr(outline, "main_plot", "") or "",
        "forbidden_constraints_json": getattr(outline, "forbidden_constraints_json", "[]") or "[]",
        "counts": counts,
    }


def create_story_bible_snapshot_from_normalized(
    db: Session, novel_id: str
) -> NovelStoryBibleSnapshot:
    max_version = (
        db.query(func.max(NovelStoryBibleSnapshot.version))
        .filter(NovelStoryBibleSnapshot.novel_id == novel_id)
        .scalar()
        or 0
    )
    summary = build_story_bible_summary(db, novel_id)
    snapshot = NovelStoryBibleSnapshot(
        novel_id=novel_id,
        version=int(max_version) + 1,
        source_memory_version=int(summary["latest_memory_version"]),
        summary_json=json.dumps(summary, ensure_ascii=False),
        stats_json=json.dumps(summary.get("counts", {}), ensure_ascii=False),
    )
    db.add(snapshot)
    db.flush()

    entity_specs: list[tuple[str, list[Any]]] = [
        (
            "character",
            db.query(NovelMemoryNormCharacter)
            .filter(NovelMemoryNormCharacter.novel_id == novel_id)
            .order_by(NovelMemoryNormCharacter.sort_order.asc())
            .all(),
        ),
        (
            "item",
            db.query(NovelMemoryNormItem)
            .filter(NovelMemoryNormItem.novel_id == novel_id)
            .order_by(NovelMemoryNormItem.sort_order.asc())
            .all(),
        ),
        (
            "skill",
            db.query(NovelMemoryNormSkill)
            .filter(NovelMemoryNormSkill.novel_id == novel_id)
            .order_by(NovelMemoryNormSkill.sort_order.asc())
            .all(),
        ),
        (
            "pet",
            db.query(NovelMemoryNormPet)
            .filter(NovelMemoryNormPet.novel_id == novel_id)
            .order_by(NovelMemoryNormPet.sort_order.asc())
            .all(),
        ),
        (
            "plot",
            db.query(NovelMemoryNormPlot)
            .filter(NovelMemoryNormPlot.novel_id == novel_id)
            .order_by(NovelMemoryNormPlot.sort_order.asc())
            .all(),
        ),
    ]
    norm_id_to_bible: dict[str, str] = {}
    name_to_bible: dict[str, str] = {}

    for entity_type, rows in entity_specs:
        for idx, row in enumerate(rows):
            name = (
                getattr(row, "name", "")
                or getattr(row, "label", "")
                or getattr(row, "body", "")
            )
            cname = str(name or "").strip()[:512]
            entity = NovelStoryBibleEntity(
                novel_id=novel_id,
                snapshot_id=snapshot.id,
                entity_type=entity_type,
                canonical_name=cname,
                aliases_json=getattr(row, "aliases_json", "[]") or "[]",
                status=getattr(row, "status", "") or "",
                description=getattr(row, "detail_json", "{}") or "{}",
                tags_json=getattr(row, "tags_json", "[]") or "[]",
                attributes_json=_entity_attributes_json(row),
                source_chapter_no=int(
                    getattr(row, "source_chapter_no", 0)
                    or getattr(row, "introduced_chapter", 0)
                    or 0
                ),
                last_seen_chapter_no=int(
                    getattr(row, "last_seen_chapter_no", 0)
                    or getattr(row, "last_used_chapter", 0)
                    or getattr(row, "last_touched_chapter", 0)
                    or 0
                ),
                confidence=1.0,
                sort_order=idx,
                is_active=bool(getattr(row, "is_active", True)),
            )
            db.add(entity)
            db.flush()
            rid = str(getattr(row, "id", "") or "")
            if rid:
                norm_id_to_bible[rid] = entity.id
            if cname:
                name_to_bible[cname.lower()] = entity.id
            try:
                for al in json.loads(getattr(row, "aliases_json", "[]") or "[]"):
                    s = str(al).strip()
                    if s:
                        name_to_bible[s.lower()] = entity.id
            except Exception:
                pass

    relation_rows = (
        db.query(NovelMemoryNormRelation)
        .filter(NovelMemoryNormRelation.novel_id == novel_id)
        .order_by(NovelMemoryNormRelation.sort_order.asc())
        .all()
    )
    for rel in relation_rows:
        body = f"{rel.src} -> {rel.dst}: {rel.relation}".strip(": ")
        sid = str(getattr(rel, "src_entity_id", None) or "") or None
        oid = str(getattr(rel, "dst_entity_id", None) or "") or None
        subj = norm_id_to_bible.get(sid) if sid else None
        obj = norm_id_to_bible.get(oid) if oid else None
        if not subj and rel.src:
            subj = name_to_bible.get(str(rel.src).strip().lower())
        if not obj and rel.dst:
            obj = name_to_bible.get(str(rel.dst).strip().lower())
        fact = NovelStoryBibleFact(
            novel_id=novel_id,
            snapshot_id=snapshot.id,
            fact_type="relation",
            subject_entity_id=subj,
            object_entity_id=obj,
            body=body,
            evidence_json=json.dumps(
                {
                    "src": rel.src,
                    "dst": rel.dst,
                    "relation": rel.relation,
                    "norm_src_id": sid,
                    "norm_dst_id": oid,
                    "detail_json": getattr(rel, "detail_json", "{}") or "{}",
                },
                ensure_ascii=False,
            ),
            chapter_range_json=json.dumps(
                {
                    "source_chapter_no": int(getattr(rel, "source_chapter_no", 0) or 0),
                    "last_seen_chapter_no": int(getattr(rel, "last_seen_chapter_no", 0) or 0),
                },
                ensure_ascii=False,
            ),
            status="active" if getattr(rel, "is_active", True) else "inactive",
            weight=1.0,
        )
        db.add(fact)

    return snapshot


def _entity_attributes_json(row: Any) -> str:
    payload = {
        "role": getattr(row, "role", ""),
        "status": getattr(row, "status", ""),
        "traits_json": getattr(row, "traits_json", "[]"),
        "detail_json": getattr(row, "detail_json", "{}"),
        "plot_type": getattr(row, "plot_type", ""),
        "priority": getattr(row, "priority", 0),
        "current_stage": getattr(row, "current_stage", ""),
        "resolve_when": getattr(row, "resolve_when", ""),
        "related_entities_json": getattr(row, "related_entities_json", "[]"),
    }
    return json.dumps(payload, ensure_ascii=False)
