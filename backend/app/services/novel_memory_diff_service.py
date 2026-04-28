from __future__ import annotations

import json
from typing import Any


def _json_load_dict(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _trim_text(value: str, limit: int = 120) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _chapter_summary(item: dict[str, Any]) -> dict[str, Any]:
    chapter_no = item.get("chapter_no")
    chapter_title = _stringify(item.get("chapter_title"))
    key_facts = item.get("key_facts")
    causal_results = item.get("causal_results")
    unresolved_hooks = item.get("unresolved_hooks")
    return {
        "chapter_no": chapter_no if isinstance(chapter_no, int) else 0,
        "chapter_title": chapter_title,
        "key_facts": [str(x).strip() for x in key_facts or [] if str(x).strip()][:4],
        "causal_results": [
            str(x).strip() for x in causal_results or [] if str(x).strip()
        ][:3],
        "unresolved_hooks": [
            str(x).strip() for x in unresolved_hooks or [] if str(x).strip()
        ][:3],
    }


def _entity_key(item: dict[str, Any], *field_names: str) -> str:
    for field in field_names:
        value = _stringify(item.get(field))
        if value:
            return value.lower()
    return _stringify(item).lower()


def _entity_summary(
    item: dict[str, Any], label_field: str, extra_fields: list[str] | None = None
) -> dict[str, Any]:
    extra_fields = extra_fields or []
    summary = {"label": _stringify(item.get(label_field))}
    for field in extra_fields:
        value = item.get(field)
        if value not in (None, "", [], {}):
            summary[field] = value
    return summary


def _relation_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": _stringify(item.get("from")),
        "to": _stringify(item.get("to")),
        "relation": _stringify(item.get("relation")),
        "is_active": bool(item.get("is_active", True)),
    }


def _plot_summary(item: dict[str, Any]) -> dict[str, Any]:
    body = _stringify(item.get("body") or item.get("summary") or item.get("title"))
    return {
        "body": _trim_text(body, 160),
        "plot_type": _stringify(item.get("plot_type")),
        "current_stage": _stringify(item.get("current_stage")),
        "priority": int(item.get("priority") or 0),
        "introduced_chapter": int(item.get("introduced_chapter") or 0),
        "last_touched_chapter": int(item.get("last_touched_chapter") or 0),
    }


def _extract_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _diff_records(
    prev_items: list[dict[str, Any]],
    curr_items: list[dict[str, Any]],
    *,
    key_fn,
    summary_fn,
    compare_fields: list[str],
) -> dict[str, Any]:
    prev_map = {key_fn(item): item for item in prev_items if key_fn(item)}
    curr_map = {key_fn(item): item for item in curr_items if key_fn(item)}
    prev_keys = set(prev_map)
    curr_keys = set(curr_map)

    added = [summary_fn(curr_map[key]) for key in sorted(curr_keys - prev_keys)]
    removed = [summary_fn(prev_map[key]) for key in sorted(prev_keys - curr_keys)]
    changed: list[dict[str, Any]] = []
    unchanged = 0
    for key in sorted(prev_keys & curr_keys):
        before = prev_map[key]
        after = curr_map[key]
        diff_fields = [
            field for field in compare_fields if _stringify(before.get(field)) != _stringify(after.get(field))
        ]
        if diff_fields:
            changed.append(
                {
                    "label": summary_fn(after).get("label") or key,
                    "fields": diff_fields,
                    "before": summary_fn(before),
                    "after": summary_fn(after),
                }
            )
        else:
            unchanged += 1
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": unchanged,
        },
    }


def build_memory_diff(previous_payload_json: str | None, current_payload_json: str | None) -> dict[str, Any]:
    prev_payload = _json_load_dict(previous_payload_json)
    curr_payload = _json_load_dict(current_payload_json)

    characters = _diff_records(
        _extract_list(prev_payload, "characters"),
        _extract_list(curr_payload, "characters"),
        key_fn=lambda item: _entity_key(item, "id", "name"),
        summary_fn=lambda item: _entity_summary(item, "name", ["role", "status", "is_active"]),
        compare_fields=["name", "role", "status", "traits", "detail", "aliases", "is_active"],
    )
    items = _diff_records(
        _extract_list(prev_payload, "inventory"),
        _extract_list(curr_payload, "inventory"),
        key_fn=lambda item: _entity_key(item, "id", "label"),
        summary_fn=lambda item: _entity_summary(item, "label", ["detail", "is_active"]),
        compare_fields=["label", "detail", "aliases", "is_active"],
    )
    skills = _diff_records(
        _extract_list(prev_payload, "skills"),
        _extract_list(curr_payload, "skills"),
        key_fn=lambda item: _entity_key(item, "id", "name"),
        summary_fn=lambda item: _entity_summary(item, "name", ["detail", "is_active"]),
        compare_fields=["name", "detail", "aliases", "is_active"],
    )
    pets = _diff_records(
        _extract_list(prev_payload, "pets"),
        _extract_list(curr_payload, "pets"),
        key_fn=lambda item: _entity_key(item, "id", "name"),
        summary_fn=lambda item: _entity_summary(item, "name", ["detail", "is_active"]),
        compare_fields=["name", "detail", "aliases", "is_active"],
    )
    relations = _diff_records(
        _extract_list(prev_payload, "relations"),
        _extract_list(curr_payload, "relations"),
        key_fn=lambda item: _entity_key(item, "id", "from", "to", "relation"),
        summary_fn=_relation_summary,
        compare_fields=["from", "to", "relation", "is_active"],
    )
    open_plots = _diff_records(
        _extract_list(prev_payload, "open_plots"),
        _extract_list(curr_payload, "open_plots"),
        key_fn=lambda item: _entity_key(item, "id", "body", "summary", "title"),
        summary_fn=_plot_summary,
        compare_fields=[
            "body",
            "plot_type",
            "priority",
            "estimated_duration",
            "current_stage",
            "resolve_when",
            "introduced_chapter",
            "last_touched_chapter",
            "is_stale",
        ],
    )

    chapter_prev = {int(item.get("chapter_no") or 0): item for item in _extract_list(prev_payload, "chapters")}
    chapter_curr = {int(item.get("chapter_no") or 0): item for item in _extract_list(curr_payload, "chapters")}
    added_chapters = [
        _chapter_summary(chapter_curr[key]) for key in sorted(set(chapter_curr) - set(chapter_prev)) if key > 0
    ]
    removed_chapters = [
        _chapter_summary(chapter_prev[key]) for key in sorted(set(chapter_prev) - set(chapter_curr)) if key > 0
    ]
    changed_chapters: list[dict[str, Any]] = []
    for key in sorted(set(chapter_prev) & set(chapter_curr)):
        before = chapter_prev[key]
        after = chapter_curr[key]
        diff_fields = [
            field
            for field in [
                "chapter_title",
                "key_facts",
                "causal_results",
                "open_plots_added",
                "open_plots_resolved",
                "emotional_state",
                "unresolved_hooks",
            ]
            if _stringify(before.get(field)) != _stringify(after.get(field))
        ]
        if diff_fields:
            changed_chapters.append(
                {
                    "chapter_no": key,
                    "fields": diff_fields,
                    "before": _chapter_summary(before),
                    "after": _chapter_summary(after),
                }
            )

    changed_types = [
        name
        for name, section in [
            ("characters", characters),
            ("inventory", items),
            ("skills", skills),
            ("pets", pets),
            ("relations", relations),
            ("open_plots", open_plots),
        ]
        if sum(section["counts"].values()) - int(section["counts"].get("unchanged", 0)) > 0
    ]
    if added_chapters or removed_chapters or changed_chapters:
        changed_types.append("chapters")

    chapter_nos = sorted(
        {
            item.get("chapter_no")
            for item in added_chapters
            if isinstance(item.get("chapter_no"), int) and item.get("chapter_no", 0) > 0
        }
        | {
            item.get("chapter_no")
            for item in changed_chapters
            if isinstance(item.get("chapter_no"), int) and item.get("chapter_no", 0) > 0
        }
    )

    return {
        "summary": {
            "changed_types": changed_types,
            "chapter_nos": chapter_nos,
            "latest_chapter_no": max(chapter_nos) if chapter_nos else None,
            "change_count": (
                len(changed_types)
                + len(added_chapters)
                + len(removed_chapters)
                + len(changed_chapters)
            ),
        },
        "characters": characters,
        "inventory": items,
        "skills": skills,
        "pets": pets,
        "relations": relations,
        "open_plots": open_plots,
        "chapters": {
            "added": added_chapters,
            "removed": removed_chapters,
            "changed": changed_chapters,
            "counts": {
                "added": len(added_chapters),
                "removed": len(removed_chapters),
                "changed": len(changed_chapters),
            },
        },
    }


def build_memory_source_summary(diff_summary: dict[str, Any]) -> dict[str, Any]:
    summary = diff_summary.get("summary") if isinstance(diff_summary, dict) else {}
    chapter_nos = summary.get("chapter_nos") if isinstance(summary, dict) else []
    chapter_nos = [int(no) for no in chapter_nos or [] if isinstance(no, int) and no > 0]
    return {
        "chapter_nos": chapter_nos,
        "latest_chapter_no": max(chapter_nos) if chapter_nos else None,
        "changed_types": list(summary.get("changed_types") or []) if isinstance(summary, dict) else [],
    }
