"""
统一实体「可用性」状态机：与小说记忆规范化表字段配合，供 Judge / 检索 / 准图使用。

有限状态（字符串存表，便于迁移与人工编辑）：
latent -> introduced -> usable -> evolved
                   \\-> forbidden / expired
"""

from __future__ import annotations

from typing import Any

# 与规划一致的关键状态集合
LIFECYCLE_STATES = (
    "latent",
    "introduced",
    "usable",
    "evolved",
    "forbidden",
    "expired",
)

IDENTITY_STAGES = ("public", "hidden", "partial", "revealed", "compromised")

EXPOSED_IDENTITY_LEVELS = ("0", "1", "2", "3", "4", "5")  # 或自由文本，供展示


def infer_lifecycle_state(
    *,
    is_active: bool,
    introduced_chapter: int,
    last_seen_chapter: int,
    expired_chapter: int | None,
    explicit: str | None = None,
) -> str:
    if explicit and str(explicit).strip() in LIFECYCLE_STATES:
        return str(explicit).strip()
    if not is_active:
        if expired_chapter is not None and expired_chapter > 0:
            return "expired"
        return "forbidden"
    if expired_chapter is not None and last_seen_chapter and last_seen_chapter > expired_chapter:
        return "expired"
    if introduced_chapter <= 0 and last_seen_chapter <= 0:
        return "latent"
    if introduced_chapter > 0 and last_seen_chapter < introduced_chapter:
        return "introduced"
    return "usable"


def entity_usability_label(lifecycle: str) -> str:
    """
    供 prompt / 工具：三类写作约束
    - ready: 可直接使用
    - foreshadow: 已出现但尚不稳定 / 需铺垫
    - gated: 可写获得过程，不得无声空降
    """
    lc = (lifecycle or "usable").strip()
    if lc in ("expired", "forbidden"):
        return "gated"
    if lc in ("latent", "introduced"):
        return "foreshadow"
    return "ready"


def pick_detail_str(item: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""
