from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.novel import Chapter, Novel
from app.models.novel_judge import NovelJudgeIssue, NovelJudgeRun
from app.models.novel_memory_norm import NovelMemoryNormOutline
from app.services.chapter_plan_schema import chapter_plan_guard_payload, normalize_beats_to_v2
from app.services.novel_repo import chapter_content_metrics

_COMMON_TOKENS = {
    "这", "那", "一个", "一种", "一些", "进行", "开始", "已经", "并且", "以及", "然后",
    "于是", "因为", "所以", "他们", "她们", "自己", "没有", "我们", "你们", "不是", "如果",
    "但是", "而且", "可以", "需要", "必须", "本章", "当前", "阶段", "出现", "发生", "推进",
}
_AI_CLICHE_PHRASES = [
    "总而言之",
    "综上所述",
    "值得一提的是",
    "不可否认",
    "显而易见",
    "某种程度上",
    "换言之",
]
_SENSORY_TOKENS = ("风", "雨", "冷", "热", "光", "影", "血", "汗", "脚步", "气息", "疼", "香", "腥")
_EMOTION_TOKENS = ("怒", "惊", "怕", "喜", "悲", "恨", "慌", "紧张", "压抑", "酸涩", "发麻", "发冷")


def run_chapter_judge_suite(
    db: Session,
    *,
    novel: Novel,
    chapter: Chapter,
    chapter_text: str,
    plan_title: str = "",
    beats: Any = None,
    workflow_run_id: str | None = None,
    trigger_source: str = "generation",
) -> dict[str, Any]:
    metrics = chapter_content_metrics(chapter_text)
    payload = {
        "trigger_source": trigger_source,
        "plan_title": plan_title,
        "metrics": metrics,
        "chapter_no": chapter.chapter_no,
    }
    judge_run = NovelJudgeRun(
        novel_id=novel.id,
        chapter_id=chapter.id,
        workflow_run_id=workflow_run_id,
        judge_type="chapter_suite",
        status="running",
        model_name="heuristic-v1",
        summary="",
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(judge_run)
    db.flush()

    issues: list[dict[str, Any]] = []
    issues.extend(_judge_narrative_quality(novel, chapter_text, metrics))
    issues.extend(_judge_ai_style(chapter_text))
    issues.extend(_judge_expressive_quality(chapter_text, metrics))
    issues.extend(_judge_plan_alignment(chapter_text, plan_title=plan_title, beats=beats))
    issues.extend(_judge_forbidden_constraints(db, novel.id, chapter_text))

    score = 100.0
    severity_counter: Counter[str] = Counter()
    for issue in issues:
        severity = str(issue.get("severity") or "warning")
        severity_counter[severity] += 1
        score -= {"error": 18, "warning": 8, "info": 3}.get(severity, 5)
        db.add(
            NovelJudgeIssue(
                judge_run_id=judge_run.id,
                novel_id=novel.id,
                chapter_id=chapter.id,
                severity=severity,
                issue_type=str(issue.get("issue_type") or "quality"),
                title=str(issue.get("title") or "")[:255],
                evidence_json=json.dumps(issue.get("evidence") or [], ensure_ascii=False),
                suggestion=str(issue.get("suggestion") or ""),
                blocking=bool(issue.get("blocking", False)),
                resolved=False,
            )
        )

    judge_run.score = max(0.0, round(score, 2))
    judge_run.blocking = any(bool(issue.get("blocking")) for issue in issues)
    judge_run.status = "done"
    judge_run.summary = _judge_summary(judge_run.score, severity_counter, issues)
    judge_run.payload_json = json.dumps(
        {
            **payload,
            "severity_counter": dict(severity_counter),
            "issue_count": len(issues),
        },
        ensure_ascii=False,
    )
    db.add(judge_run)
    db.flush()
    return {
        "judge_run_id": judge_run.id,
        "score": judge_run.score,
        "blocking": judge_run.blocking,
        "summary": judge_run.summary,
        "severity_counter": dict(severity_counter),
        "issue_count": len(issues),
    }


def _judge_narrative_quality(
    novel: Novel,
    chapter_text: str,
    metrics: dict[str, int],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    target_words = int(getattr(novel, "chapter_target_words", 3000) or 3000)
    body_chars = int(metrics.get("body_chars", 0) or 0)
    paragraph_count = int(metrics.get("paragraph_count", 0) or 0)
    if body_chars < max(600, int(target_words * 0.55)):
        issues.append(
            {
                "severity": "warning",
                "issue_type": "narrative_quality",
                "title": "章节篇幅偏短",
                "evidence": [f"正文约 {body_chars} 字", f"目标约 {target_words} 字"],
                "suggestion": "补充场景推进、人物反应或结果承接，避免剧情只交代结论。",
            }
        )
    expected_paragraphs = max(3, body_chars // 700)
    if paragraph_count < expected_paragraphs:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "readability",
                "title": "段落切分偏少",
                "evidence": [f"当前段落数 {paragraph_count}", f"建议至少 {expected_paragraphs} 段"],
                "suggestion": "增加对话、动作、心理和环境切换时的换段，提升网文阅读节奏。",
            }
        )
    duplicate_paras = _duplicate_paragraphs(chapter_text)
    if duplicate_paras:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "repetition",
                "title": "存在重复段落或近重复段落",
                "evidence": duplicate_paras[:3],
                "suggestion": "压缩重复描述，避免同一动作、情绪或信息重复表达。",
            }
        )
    if _ending_too_abrupt(chapter_text):
        issues.append(
            {
                "severity": "info",
                "issue_type": "pacing",
                "title": "结尾可能偏突兀",
                "evidence": ["结尾段落过短或缺少承接/钩子"],
                "suggestion": "可补一个情绪落点、悬念或下章触发点。",
            }
        )
    return issues


def _judge_ai_style(chapter_text: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    hits = [phrase for phrase in _AI_CLICHE_PHRASES if phrase in (chapter_text or "")]
    if hits:
        issues.append(
            {
                "severity": "info",
                "issue_type": "style",
                "title": "存在较明显的套路化表达",
                "evidence": hits[:5],
                "suggestion": "替换成更具体的场景或人物语气，减少总结式、议论文式表达。",
            }
        )
    return issues


def _judge_expressive_quality(
    chapter_text: str,
    metrics: dict[str, int],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    text = str(chapter_text or "")
    body_chars = int(metrics.get("body_chars", 0) or 0)
    dialogue_lines = len(re.findall(r"[“\"「].+?[”\"」]", text))
    if body_chars >= 1200 and dialogue_lines <= 1:
        issues.append(
            {
                "severity": "info",
                "issue_type": "expressive_dialogue",
                "title": "对白区分度偏弱",
                "evidence": [f"正文约 {body_chars} 字", f"对白片段 {dialogue_lines} 处"],
                "suggestion": "可补入更有角色口吻的对白或言语交锋，减少纯叙述推进。",
            }
        )
    sensory_hits = [tok for tok in _SENSORY_TOKENS if tok in text]
    if body_chars >= 1500 and len(sensory_hits) < 2:
        issues.append(
            {
                "severity": "info",
                "issue_type": "expressive_scene",
                "title": "场景可视化略弱",
                "evidence": ["感官描写关键词较少", *sensory_hits[:3]],
                "suggestion": "增加环境、动作触感或声音细节，让场景更可见可感。",
            }
        )
    emotion_hits = [tok for tok in _EMOTION_TOKENS if tok in text]
    if body_chars >= 1500 and len(emotion_hits) < 2:
        issues.append(
            {
                "severity": "info",
                "issue_type": "expressive_emotion",
                "title": "情绪递进不够明显",
                "evidence": ["显性情绪锚点偏少"],
                "suggestion": "补足人物情绪变化的触发、反应与余波，避免情绪只停留在结论句。",
            }
        )
    return issues


def _judge_plan_alignment(
    chapter_text: str,
    *,
    plan_title: str,
    beats: Any,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not beats:
        return issues
    payload = chapter_plan_guard_payload(normalize_beats_to_v2(beats), plan_title=plan_title)
    hard = payload.get("hard_requirements", {}) if isinstance(payload, dict) else {}
    repair = payload.get("repair_targets", {}) if isinstance(payload, dict) else {}
    texts_to_cover: list[tuple[str, str]] = [
        ("章节目标", str(hard.get("chapter_goal") or "").strip()),
        ("核心冲突", str(hard.get("core_conflict") or "").strip()),
        ("关键转折", str(hard.get("key_turn") or "").strip()),
        ("结尾钩子", str(repair.get("ending_hook") or "").strip()),
    ]
    uncovered: list[str] = []
    for label, text in texts_to_cover:
        if text and not _rough_text_hit(chapter_text, text):
            uncovered.append(f"{label}：{text[:60]}")

    must_happen = [str(x).strip() for x in (hard.get("must_happen") or []) if str(x).strip()]
    must_happen_uncovered = [item[:60] for item in must_happen if not _rough_text_hit(chapter_text, item)]
    if uncovered:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "plan_alignment",
                "title": "章节对计划核心要点覆盖不足",
                "evidence": uncovered[:4],
                "suggestion": "补足章节目标、冲突或转折的显性落点，让正文更贴合执行卡。",
            }
        )
    if len(must_happen_uncovered) >= 2:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "plan_alignment",
                "title": "执行卡中的关键事件落地偏弱",
                "evidence": must_happen_uncovered[:4],
                "suggestion": "检查 must_happen 事项是否真的在正文中完成，而不是只在计划里存在。",
            }
        )

    must_not_hits = [
        item[:60]
        for item in (hard.get("must_not") or [])
        if str(item).strip() and _literal_hit(chapter_text, str(item))
    ]
    if must_not_hits:
        issues.append(
            {
                "severity": "warning",
                "issue_type": "plan_guard",
                "title": "正文可能触碰执行卡禁止项",
                "evidence": must_not_hits[:4],
                "suggestion": "复核这些禁止项是否被正文直接写出，必要时回退或改写。",
            }
        )

    reserved_hits = []
    for item in (hard.get("reserved_for_later") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("item") or "").strip()
        if text and _literal_hit(chapter_text, text):
            reserved_hits.append(text[:60])
    if reserved_hits:
        issues.append(
            {
                "severity": "info",
                "issue_type": "foreshadowing",
                "title": "正文可能提前推进了保留到后续章节的内容",
                "evidence": reserved_hits[:4],
                "suggestion": "确认这些内容是否只是轻微铺垫，而非已经提前兑现。",
            }
        )
    return issues


def _judge_forbidden_constraints(
    db: Session,
    novel_id: str,
    chapter_text: str,
) -> list[dict[str, Any]]:
    outline = db.get(NovelMemoryNormOutline, novel_id)
    if not outline:
        return []
    try:
        items = json.loads(outline.forbidden_constraints_json or "[]")
    except Exception:
        items = []
    hits: list[str] = []
    for raw in items:
        text = str(raw.get("body") if isinstance(raw, dict) else raw or "").strip()
        if len(text) < 4:
            continue
        if _literal_hit(chapter_text, text):
            hits.append(text[:80])
    if not hits:
        return []
    return [
        {
            "severity": "warning",
            "issue_type": "consistency",
            "title": "正文可能触碰全局设定防火墙",
            "evidence": hits[:4],
            "suggestion": "核对是否真的违反设定，或只是表述相近；必要时重写相关情节。",
        }
    ]


def _judge_summary(
    score: float,
    severity_counter: Counter[str],
    issues: list[dict[str, Any]],
) -> str:
    if not issues:
        return f"本章 Judge 通过，未发现明显问题，综合分 {score:.1f}。"
    parts = [f"综合分 {score:.1f}"]
    if severity_counter:
        parts.append(
            "；".join(
                f"{k}:{v}" for k, v in sorted(severity_counter.items(), key=lambda x: x[0])
            )
        )
    top_titles = [str(issue.get("title") or "").strip() for issue in issues[:3] if str(issue.get("title") or "").strip()]
    if top_titles:
        parts.append("重点关注：" + "；".join(top_titles))
    return "，".join(parts)


def _duplicate_paragraphs(chapter_text: str) -> list[str]:
    paras = [
        _normalize_line(p)
        for p in re.split(r"\n\s*\n", str(chapter_text or "").strip())
        if _normalize_line(p)
    ]
    counter = Counter(paras)
    return [p[:80] for p, count in counter.items() if count > 1 and len(p) >= 12]


def _ending_too_abrupt(chapter_text: str) -> bool:
    paras = [p.strip() for p in str(chapter_text or "").splitlines() if p.strip()]
    if not paras:
        return False
    tail = paras[-1]
    compact = _normalize_line(tail)
    return len(compact) < 22


def _literal_hit(content: str, target: str) -> bool:
    content_norm = _normalize_line(content)
    target_norm = _normalize_line(target)
    if len(target_norm) < 4:
        return False
    return target_norm in content_norm


def _rough_text_hit(content: str, target: str) -> bool:
    target_tokens = _keywords(target)
    if not target_tokens:
        return True
    content_tokens = set(_keywords(content))
    overlap = len([token for token in target_tokens if token in content_tokens])
    return overlap >= max(1, min(2, len(target_tokens) // 2))


def _keywords(text: str) -> list[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    cn = re.findall(r"[\u4e00-\u9fff]{2,}", raw)
    en = re.findall(r"[a-z0-9_]{3,}", raw)
    tokens = [*cn, *en]
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _COMMON_TOKENS:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out[:16]


def _normalize_line(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()
