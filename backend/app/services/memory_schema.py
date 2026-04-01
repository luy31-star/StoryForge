from __future__ import annotations

from typing import Any

PLOT_TYPE_CORE = "Core"
PLOT_TYPE_ARC = "Arc"
PLOT_TYPE_TRANSIENT = "Transient"
PLOT_TYPE_VALUES = (PLOT_TYPE_CORE, PLOT_TYPE_ARC, PLOT_TYPE_TRANSIENT)

ALIAS_KEYS = ("aliases", "alias", "aka")

IRREVERSIBLE_FACT_KEYWORDS = (
    "死亡",
    "身亡",
    "牺牲",
    "暴露",
    "揭穿",
    "公开",
    "坦白",
    "认出",
    "识破",
    "订婚",
    "成婚",
    "结婚",
    "决裂",
    "绝交",
    "背叛",
    "收徒",
    "拜师",
    "立誓",
    "签约",
    "契约",
    "失忆",
    "觉醒",
    "破境",
    "突破",
    "重伤",
    "残废",
    "失去",
    "遗失",
    "夺走",
    "继承",
    "易主",
    "怀孕",
)


def normalize_plot_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "core":
        return PLOT_TYPE_CORE
    if raw == "arc":
        return PLOT_TYPE_ARC
    return PLOT_TYPE_TRANSIENT


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_int(value: Any, *, minimum: int = 0, maximum: int = 100, default: int = 0) -> int:
    return max(minimum, min(maximum, coerce_int(value, default)))


def dedupe_clean_strs(items: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if limit is not None and len(out) >= limit:
            break
    return out


def extract_aliases(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        out: list[str] = []
        for key in ALIAS_KEYS:
            raw = payload.get(key)
            if isinstance(raw, list):
                out.extend(dedupe_clean_strs(raw))
            elif isinstance(raw, str) and raw.strip():
                out.extend(dedupe_clean_strs([raw]))
        return dedupe_clean_strs(out, limit=12)
    if isinstance(payload, list):
        return dedupe_clean_strs(payload, limit=12)
    if isinstance(payload, str) and payload.strip():
        return [payload.strip()]
    return []


def memory_schema_guide() -> dict[str, Any]:
    return {
        "open_plots": {
            "purpose": "只记录仍活跃、未来 5 章以上仍会持续影响剧情的长期线索。",
            "rules": [
                "优先写跨章目标，不写本章顺手可解决的小问题。",
                "重要线索用对象结构，至少补 plot_type、priority、estimated_duration。",
                "body 使用主名，必要别名写入 aliases 或在 body 中明确“又名”。",
                "current_stage 只写当前推进到哪一步，不写冗长剧情摘要。",
                "resolve_when 写清什么条件达成后才算真正收束。",
            ],
            "template": {
                "body": "主角查清黑匣子的来源",
                "plot_type": PLOT_TYPE_CORE,
                "priority": 95,
                "estimated_duration": 12,
                "current_stage": "已确认与父亲有关，但来源未明",
                "resolve_when": "确认来源 + 锁定投放者 + 拿到证据",
            },
        },
        "key_facts": {
            "purpose": "只记录不可逆变化、后续必须引用或不能改写的事实锚点。",
            "rules": [
                "每章建议控制在 3-8 条。",
                "优先写身份暴露、关系破裂、重要物品易主、受伤、立誓、世界规则确认等事实。",
                "过程性细节、普通情绪波动、短时推测不进 key_facts。",
            ],
        },
        "notes": {
            "purpose": "弱提醒，只放风格底线、容易吃书的雷点、人工提醒。",
            "rules": [
                "不要堆普通剧情摘要。",
                "不能替代 key_facts、open_plots 或 forbidden_constraints。",
            ],
        },
        "forbidden_constraints": {
            "purpose": "硬约束，正文禁止违反的设定防火墙。",
            "rules": [
                "只放绝对禁止事项，如“不能提前暴露身份”“某能力当前不可用”。",
                "一旦进入该字段，就会参与章节审计。",
            ],
        },
        "entity_naming": {
            "purpose": "统一主名与别名，降低召回丢失。",
            "rules": [
                "角色、物品、技能、宠物统一使用主名。",
                "别名放 aliases，正文可自由叫法，但结构化记忆尽量保持主名一致。",
            ],
        },
        "entity_scheduling": {
            "purpose": "用 influence_score 和 is_active 调度热层，避免无关实体占用上下文。",
            "rules": [
                "未来 3-5 章持续重要的实体提高 influence_score。",
                "已退场、失效、死亡、替换的实体标记 is_active=false。",
            ],
        },
    }


def is_irreversible_fact(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return any(keyword in raw for keyword in IRREVERSIBLE_FACT_KEYWORDS)
