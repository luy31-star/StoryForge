"""
小说核心能力升级四阶段：最小验收指标（静态量表 + 可观测运行数据）。
供前端「回归观察」面板与人工对照使用。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.novel import Chapter, NovelGenerationLog
from app.models.novel_judge import NovelJudgeIssue, NovelJudgeRun
from app.models.novel_memory_runtime import NovelMemoryUpdateRun
from app.models.novel_memory_norm import (
    NovelMemoryNormChapter,
    NovelMemoryNormCharacter,
    NovelMemoryNormItem,
    NovelMemoryNormPet,
    NovelMemoryNormRelation,
    NovelMemoryNormSkill,
)
from app.models.novel_retrieval import NovelRetrievalQueryLog
from app.models.novel_story_bible import NovelStoryBibleFact, NovelStoryBibleSnapshot


RUBRIC: dict[str, Any] = {
    "phases": [
        {
            "id": "retrieval",
            "name": "检索底座",
            "metrics": [
                "RAG 平均延迟（ms，来自 query log）",
                "每次召回条目数、跨类型覆盖（timeline/plot/entity/gear）",
                "同章约束：introduced_chapter / expired_chapter 与当前章一致性（启发式，见 payload）",
            ],
        },
        {
            "id": "state_machine",
            "name": "显式状态机",
            "metrics": [
                "人物/物品/技能 lifecycle_state 分布",
                "身份字段 identity_stage / exposed_identity_level 覆盖率",
                "关系行 src_entity_id / dst_entity_id 可解析率",
            ],
        },
        {
            "id": "quasi_graph",
            "name": "准图与 Story Bible",
            "metrics": [
                "关系事实是否带双端点 subject/object entity_id",
                "子图块是否随章计划关键词注入（见写章 prompt 日志）",
            ],
        },
        {
            "id": "expressive",
            "name": "表现力",
            "metrics": [
                "Judge 分数与表现力相关 issue 数（若启用）",
                "开启表现力 pass 的章节与强度档位",
            ],
        },
    ],
    "notes": "完整主观评价仍建议配合读者试读与人工抽检。",
}


def build_core_evaluation_snapshot(db: Session, novel_id: str) -> dict[str, Any]:
    def _load_json(raw: str, fallback: Any) -> Any:
        try:
            data = json.loads(raw or "")
        except Exception:
            return fallback
        return data

    retrieval_logs = (
        db.query(NovelRetrievalQueryLog)
        .filter(NovelRetrievalQueryLog.novel_id == novel_id)
        .all()
    )
    n_rag = len(retrieval_logs)
    avg_lat = (
        sum(int(getattr(row, "latency_ms", 0) or 0) for row in retrieval_logs) / n_rag
        if n_rag
        else None
    )
    hit_counts: list[int] = []
    unique_type_counts: list[int] = []
    identity_hit_logs = 0
    for row in retrieval_logs:
        result = _load_json(getattr(row, "result_json", "") or "[]", [])
        hits = result if isinstance(result, list) else []
        hit_counts.append(len(hits))
        hit_types: set[str] = set()
        has_identity = False
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else hit
            source_type = str(payload.get("source_type") or payload.get("doc_type") or "").strip()
            rag_kind = str(payload.get("rag_kind") or "").strip()
            identity_stage = str(payload.get("identity_stage") or "").strip()
            if source_type:
                hit_types.add(source_type)
            if rag_kind:
                hit_types.add(f"rag:{rag_kind}")
            if rag_kind == "identity" or identity_stage:
                has_identity = True
        unique_type_counts.append(len(hit_types))
        if has_identity:
            identity_hit_logs += 1

    n_ch = (
        db.query(func.count(Chapter.id))
        .filter(Chapter.novel_id == novel_id, Chapter.status == "approved")
        .scalar()
        or 0
    )
    n_judge = (
        db.query(func.count(NovelJudgeRun.id))
        .filter(NovelJudgeRun.novel_id == novel_id, NovelJudgeRun.status == "done")
        .scalar()
        or 0
    )
    avg_j = (
        db.query(func.avg(NovelJudgeRun.score))
        .filter(NovelJudgeRun.novel_id == novel_id, NovelJudgeRun.status == "done")
        .scalar()
    )

    def _count(model: Any) -> int:
        return (
            db.query(func.count(model.id))
            .filter(model.novel_id == novel_id)
            .scalar()
            or 0
        )

    chars = db.query(NovelMemoryNormCharacter).filter(NovelMemoryNormCharacter.novel_id == novel_id).all()
    items = db.query(NovelMemoryNormItem).filter(NovelMemoryNormItem.novel_id == novel_id).all()
    skills = db.query(NovelMemoryNormSkill).filter(NovelMemoryNormSkill.novel_id == novel_id).all()
    pets = db.query(NovelMemoryNormPet).filter(NovelMemoryNormPet.novel_id == novel_id).all()
    rels = db.query(NovelMemoryNormRelation).filter(NovelMemoryNormRelation.novel_id == novel_id).all()
    norm_chapters = (
        db.query(NovelMemoryNormChapter)
        .filter(NovelMemoryNormChapter.novel_id == novel_id)
        .all()
    )

    lifecycle_distribution: dict[str, int] = {}
    for row in [*chars, *items, *skills, *pets]:
        state = str(getattr(row, "lifecycle_state", "") or "unknown")
        lifecycle_distribution[state] = lifecycle_distribution.get(state, 0) + 1

    identity_covered = 0
    for row in chars:
        if str(getattr(row, "identity_stage", "") or "").strip() or str(
            getattr(row, "exposed_identity_level", "") or ""
        ).strip():
            identity_covered += 1

    linked_relations = 0
    for row in rels:
        if getattr(row, "src_entity_id", None) and getattr(row, "dst_entity_id", None):
            linked_relations += 1

    snapshot_covered = 0
    transition_covered = 0
    for row in norm_chapters:
        snapshot = _load_json(getattr(row, "state_snapshot_json", None) or "{}", {})
        transitions = _load_json(
            getattr(row, "state_transition_summary_json", None) or "[]",
            [],
        )
        if isinstance(snapshot, dict) and snapshot.get("counts"):
            snapshot_covered += 1
        if isinstance(transitions, list) and transitions:
            transition_covered += 1

    latest_snapshot = (
        db.query(NovelStoryBibleSnapshot)
        .filter(NovelStoryBibleSnapshot.novel_id == novel_id)
        .order_by(NovelStoryBibleSnapshot.created_at.desc())
        .first()
    )
    story_bible_facts_total = 0
    story_bible_fact_linked = 0
    if latest_snapshot:
        facts = (
            db.query(NovelStoryBibleFact)
            .filter(NovelStoryBibleFact.snapshot_id == latest_snapshot.id)
            .all()
        )
        story_bible_facts_total = len(facts)
        for fact in facts:
            if getattr(fact, "subject_entity_id", None) and getattr(fact, "object_entity_id", None):
                story_bible_fact_linked += 1

    expressive_issue_total = (
        db.query(func.count(NovelJudgeIssue.id))
        .filter(
            NovelJudgeIssue.novel_id == novel_id,
            NovelJudgeIssue.issue_type.in_(
                ["expressive_dialogue", "expressive_scene", "expressive_emotion"]
            ),
        )
        .scalar()
        or 0
    )
    expressive_pass_logs = (
        db.query(NovelGenerationLog)
        .filter(
            NovelGenerationLog.novel_id == novel_id,
            NovelGenerationLog.event == "chapter_expressive_enhance_done",
        )
        .all()
    )
    strength_distribution: dict[str, int] = {}
    for row in expressive_pass_logs:
        meta = _load_json(getattr(row, "meta_json", "") or "{}", {})
        strength = str(meta.get("strength") or "unknown")
        strength_distribution[strength] = strength_distribution.get(strength, 0) + 1
    memory_runs = (
        db.query(NovelMemoryUpdateRun)
        .filter(NovelMemoryUpdateRun.novel_id == novel_id)
        .all()
    )
    memory_run_status_distribution: dict[str, int] = {}
    source_applied_runs = 0
    assets_fresh_runs = 0
    diff_covered_runs = 0
    for row in memory_runs:
        status = str(getattr(row, "status", "") or "unknown")
        memory_run_status_distribution[status] = (
            memory_run_status_distribution.get(status, 0) + 1
        )
        if str(getattr(row, "norm_status", "") or "") == "ok" and str(
            getattr(row, "snapshot_status", "") or ""
        ) == "ok":
            source_applied_runs += 1
        if str(getattr(row, "story_bible_status", "") or "") in {"ok", "skipped"} and str(
            getattr(row, "rag_status", "") or ""
        ) in {"ok", "skipped"}:
            assets_fresh_runs += 1
        diff_summary = _load_json(getattr(row, "diff_summary_json", "") or "{}", {})
        if isinstance(diff_summary, dict) and diff_summary.get("summary"):
            diff_covered_runs += 1

    return {
        "status": "ok",
        "novel_id": novel_id,
        "rubric": RUBRIC,
        "observed": {
            "retrieval_query_logs": int(n_rag),
            "retrieval_avg_latency_ms": float(avg_lat) if avg_lat is not None else None,
            "retrieval_avg_hits_per_query": (
                round(sum(hit_counts) / len(hit_counts), 2) if hit_counts else None
            ),
            "retrieval_avg_type_coverage_per_query": (
                round(sum(unique_type_counts) / len(unique_type_counts), 2)
                if unique_type_counts
                else None
            ),
            "retrieval_identity_hit_log_rate": (
                round(identity_hit_logs / n_rag, 4) if n_rag else None
            ),
            "approved_chapters": int(n_ch),
            "judge_runs": int(n_judge),
            "judge_avg_score": float(avg_j) if avg_j is not None else None,
            "state_machine": {
                "characters": len(chars),
                "items": len(items),
                "skills": len(skills),
                "pets": len(pets),
                "relations": len(rels),
                "lifecycle_distribution": lifecycle_distribution,
                "identity_field_coverage_rate": (
                    round(identity_covered / len(chars), 4) if chars else None
                ),
                "relation_entity_link_rate": (
                    round(linked_relations / len(rels), 4) if rels else None
                ),
                "chapter_state_snapshot_coverage_rate": (
                    round(snapshot_covered / len(norm_chapters), 4)
                    if norm_chapters
                    else None
                ),
                "chapter_transition_coverage_rate": (
                    round(transition_covered / len(norm_chapters), 4)
                    if norm_chapters
                    else None
                ),
            },
            "quasi_graph": {
                "story_bible_snapshots": _count(NovelStoryBibleSnapshot),
                "story_bible_facts": story_bible_facts_total,
                "story_bible_fact_link_rate": (
                    round(story_bible_fact_linked / story_bible_facts_total, 4)
                    if story_bible_facts_total
                    else None
                ),
            },
            "expressive": {
                "judge_issue_count": int(expressive_issue_total),
                "enhance_pass_chapters": len(expressive_pass_logs),
                "enhance_strength_distribution": strength_distribution,
            },
            "memory_update": {
                "runs": len(memory_runs),
                "status_distribution": memory_run_status_distribution,
                "source_applied_rate": (
                    round(source_applied_runs / len(memory_runs), 4) if memory_runs else None
                ),
                "derived_assets_fresh_rate": (
                    round(assets_fresh_runs / len(memory_runs), 4) if memory_runs else None
                ),
                "diff_coverage_rate": (
                    round(diff_covered_runs / len(memory_runs), 4) if memory_runs else None
                ),
            },
        },
    }
