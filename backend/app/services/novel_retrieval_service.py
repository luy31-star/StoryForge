from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Novel
from app.models.novel_memory_norm import (
    NovelMemoryNormCharacter,
    NovelMemoryNormChapter,
    NovelMemoryNormItem,
    NovelMemoryNormPet,
    NovelMemoryNormPlot,
    NovelMemoryNormRelation,
    NovelMemoryNormSkill,
)
from app.models.novel_retrieval import (
    NovelRetrievalChunk,
    NovelRetrievalDocument,
    NovelRetrievalQueryLog,
)
from app.services.novel_embedding_service import embed_text, embed_texts
from app.services.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


def is_novel_rag_enabled(db: Session, novel_id: str) -> bool:
    if not settings.novel_rag_enabled:
        return False
    novel = db.get(Novel, novel_id)
    return bool(novel and getattr(novel, "rag_enabled", False))


def is_novel_story_bible_enabled(db: Session, novel_id: str) -> bool:
    if not settings.novel_story_bible_enabled:
        return False
    novel = db.get(Novel, novel_id)
    return bool(novel and getattr(novel, "story_bible_enabled", False))


def _doc_key(source_type: str, source_id: str) -> tuple[str, str]:
    return (str(source_type or ""), str(source_id or ""))


def _split_into_chunks(
    text: str,
    *,
    max_chars: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    max_c = int(max_chars or settings.novel_retrieval_chunk_max_chars)
    ov = int(overlap or settings.novel_retrieval_chunk_overlap)
    if len(raw) <= max_c:
        return [raw]
    chunks: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        j = min(n, i + max_c)
        piece = raw[i:j]
        if piece.strip():
            chunks.append(piece.strip())
        if j >= n:
            break
        i = max(0, j - ov)
    return chunks or [raw[:max_c]]


def rebuild_novel_retrieval_index(db: Session, novel_id: str) -> dict[str, Any]:
    if not is_novel_rag_enabled(db, novel_id):
        return {"status": "disabled", "documents": 0, "chunks": 0}

    store = QdrantStore()
    store.ensure_collection()
    try:
        store.delete_points_by_filter(
            {"must": [{"key": "novel_id", "match": {"value": novel_id}}]}
        )
    except Exception:
        logger.exception("qdrant delete old novel points failed | novel_id=%s", novel_id)

    db.query(NovelRetrievalChunk).filter(
        NovelRetrievalChunk.novel_id == novel_id
    ).delete(synchronize_session=False)
    db.query(NovelRetrievalDocument).filter(
        NovelRetrievalDocument.novel_id == novel_id
    ).delete(synchronize_session=False)
    db.flush()

    return _ingest_all_documents(
        db, store, novel_id, docs_payload=_build_retrieval_documents_from_db(db, novel_id)
    )


def sync_novel_retrieval_index(
    db: Session, novel_id: str, *, full_rebuild: bool = False
) -> dict[str, Any]:
    if not is_novel_rag_enabled(db, novel_id):
        return {"status": "disabled", "documents": 0, "chunks": 0, "mode": "disabled"}
    if full_rebuild or not settings.novel_retrieval_incremental:
        out = rebuild_novel_retrieval_index(db, novel_id)
        return {**out, "mode": "full"}
    return _sync_novel_retrieval_incremental(db, novel_id)


def _ingest_all_documents(
    db: Session,
    store: QdrantStore,
    novel_id: str,
    *,
    docs_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    struct: list[
        tuple[NovelRetrievalDocument, NovelRetrievalChunk, dict[str, Any], dict[str, Any]]
    ] = []
    for doc_item in docs_payload:
        doc = NovelRetrievalDocument(
            novel_id=novel_id,
            source_type=doc_item["source_type"],
            source_id=doc_item["source_id"],
            title=doc_item["title"],
            summary=doc_item["summary"],
            metadata_json=json.dumps(doc_item["metadata"], ensure_ascii=False),
            checksum=doc_item["checksum"],
            is_active=True,
        )
        db.add(doc)
        db.flush()
        for idx, ch_text in enumerate(doc_item["chunks"], start=1):
            h = hashlib.md5(
                f"{doc_item['source_type']}:{doc_item['source_id']}:{idx}:{ch_text}".encode(
                    "utf-8"
                )
            ).hexdigest()[:32]
            chunk = NovelRetrievalChunk(
                novel_id=novel_id,
                document_id=doc.id,
                chunk_no=idx,
                content=ch_text,
                content_hash=h,
                vector_backend=settings.novel_embedding_provider,
                qdrant_point_id="",
                metadata_json=json.dumps(
                    {**(doc_item.get("metadata") or {}), "chunk_in_doc": idx},
                    ensure_ascii=False,
                ),
                token_estimate=max(1, len(ch_text) // 2),
            )
            db.add(chunk)
            db.flush()
            chunk.qdrant_point_id = str(chunk.id)
            struct.append((doc, chunk, doc_item, doc_item.get("metadata") or {}))
    if not struct:
        db.flush()
        return {"status": "ok", "documents": len(docs_payload), "chunks": 0}
    all_chunk_texts = [s[1].content for s in struct]
    try:
        vecs = embed_texts(all_chunk_texts)
    except Exception:
        logger.exception("batch embed failed, falling back to per-chunk | novel_id=%s", novel_id)
        vecs = [embed_text(t) for t in all_chunk_texts]
    points: list[dict[str, Any]] = []
    for (doc, ch, ditem, meta), vec in zip(struct, vecs):
        payload = _qdrant_payload(
            novel_id, doc, ch, ch.content, meta, ditem
        )
        points.append(
            {
                "id": ch.id,
                "vector": vec,
                "payload": payload,
            }
        )
    if points:
        store.upsert_points(points)
    db.flush()
    return {
        "status": "ok",
        "documents": len(docs_payload),
        "chunks": len(struct),
    }


def _qdrant_payload(
    novel_id: str,
    doc: NovelRetrievalDocument,
    ch: NovelRetrievalChunk,
    ch_text: str,
    base_meta: dict[str, Any],
    doc_item: dict[str, Any] | None,
) -> dict[str, Any]:
    p: dict[str, Any] = {
        "novel_id": novel_id,
        "document_id": doc.id,
        "chunk_id": ch.id,
        "source_type": doc.source_type,
        "source_id": str(doc.source_id or ""),
        "title": (doc.title or "")[:512],
        "text": (ch_text or "")[:4000],
        "rag_kind": str(doc_item.get("rag_kind") or doc.source_type) if doc_item else doc.source_type,
    }
    for k in (
        "entity_id",
        "entity_ids",
        "state_tags",
        "edge_kind",
        "introduced_chapter",
        "expired_chapter",
        "chapter_no",
        "src_entity_id",
        "dst_entity_id",
        "subject_entity_id",
        "object_entity_id",
    ):
        if k in base_meta and base_meta[k] is not None:
            p[k] = base_meta[k]
    return p


def _delete_one_document(
    db: Session, store: QdrantStore, doc: NovelRetrievalDocument
) -> None:
    cids: list[str] = []
    for ch in list(doc.chunks) if doc.chunks else ():
        cids.append(ch.id)
    if cids:
        try:
            store.delete_points_by_ids(cids)
        except Exception:
            logger.exception("qdrant delete points failed for doc | doc_id=%s", doc.id)
    db.query(NovelRetrievalChunk).filter(
        NovelRetrievalChunk.document_id == doc.id
    ).delete(synchronize_session=False)
    db.delete(doc)
    db.flush()


def _sync_novel_retrieval_incremental(db: Session, novel_id: str) -> dict[str, Any]:
    store = QdrantStore()
    store.ensure_collection()
    new_docs = _build_retrieval_documents_from_db(db, novel_id)
    new_map: dict[tuple[str, str], dict[str, Any]] = {
        _doc_key(d["source_type"], d["source_id"]): d for d in new_docs
    }
    existing = (
        db.query(NovelRetrievalDocument)
        .filter(NovelRetrievalDocument.novel_id == novel_id)
        .all()
    )
    ex_map: dict[tuple[str, str], NovelRetrievalDocument] = {
        _doc_key(d.source_type, d.source_id): d for d in existing
    }
    removed = 0
    updated = 0
    skipped = 0
    for key, doc in list(ex_map.items()):
        if key not in new_map:
            _delete_one_document(db, store, doc)
            removed += 1
            ex_map.pop(key, None)
    for key, item in new_map.items():
        cur = ex_map.get(key)
        if cur and cur.checksum == item.get("checksum"):
            skipped += 1
            continue
        if cur:
            _delete_one_document(db, store, cur)
        _ingest_all_documents(db, store, novel_id, docs_payload=[item])
        updated += 1
    return {
        "status": "ok",
        "mode": "incremental",
        "documents": len(new_map),
        "removed": removed,
        "updated": updated,
        "skipped_unchanged": skipped,
    }


def retrieve_relevant_context_block(
    db: Session,
    novel_id: str,
    query_text: str,
    *,
    top_k: int | None = None,
    chapter_no: int | None = None,
) -> str:
    if not is_novel_rag_enabled(db, novel_id):
        return ""
    query = str(query_text or "").strip()
    if not query:
        return ""
    k = max(1, int(top_k or settings.novel_retrieval_top_k))
    started = time.perf_counter()
    per = max(2, int(settings.novel_retrieval_per_branch_k))
    store = QdrantStore()
    all_hits: list[dict[str, Any]] = []
    if settings.novel_retrieval_query_rewrite and query:
        subsearches: list[tuple[str, list[str] | None, str]] = [
            (f"剧情线 时间线 因果 转折 {query}", ["timeline", "plot"], "plotline"),
            (f"人物 关系 对立 密谋 {query}", ["character", "relation", "pet"], "social"),
            (f"技能 物品 武具 能力 {query}", ["item", "skill"], "gear"),
            (f"身份 立场 公开 未公开 称谓 {query}", ["character"], "identity"),
        ]
    else:
        subsearches = [(query, None, "all")]

    for qtext, types, _name in subsearches:
        try:
            v = embed_text(qtext)
        except Exception:
            logger.exception("embed for retrieval")
            continue
        if not types:
            r = store.search(
                v,
                limit=per * 2,
                filter_payload={
                    "must": [{"key": "novel_id", "match": {"value": novel_id}}]
                },
            )
        else:
            for st in types:
                r = store.search(
                    v,
                    limit=per,
                    filter_payload={
                        "must": [
                            {"key": "novel_id", "match": {"value": novel_id}},
                            {"key": "source_type", "match": {"value": st}},
                        ]
                    },
                )
                hits = r.get("result") or []
                if not isinstance(hits, list):
                    continue
                for h in hits:
                    if not isinstance(h, dict):
                        continue
                    h["_branch"] = _name
                    h["_q"] = qtext
                    all_hits.append(h)
            continue
        hits = r.get("result") or []
        for h in hits or []:
            if isinstance(h, dict):
                h["_branch"] = "wide"
                h["_q"] = qtext
                all_hits.append(h)

    merged = _dedupe_fuse_hits(all_hits)
    ranked = _rerank_hits(merged, query, chapter_no=chapter_no, top_k=k)
    elapsed = int(
        (time.perf_counter() - started) * 1000
        + 0.5
    )
    if not ranked:
        _log_query(
            db,
            novel_id=novel_id,
            query_text=query,
            top_k=k,
            hits=[],
            elapsed_ms=elapsed,
        )
        return ""
    lines = ["【长程记忆检索（RAG）】"]
    serialized: list[dict[str, Any]] = []
    for idx, h in enumerate(ranked[:k], start=1):
        payload = h.get("payload") or {}
        title = str(
            payload.get("title")
            or payload.get("source_type")
            or "记忆片段"
        ).strip()
        st = str(payload.get("source_type") or "").strip()
        text = str(payload.get("text") or "").strip()
        score = float(h.get("_fused", h.get("score", 0.0)) or 0.0)
        ch_no = payload.get("chapter_no")
        prefix = f"  {idx}. [{st}] {title}".strip()
        if ch_no:
            prefix += f"（第{ch_no}章）"
        stags = payload.get("state_tags")
        if stags and isinstance(stags, list) and stags:
            prefix += f" 标签:{','.join(str(x) for x in stags[:3])}"
        lines.append(f"{prefix}｜score={score:.3f}")
        if text:
            lines.append(f"     {text[:280]}")
        serialized.append(
            {
                "title": title,
                "source_type": st,
                "score": round(score, 6),
                "chapter_no": ch_no,
                "text": text[:220],
            }
        )
    _log_query(
        db,
        novel_id=novel_id,
        query_text=query,
        top_k=k,
        hits=serialized,
        elapsed_ms=elapsed,
    )
    return "\n".join(lines)


def _dedupe_fuse_hits(
    hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for h in hits:
        p = h.get("payload") or {}
        pk = p.get("chunk_id") or p.get("id")
        if not pk:
            body = (p.get("text") or "")[:120]
            pk = hashlib.md5(f"{p.get('document_id')}|{body}".encode()).hexdigest()[:20]
        sid = str(pk)
        s = float(h.get("score") or 0.0)
        branch_w = 1.05 if str(h.get("_branch") or "") in ("plotline", "identity") else 1.0
        fused = s * branch_w
        prev = by_id.get(sid)
        if prev is None or float(prev.get("_fused", 0) or 0) < fused:
            hc = {**h, "_fused": fused, "_base_score": s}
            by_id[sid] = hc
    return list(by_id.values())


def _rerank_hits(
    raw: list[dict[str, Any]],
    query: str,
    *,
    chapter_no: int | None = None,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    cn = try_int(chapter_no) if chapter_no is not None else None
    toks = set(
        t for t in re.split(r"[\s、，,。！？「」\[\]\"']+", query) if t and len(t) > 1
    ) | set(
        t for t in re.findall(r"[\u4e00-\u9fff]{2,4}", query)
    )
    scored: list[tuple[float, dict[str, Any]]] = []
    for h in raw:
        p = h.get("payload") or {}
        # 硬过滤：生成第 N 章时，RAG 不允许召回“未来章内容”。
        if cn is not None:
            p_ch = try_int(p.get("chapter_no"))
            p_intro = try_int(p.get("introduced_chapter"))
            if p_ch is not None and p_ch > cn:
                continue
            if p_intro is not None and p_intro > cn:
                continue
        text = f"{p.get('title', '')} {p.get('text', '')}"
        f = float(h.get("_fused", h.get("score", 0.0)) or 0.0)
        for t in toks:
            if t and t in text:
                f += 0.04
        ic = p.get("introduced_chapter")
        ec = p.get("expired_chapter")
        try:
            icn = int(ic) if ic is not None else 0
        except Exception:
            icn = 0
        try:
            ecn = int(ec) if ec is not None and ec != "" else 0
        except Exception:
            ecn = 0
        if cn is not None:
            if icn and 0 < icn <= cn:
                f += 0.12
            if ecn and ecn and cn > ecn:
                f -= 0.3
        scored.append((f, h))
    scored.sort(key=lambda x: -x[0])
    if not settings.novel_retrieval_rerank_enabled:
        out = [h for _, h in scored][: max(1, top_k * 2)]
    else:
        out = _mmr_select(scored, k=max(1, top_k))
    return out


def try_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    s = str(v).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    return None


def _mmr_select(
    scored: list[tuple[float, dict[str, Any]]],
    *,
    k: int,
) -> list[dict[str, Any]]:
    lam = float(
        min(0.95, max(0.1, settings.novel_retrieval_mmr_lambda or 0.55))
    )
    pool = [(fs, h) for fs, h in scored if fs is not None]
    pool.sort(key=lambda x: -x[0])
    if not pool:
        return []
    taken: list[dict[str, Any]] = []
    used_docs: set[str] = set()
    while len(taken) < k and pool:
        best_i = 0
        best_obj = -1e9
        for i, (fs, h) in enumerate(pool):
            p = h.get("payload") or {}
            did = str(p.get("document_id") or p.get("chunk_id") or "")
            div = 0.15 if did and did in used_docs else 0.0
            t1 = p.get("text") or ""
            dpen = 0.0
            for prev in taken:
                p2 = (prev.get("payload") or {}).get("text") or ""
                if t1 and p2 and t1[:120] == p2[:120]:
                    dpen = 0.2
            mmr = lam * fs - (1 - lam) * (div + dpen)
            if mmr > best_obj:
                best_obj = mmr
                best_i = i
        _fs, h = pool.pop(best_i)
        p = h.get("payload") or {}
        dds = str(p.get("document_id") or "")
        if dds:
            used_docs.add(dds)
        h["_mmr"] = best_obj
        taken.append(h)
    return taken


def _build_retrieval_documents_from_db(
    db: Session, novel_id: str
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    chapters = (
        db.query(NovelMemoryNormChapter)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .order_by(NovelMemoryNormChapter.chapter_no.asc())
        .all()
    )
    for row in chapters:
        parts = _chapter_timeline_parts(row)
        for pidx, part in enumerate(parts):
            summary = part["summary"][:2000]
            cks = part.get("chunks") or [summary]
            docs.append(
                _doc_entry(
                    source_type="timeline",
                    source_id=f"{row.chapter_no}:{pidx}",
                    title=f"第{row.chapter_no}章 {row.chapter_title or ''}｜{part.get('label', '块')}"[
                        :512
                    ],
                    summary=summary,
                    chunks=cks,
                    metadata={**(part.get("metadata") or {}), "rag_kind": "timeline"},
                )
            )

    for row in (
        db.query(NovelMemoryNormPlot)
        .filter(NovelMemoryNormPlot.novel_id == novel_id)
        .order_by(
            NovelMemoryNormPlot.priority.desc(), NovelMemoryNormPlot.sort_order.asc()
        )
        .all()
    ):
        re_list = _json_list(getattr(row, "related_entities_json", "[]"))
        eids: list[str] = []
        for e in re_list:
            s = str(e)
            if s:
                eids.append(s)
        pmeta = {
            "priority": getattr(row, "priority", 0) or 0,
            "introduced_chapter": getattr(row, "introduced_chapter", 0) or 0,
            "entity_ids": eids,
            "state_tags": [f"plotline:{(row.id or '')[:8]}"],
            "rag_kind": "plot",
        }
        t1 = (
            f"剧情线：{row.body}\n"
            f"类型：{getattr(row, 'plot_type', '') or ''}\n"
            f"阶段：{getattr(row, 'current_stage', '') or ''}\n"
        )
        t2 = (
            f"收束条件：{getattr(row, 'resolve_when', '') or ''}\n"
            f"相关实体：{'、'.join(eids[:8])}\n"
        )
        c1 = _split_into_chunks(
            t1, max_chars=settings.novel_retrieval_chunk_max_chars, overlap=0
        ) or [t1]
        c2 = _split_into_chunks(
            t2, max_chars=settings.novel_retrieval_chunk_max_chars, overlap=0
        ) or [t2]
        docs.append(
            _doc_entry(
                source_type="plot",
                source_id=row.id,
                title=row.body[:80],
                summary=(t1 + t2)[:2000],
                chunks=c1 + c2,
                metadata=pmeta,
            )
        )

    docs.extend(
        _entity_docs(
            "character",
            db.query(NovelMemoryNormCharacter)
            .filter(NovelMemoryNormCharacter.novel_id == novel_id)
            .all(),
        )
    )
    docs.extend(
        _entity_docs(
            "relation",
            db.query(NovelMemoryNormRelation)
            .filter(NovelMemoryNormRelation.novel_id == novel_id)
            .all(),
        )
    )
    docs.extend(
        _entity_docs(
            "item",
            db.query(NovelMemoryNormItem)
            .filter(NovelMemoryNormItem.novel_id == novel_id)
            .all(),
        )
    )
    docs.extend(
        _entity_docs(
            "skill",
            db.query(NovelMemoryNormSkill)
            .filter(NovelMemoryNormSkill.novel_id == novel_id)
            .all(),
        )
    )
    docs.extend(
        _entity_docs(
            "pet",
            db.query(NovelMemoryNormPet)
            .filter(NovelMemoryNormPet.novel_id == novel_id)
            .all(),
        )
    )
    return docs


def _chapter_timeline_parts(
    row: Any,
) -> list[dict[str, Any]]:
    key_facts = _json_list(row.key_facts_json)
    causal = _json_list(row.causal_results_json)
    scene_facts = _json_list(getattr(row, "scene_facts_json", "[]"))
    unresolved = _json_list(getattr(row, "unresolved_hooks_json", "[]"))
    cno = int(row.chapter_no or 0)
    ch = f"第{row.chapter_no}章 {row.chapter_title or ''}"
    mbase: dict[str, Any] = {
        "chapter_no": cno,
        "state_tags": [f"chapter:{cno}", "timeline"],
    }
    parts: list[dict[str, Any]] = []
    t_a = f"{ch}\n关键事实：{'；'.join(str(x) for x in key_facts[:8])}\n因果：{'；'.join(str(x) for x in causal[:6])}"
    parts.append(
        {
            "label": "章事实/因果",
            "summary": t_a,
            "chunks": _split_into_chunks(
                t_a, max_chars=settings.novel_retrieval_chunk_max_chars, overlap=60
            ),
            "metadata": mbase,
        }
    )
    t_b = f"{ch}\n场景事实：{'；'.join(str(x) for x in scene_facts[:6])}\n情绪：{getattr(row, 'emotional_state', '') or ''}"
    parts.append(
        {
            "label": "场景/情绪",
            "summary": t_b,
            "chunks": _split_into_chunks(
                t_b, max_chars=settings.novel_retrieval_chunk_max_chars, overlap=60
            ),
            "metadata": {**mbase, "state_tags": mbase["state_tags"] + ["scene"]},
        }
    )
    t_c = f"{ch}\n未解：{'；'.join(str(x) for x in unresolved[:6])}"
    parts.append(
        {
            "label": "伏笔/未解",
            "summary": t_c,
            "chunks": _split_into_chunks(
                t_c, max_chars=settings.novel_retrieval_chunk_max_chars, overlap=60
            ),
            "metadata": {**mbase, "state_tags": mbase["state_tags"] + ["hook"]},
        }
    )
    return parts


def _entity_docs(source_type: str, rows: list[Any]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for row in rows:
        eid = str(getattr(row, "id", "") or "")
        name = (
            getattr(row, "name", "")
            or getattr(row, "label", "")
            or getattr(row, "body", "")
            or f"{source_type}:{eid[:8]}"
        )
        aliases = _json_list(getattr(row, "aliases_json", "[]"))
        tags = _json_list(getattr(row, "tags_json", "[]"))
        detail = str(getattr(row, "detail_json", "{}") or "{}")
        relation = getattr(row, "relation", "")
        extra = []
        stags: list[str] = [source_type]
        if getattr(row, "role", None):
            extra.append(f"身份：{row.role}")
            stags.append("identity")
        if getattr(row, "status", None):
            extra.append(f"状态：{row.status}")
            stags.append("state")
        if relation:
            extra.append(f"关系：{relation}")
        if getattr(row, "src", None) or getattr(row, "dst", None):
            extra.append(f"对象：{getattr(row, 'src', '')}->{getattr(row, 'dst', '')}")
        if getattr(row, "body", None) and source_type != "plot":
            extra.append(f"正文：{getattr(row, 'body', '')}")
        if source_type == "relation" and (getattr(row, "subject_entity_id", None) or getattr(row, "object_entity_id", None)):
            pass
        intro_c = int(getattr(row, "introduced_chapter", 0) or 0) or int(
            getattr(row, "source_chapter_no", 0) or 0
        )
        ex_c: int | None = None
        raw_e = getattr(row, "expired_chapter", None)
        if raw_e is not None:
            try:
                ex_c = int(raw_e)
            except Exception:
                ex_c = None
        lc = str(getattr(row, "lifecycle_state", "") or "").strip() or "usable"
        ent_ids = [eid] if eid else []
        text = (
            f"{source_type}：{name}\n"
            f"别名：{'、'.join(str(x) for x in aliases[:8])}\n"
            f"标签：{'、'.join(str(x) for x in tags[:8])}\n"
            f"{'；'.join(extra)}\n"
            f"状态机：{lc}；首见章{intro_c}\n"
            f"详情：{detail[:600]}"
        )
        cks = _split_into_chunks(
            text, max_chars=settings.novel_retrieval_chunk_max_chars, overlap=80
        )
        pmeta: dict[str, Any] = {
            "is_active": bool(getattr(row, "is_active", True)),
            "source_chapter_no": int(
                getattr(row, "source_chapter_no", 0) or 0
            )
            or intro_c,
            "last_seen_chapter_no": int(
                getattr(row, "last_seen_chapter_no", 0) or 0
            ),
            "introduced_chapter": intro_c,
            "expired_chapter": ex_c,
            "entity_id": eid,
            "entity_ids": ent_ids,
            "state_tags": stags,
            "rag_kind": "identity" if (source_type == "character" and "identity" in stags) else source_type,
        }
        if source_type == "relation":
            pmeta["edge_kind"] = "relation"
            s_e = str(getattr(row, "src_entity_id", None) or "").strip()
            o_e = str(getattr(row, "dst_entity_id", None) or "").strip()
            pmeta["src_entity_id"] = s_e or None
            pmeta["dst_entity_id"] = o_e or None
            pmeta["subject_entity_id"] = s_e or None
            pmeta["object_entity_id"] = o_e or None
            pmeta["entity_ids"] = [x for x in (s_e, o_e) if x]
        docs.append(
            _doc_entry(
                source_type=source_type,
                source_id=str(eid) if eid else f"{name}:{id(row)}",
                title=str(name)[:120],
                summary=text[:2000],
                chunks=cks or [text],
                metadata=pmeta,
            )
        )
    return docs


def _doc_entry(
    *,
    source_type: str,
    source_id: str,
    title: str,
    summary: str,
    chunks: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    body_for_hash = summary + "|" + "||".join(
        c[:200] for c in chunks if (c or "").strip()
    )
    checksum = hashlib.md5(
        f"{source_type}:{source_id}:{body_for_hash}".encode("utf-8")
    ).hexdigest()
    clean_chunks = [c[:4000] for c in chunks if str(c or "").strip()]
    return {
        "source_type": source_type,
        "source_id": str(source_id),
        "title": title[:512],
        "summary": (summary or "")[:4000],
        "chunks": clean_chunks,
        "metadata": metadata,
        "checksum": checksum[:120],
    }


def _log_query(
    db: Session,
    *,
    novel_id: str,
    query_text: str,
    top_k: int,
    hits: list[dict[str, Any]],
    elapsed_ms: int,
) -> None:
    row = NovelRetrievalQueryLog(
        novel_id=novel_id,
        query_text=query_text,
        query_type="chapter_context",
        top_k=top_k,
        result_json=json.dumps(hits, ensure_ascii=False),
        latency_ms=max(0, int(elapsed_ms or 0)),
    )
    db.add(row)
    db.flush()


def _json_list(raw: str) -> list[Any]:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def sync_story_bible_and_retrieval(db: Session, novel_id: str) -> dict[str, Any]:
    from app.services.novel_story_bible_service import (
        create_story_bible_snapshot_from_normalized,
    )

    output: dict[str, Any] = {}
    if is_novel_story_bible_enabled(db, novel_id):
        snapshot = create_story_bible_snapshot_from_normalized(db, novel_id)
        output["story_bible_snapshot_id"] = snapshot.id
        output["story_bible_version"] = snapshot.version
    if is_novel_rag_enabled(db, novel_id):
        output["retrieval"] = sync_novel_retrieval_index(db, novel_id)
    return output
