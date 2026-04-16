from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Novel
from app.models.volume import NovelChapterPlan
from app.services.chapter_plan_schema import normalize_beats_to_v2
from app.services.novel_llm_service import NovelLLMService


def latest_chapter_plan(
    db: Session,
    *,
    novel_id: str,
    chapter_no: int,
) -> NovelChapterPlan | None:
    return (
        db.query(NovelChapterPlan)
        .filter(
            NovelChapterPlan.novel_id == novel_id,
            NovelChapterPlan.chapter_no == chapter_no,
        )
        .order_by(NovelChapterPlan.updated_at.desc())
        .first()
    )


def normalized_plan_beats(plan: NovelChapterPlan | None) -> dict[str, Any]:
    if not plan:
        return {}
    try:
        beats = json.loads(plan.beats_json or "{}")
    except Exception:
        beats = {}
    return normalize_beats_to_v2(beats)


def collect_chapter_approval_issues(
    *,
    novel: Novel,
    chapter_no: int,
    chapter_text: str,
    llm: NovelLLMService,
    db: Session,
    plan: NovelChapterPlan | None = None,
    include_plan_audit: bool = True,
) -> list[str]:
    issues: list[str] = []
    content = chapter_text or ""

    if (
        settings.novel_setting_audit_on_approve
        and settings.novel_setting_audit_block_on_violation
        and content.strip()
    ):
        audit = llm.audit_chapter_against_constraints_sync(novel, content, db)
        if not audit.get("ok"):
            violations = [
                str(x).strip() for x in (audit.get("violations") or []) if str(x).strip()
            ]
            if violations:
                issues.extend([f"设定审计未通过：{x}" for x in violations])
            else:
                issues.append("设定审计未通过：存在未归档的设定冲突")

    if include_plan_audit and content.strip():
        plan = plan or latest_chapter_plan(
            db,
            novel_id=novel.id,
            chapter_no=chapter_no,
        )
        if plan:
            beats = normalized_plan_beats(plan)
            plan_audit = llm.audit_chapter_against_plan_sync(
                chapter_no=chapter_no,
                plan_title=plan.chapter_title,
                beats=beats,
                chapter_text=content,
                db=db,
            )
            if not plan_audit.get("ok"):
                issues.extend(
                    [
                        f"执行卡未满足：{x}"
                        for x in (plan_audit.get("violations") or [])
                        if str(x).strip()
                    ]
                )

    return issues
