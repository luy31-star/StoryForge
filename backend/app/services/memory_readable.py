"""将小说结构化记忆 JSON 转为中文可读文本（供前端「记忆」页展示）。"""

from __future__ import annotations

import json
from typing import Any


# 不参与「自动生成中文阅读」展示的字段（人工覆盖文案单独处理）
_SKIP_READABLE_KEYS: frozenset[str] = frozenset({"readable_zh_override"})

_KEY_LABELS: dict[str, str] = {
    "characters": "人物",
    "relations": "人物关系",
    "inventory": "物品与道具",
    "skills": "技能与能力",
    "pets": "宠物与同伴",
    "open_plots": "未完结剧情线",
    "notes": "一致性备忘",
    "world_rules": "世界观规则",
    "main_plot": "主线剧情",
    "arcs": "篇章与卷",
    "themes": "主题",
    "locations": "地点",
    "factions": "势力",
    "timeline": "时间线",
    "raw_framework_tail": "原始框架摘录",
}


def _label_for_key(key: str) -> str:
    return _KEY_LABELS.get(key, key)


def _format_scalar(v: Any) -> str:
    if v is None:
        return "（空）"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, indent=2)
    return str(v)


def _format_dict_lines(obj: dict[str, Any], bullet: str = "  • ") -> list[str]:
    lines: list[str] = []
    for k, v in obj.items():
        lk = _label_for_key(k) if k in _KEY_LABELS or k.isascii() else k
        if isinstance(v, (list, dict)):
            lines.append(f"{bullet}{lk}：")
            lines.extend(_format_any(v, indent=2))
        else:
            lines.append(f"{bullet}{lk}：{_format_scalar(v)}")
    return lines


def _format_any(val: Any, indent: int = 0) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    if isinstance(val, list):
        for i, item in enumerate(val, 1):
            if isinstance(item, dict):
                lines.append(f"{pad}{i}.")
                lines.extend(_format_dict_lines(item, bullet=f"{pad}  • "))
            else:
                lines.append(f"{pad}{i}. {_format_scalar(item)}")
    elif isinstance(val, dict):
        lines.extend(_format_dict_lines(val, bullet=f"{pad}• "))
    else:
        lines.append(f"{pad}{_format_scalar(val)}")
    return lines


def _dict_to_auto_readable_zh(data: dict[str, Any]) -> str:
    lines: list[str] = []
    used: set[str] = set()

    preferred_order = list(_KEY_LABELS.keys())
    for key in preferred_order:
        if key in _SKIP_READABLE_KEYS or key not in data:
            continue
        val = data[key]
        if val in (None, "", [], {}):
            continue
        used.add(key)
        title = _KEY_LABELS.get(key, key)
        lines.append(f"【{title}】")
        lines.extend(_format_any(val))
        lines.append("")

    for key in sorted(data.keys()):
        if key in used or key in _SKIP_READABLE_KEYS:
            continue
        val = data[key]
        if val in (None, "", [], {}):
            continue
        title = _label_for_key(key)
        lines.append(f"【{title}】")
        lines.extend(_format_any(val))
        lines.append("")

    out = "\n".join(lines).strip()
    return out if out else "（记忆 JSON 为空对象）"


def memory_payload_readable_zh_auto(payload_json: str) -> str:
    """由结构化 JSON 自动排版的中文阅读（忽略 readable_zh_override）。"""
    raw = (payload_json or "").strip()
    if not raw:
        return "（尚无记忆数据）"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "（内容不是合法 JSON，以下为原文节选）\n" + raw[:4000]

    if not isinstance(data, dict):
        return _format_scalar(data)
    return _dict_to_auto_readable_zh(data)


def memory_payload_to_readable_zh(payload_json: str) -> str:
    raw = (payload_json or "").strip()
    if not raw:
        return "（尚无记忆数据）"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "（内容不是合法 JSON，以下为原文节选）\n" + raw[:4000]

    if not isinstance(data, dict):
        return _format_scalar(data)

    ov = data.get("readable_zh_override")
    if isinstance(ov, str) and ov.strip():
        return ov.strip()

    return _dict_to_auto_readable_zh(data)
