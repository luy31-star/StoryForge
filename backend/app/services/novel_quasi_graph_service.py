"""
基于最新 Story Bible 快照的轻量「准图」：1~2 跳邻居 + 关系边，供写章 prompt 注入。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel_story_bible import (
    NovelStoryBibleEntity,
    NovelStoryBibleFact,
    NovelStoryBibleSnapshot,
)
from app.services.novel_retrieval_service import is_novel_story_bible_enabled

logger = logging.getLogger(__name__)


def _json_list(raw: str) -> list[Any]:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _latest_snapshot(db: Session, novel_id: str) -> NovelStoryBibleSnapshot | None:
    return (
        db.query(NovelStoryBibleSnapshot)
        .filter(NovelStoryBibleSnapshot.novel_id == novel_id)
        .order_by(desc(NovelStoryBibleSnapshot.version), desc(NovelStoryBibleSnapshot.created_at))
        .first()
    )


def build_quasi_graph_context_block(
    db: Session,
    novel_id: str,
    *,
    chapter_no: int,
    plan_hint: str = "",
) -> str:
    if not settings.novel_quasi_graph_enabled or not is_novel_story_bible_enabled(db, novel_id):
        return ""
    snap = _latest_snapshot(db, novel_id)
    if not snap:
        return ""
    ents = (
        db.query(NovelStoryBibleEntity)
        .filter(
            NovelStoryBibleEntity.snapshot_id == snap.id,
            NovelStoryBibleEntity.is_active == True,
        )
        .all()
    )
    facts = (
        db.query(NovelStoryBibleFact)
        .filter(
            NovelStoryBibleFact.snapshot_id == snap.id,
            NovelStoryBibleFact.fact_type == "relation",
        )
        .all()
    )
    if not ents and not facts:
        return ""
    eby: dict[str, NovelStoryBibleEntity] = {e.id: e for e in ents if e.id}
    seed: set[str] = set()
    for tok in _extract_name_tokens(f"第{chapter_no}章 " + (plan_hint or "")):
        for e in ents:
            if (e.canonical_name or "").strip() and tok in (e.canonical_name or "").lower():
                seed.add(e.id)
            for al in _json_list(e.aliases_json or "[]"):
                s2 = str(al).strip()
                if s2 and tok in s2.lower():
                    seed.add(e.id)
    if not seed and ents:
        for e in ents[:4]:
            if e.id:
                seed.add(e.id)
    nbr1 = set(seed)
    for ft in facts:
        a, b = ft.subject_entity_id, ft.object_entity_id
        if not a or not b or a not in eby or b not in eby:
            continue
        if a in nbr1 or b in nbr1:
            nbr1.add(a)
            nbr1.add(b)
    max_lines = int(settings.novel_quasi_graph_max_edges or 24)
    lines: list[str] = ["【关系子图（Story Bible）】"]
    shown = 0
    for ft in facts:
        if shown >= max_lines:
            break
        a, b = ft.subject_entity_id, ft.object_entity_id
        if not a or not b or a not in nbr1 or b not in nbr1:
            continue
        ea, eb2 = eby.get(a), eby.get(b)
        sa = ea.canonical_name if ea else "?"
        sb = eb2.canonical_name if eb2 else "?"
        lines.append(
            f"  · {sa} —{str(ft.body or '')[:120]}— {sb}"[:200]
        )
        shown += 1
    if shown == 0:
        for e in list(ents)[:6]:
            lines.append(
                f"  · [{e.entity_type}] {e.canonical_name}｜{str(e.status or '')[:40]}"
            )
    return "\n".join(lines[: 18])


def _extract_name_tokens(hint: str) -> set[str]:
    s = (hint or "").lower()
    if not s:
        return set()
    toks: set[str] = set()
    for part in s.replace("，", " ").replace("。", " ").split():
        p2 = part.strip("（）()[]")
        if len(p2) >= 2:
            toks.add(p2.lower())
    for m in re.findall(r"[\u4e00-\u9fff]{2,4}", hint):
        toks.add(m.lower())
    return toks
