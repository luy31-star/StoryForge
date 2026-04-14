from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

CHAPTER_PLAN_SCHEMA_VERSION = 2

_DISPLAY_SUMMARY_STRING_KEYS = (
    "plot_summary",
    "stage_position",
    "pacing_justification",
)
_EXECUTION_CARD_STRING_KEYS = (
    "chapter_goal",
    "core_conflict",
    "key_turn",
    "ending_hook",
)
_EXECUTION_CARD_LIST_KEYS = (
    "must_happen",
    "required_callbacks",
    "allowed_progress",
    "must_not",
    "style_guardrails",
)
_END_STATE_TARGET_KEYS = ("characters", "relations", "items", "plots")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    return ""


def _clean_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _clean_reserved_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        text = value.strip()
        value = [{"item": text}] if text else []
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for item in value:
        if isinstance(item, dict):
            raw_item = item.get("item") or item.get("title") or item.get("name")
            raw_nb = item.get("not_before_chapter") or item.get("chapter_no")
            raw_reason = item.get("reason") or item.get("note")
        else:
            raw_item = item
            raw_nb = None
            raw_reason = None
        text = _clean_text(raw_item)
        if not text:
            continue
        not_before = _coerce_optional_int(raw_nb)
        key = (text.lower(), not_before)
        if key in seen:
            continue
        seen.add(key)
        row: dict[str, Any] = {"item": text}
        if not_before is not None:
            row["not_before_chapter"] = not_before
        reason = _clean_text(raw_reason)
        if reason:
            row["reason"] = reason
        out.append(row)
    return out


def _clean_scene_cards(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        text = value.strip()
        value = [{"content": text}] if text else []
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(value, 1):
        if isinstance(item, dict):
            label = _clean_text(item.get("label") or item.get("title")) or f"场景{idx}"
            goal = _clean_text(item.get("goal"))
            conflict = _clean_text(item.get("conflict"))
            content = _clean_text(item.get("content") or item.get("summary"))
            outcome = _clean_text(item.get("outcome") or item.get("result"))
            words = _coerce_optional_int(item.get("words") or item.get("target_words"))
        else:
            label = f"场景{idx}"
            goal = ""
            conflict = ""
            content = _clean_text(item)
            outcome = ""
            words = None
        if not any([goal, conflict, content, outcome]):
            continue
        row: dict[str, Any] = {"label": label}
        if goal:
            row["goal"] = goal
        if conflict:
            row["conflict"] = conflict
        if content:
            row["content"] = content
        if outcome:
            row["outcome"] = outcome
        if words is not None and words > 0:
            row["words"] = words
        out.append(row)
    return out


def _clean_end_state_targets(value: Any) -> dict[str, list[str]]:
    raw = value if isinstance(value, dict) else {}
    out: dict[str, list[str]] = {}
    for key in _END_STATE_TARGET_KEYS:
        out[key] = _clean_text_list(raw.get(key))
    return out


def _scene_cards_summary(scene_cards: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for idx, item in enumerate(scene_cards, 1):
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("label")) or f"场景{idx}"
        content = _clean_text(item.get("content"))
        goal = _clean_text(item.get("goal"))
        conflict = _clean_text(item.get("conflict"))
        outcome = _clean_text(item.get("outcome"))
        segments = [text for text in [content, goal, conflict, outcome] if text]
        if segments:
            parts.append(f"{label}：{'；'.join(segments[:3])}")
    return "\n".join(parts)


def _attach_legacy_aliases(data: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(data)
    display = out.get("display_summary", {})
    card = out.get("execution_card", {})
    scene_cards = card.get("scene_cards")
    out["goal"] = _clean_text(card.get("chapter_goal"))
    out["conflict"] = _clean_text(card.get("core_conflict"))
    out["turn"] = _clean_text(card.get("key_turn"))
    out["hook"] = _clean_text(card.get("ending_hook"))
    out["plot_summary"] = (
        deepcopy(scene_cards)
        if isinstance(scene_cards, list) and scene_cards
        else _clean_text(display.get("plot_summary"))
    )
    out["stage_position"] = _clean_text(display.get("stage_position"))
    out["pacing_justification"] = _clean_text(display.get("pacing_justification"))
    out["progress_allowed"] = deepcopy(card.get("allowed_progress") or [])
    out["must_not"] = deepcopy(card.get("must_not") or [])
    out["reserved_for_later"] = deepcopy(card.get("reserved_for_later") or [])
    return out


def normalize_beats_to_v2(beats: Any) -> dict[str, Any]:
    raw = beats if isinstance(beats, dict) else {}
    meta_in = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    display_in = (
        raw.get("display_summary") if isinstance(raw.get("display_summary"), dict) else {}
    )
    card_in = (
        raw.get("execution_card") if isinstance(raw.get("execution_card"), dict) else {}
    )

    raw_plot_summary = raw.get("plot_summary")
    raw_scene_cards = (
        raw_plot_summary
        if isinstance(raw_plot_summary, list)
        else card_in.get("scene_cards") or raw.get("scene_cards")
    )
    scene_cards = _clean_scene_cards(raw_scene_cards)

    display_plot_summary = _clean_text(
        display_in.get("plot_summary")
        if "plot_summary" in display_in
        else (raw_plot_summary if isinstance(raw_plot_summary, str) else raw.get("display_summary"))
    )
    if not display_plot_summary and scene_cards:
        display_plot_summary = _scene_cards_summary(scene_cards)

    execution_card = {
        "chapter_goal": _clean_text(
            card_in.get("chapter_goal")
            if "chapter_goal" in card_in
            else raw.get("goal")
        ),
        "core_conflict": _clean_text(
            card_in.get("core_conflict")
            if "core_conflict" in card_in
            else raw.get("conflict")
        ),
        "key_turn": _clean_text(
            card_in.get("key_turn")
            if "key_turn" in card_in
            else raw.get("turn")
        ),
        "must_happen": _clean_text_list(
            card_in.get("must_happen") if "must_happen" in card_in else raw.get("must_happen")
        ),
        "required_callbacks": _clean_text_list(
            card_in.get("required_callbacks")
            if "required_callbacks" in card_in
            else raw.get("required_callbacks")
        ),
        "scene_cards": scene_cards,
        "allowed_progress": _clean_text_list(
            card_in.get("allowed_progress")
            if "allowed_progress" in card_in
            else raw.get("progress_allowed")
        ),
        "must_not": _clean_text_list(
            card_in.get("must_not") if "must_not" in card_in else raw.get("must_not")
        ),
        "reserved_for_later": _clean_reserved_list(
            card_in.get("reserved_for_later")
            if "reserved_for_later" in card_in
            else raw.get("reserved_for_later")
        ),
        "end_state_targets": _clean_end_state_targets(
            card_in.get("end_state_targets")
            if "end_state_targets" in card_in
            else raw.get("end_state_targets")
        ),
        "ending_hook": _clean_text(
            card_in.get("ending_hook")
            if "ending_hook" in card_in
            else raw.get("hook")
        ),
        "style_guardrails": _clean_text_list(
            card_in.get("style_guardrails")
            if "style_guardrails" in card_in
            else raw.get("style_guardrails")
        ),
    }

    normalized = {
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "meta": {
            "edited_by_user": bool(meta_in.get("edited_by_user")),
            "last_editor_id": _clean_text(meta_in.get("last_editor_id")) or None,
            "last_edited_at": _clean_text(meta_in.get("last_edited_at")) or None,
        },
        "display_summary": {
            "plot_summary": display_plot_summary,
            "stage_position": _clean_text(
                display_in.get("stage_position")
                if "stage_position" in display_in
                else raw.get("stage_position")
            ),
            "pacing_justification": _clean_text(
                display_in.get("pacing_justification")
                if "pacing_justification" in display_in
                else raw.get("pacing_justification")
            ),
        },
        "execution_card": execution_card,
    }
    return _attach_legacy_aliases(normalized)


def _normalize_display_summary_field(key: str, value: Any) -> Any:
    if key == "plot_summary":
        if isinstance(value, list):
            return _scene_cards_summary(_clean_scene_cards(value))
        return _clean_text(value)
    if key in _DISPLAY_SUMMARY_STRING_KEYS:
        return _clean_text(value)
    return ""


def _normalize_execution_card_field(key: str, value: Any) -> Any:
    if key in _EXECUTION_CARD_STRING_KEYS:
        return _clean_text(value)
    if key in _EXECUTION_CARD_LIST_KEYS:
        return _clean_text_list(value)
    if key == "scene_cards":
        return _clean_scene_cards(value)
    if key == "reserved_for_later":
        return _clean_reserved_list(value)
    if key == "end_state_targets":
        return _clean_end_state_targets(value)
    return value


def merge_execution_card_patch(
    existing_v2: Any,
    patch: Any,
    *,
    editor_id: str | None = None,
) -> dict[str, Any]:
    merged = deepcopy(normalize_beats_to_v2(existing_v2))
    if not isinstance(patch, dict):
        patch = {}

    patch_display = patch.get("display_summary") if isinstance(patch.get("display_summary"), dict) else {}
    for key in _DISPLAY_SUMMARY_STRING_KEYS:
        if key in patch_display:
            merged["display_summary"][key] = _normalize_display_summary_field(
                key, patch_display.get(key)
            )

    patch_card = patch.get("execution_card") if isinstance(patch.get("execution_card"), dict) else {}
    for key in _EXECUTION_CARD_STRING_KEYS + _EXECUTION_CARD_LIST_KEYS:
        if key in patch_card:
            merged["execution_card"][key] = _normalize_execution_card_field(
                key, patch_card.get(key)
            )
    for key in ("scene_cards", "reserved_for_later", "end_state_targets"):
        if key in patch_card:
            merged["execution_card"][key] = _normalize_execution_card_field(
                key, patch_card.get(key)
            )

    for key in _DISPLAY_SUMMARY_STRING_KEYS:
        if key in patch:
            merged["display_summary"][key] = _normalize_display_summary_field(key, patch.get(key))

    legacy_exec_string_map = {
        "goal": "chapter_goal",
        "conflict": "core_conflict",
        "turn": "key_turn",
        "hook": "ending_hook",
    }
    for legacy_key, target_key in legacy_exec_string_map.items():
        if legacy_key in patch:
            merged["execution_card"][target_key] = _normalize_execution_card_field(
                target_key, patch.get(legacy_key)
            )

    legacy_exec_direct_map = {
        "must_happen": "must_happen",
        "required_callbacks": "required_callbacks",
        "scene_cards": "scene_cards",
        "progress_allowed": "allowed_progress",
        "allowed_progress": "allowed_progress",
        "must_not": "must_not",
        "reserved_for_later": "reserved_for_later",
        "end_state_targets": "end_state_targets",
        "style_guardrails": "style_guardrails",
        "ending_hook": "ending_hook",
    }
    for legacy_key, target_key in legacy_exec_direct_map.items():
        if legacy_key in patch:
            merged["execution_card"][target_key] = _normalize_execution_card_field(
                target_key, patch.get(legacy_key)
            )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    merged["schema_version"] = CHAPTER_PLAN_SCHEMA_VERSION
    merged["meta"]["edited_by_user"] = True
    merged["meta"]["last_editor_id"] = _clean_text(editor_id) or merged["meta"].get("last_editor_id")
    merged["meta"]["last_edited_at"] = now
    return merged


def chapter_plan_display_summary(beats: Any) -> dict[str, Any]:
    return normalize_beats_to_v2(beats).get("display_summary", {})


def chapter_plan_execution_card(beats: Any) -> dict[str, Any]:
    return normalize_beats_to_v2(beats).get("execution_card", {})


def chapter_plan_plot_summary(beats: Any) -> str:
    summary = chapter_plan_display_summary(beats)
    return _clean_text(summary.get("plot_summary"))


def chapter_plan_stage_position(beats: Any) -> str:
    summary = chapter_plan_display_summary(beats)
    return _clean_text(summary.get("stage_position"))


def chapter_plan_pacing_justification(beats: Any) -> str:
    summary = chapter_plan_display_summary(beats)
    return _clean_text(summary.get("pacing_justification"))


def chapter_plan_goal(beats: Any) -> str:
    card = chapter_plan_execution_card(beats)
    return _clean_text(card.get("chapter_goal"))


def chapter_plan_conflict(beats: Any) -> str:
    card = chapter_plan_execution_card(beats)
    return _clean_text(card.get("core_conflict"))


def chapter_plan_turn(beats: Any) -> str:
    card = chapter_plan_execution_card(beats)
    return _clean_text(card.get("key_turn"))


def chapter_plan_hook(beats: Any) -> str:
    card = chapter_plan_execution_card(beats)
    return _clean_text(card.get("ending_hook"))


def chapter_plan_guard_payload(
    beats: Any,
    *,
    chapter_no: int | None = None,
    plan_title: str = "",
) -> dict[str, Any]:
    normalized = normalize_beats_to_v2(beats)
    card = normalized.get("execution_card", {})
    summary = normalized.get("display_summary", {})
    payload: dict[str, Any] = {
        "plan_title": _clean_text(plan_title),
        "display_summary": {
            "plot_summary": _clean_text(summary.get("plot_summary")),
            "stage_position": _clean_text(summary.get("stage_position")),
            "pacing_justification": _clean_text(summary.get("pacing_justification")),
        },
        "hard_requirements": {
            "chapter_goal": _clean_text(card.get("chapter_goal")),
            "core_conflict": _clean_text(card.get("core_conflict")),
            "key_turn": _clean_text(card.get("key_turn")),
            "must_happen": _clean_text_list(card.get("must_happen")),
            "required_callbacks": _clean_text_list(card.get("required_callbacks")),
            "allowed_progress": _clean_text_list(card.get("allowed_progress")),
            "must_not": _clean_text_list(card.get("must_not")),
            "reserved_for_later": _clean_reserved_list(card.get("reserved_for_later")),
        },
        "repair_targets": {
            "ending_hook": _clean_text(card.get("ending_hook")),
            "end_state_targets": _clean_end_state_targets(card.get("end_state_targets")),
            "style_guardrails": _clean_text_list(card.get("style_guardrails")),
        },
    }
    if isinstance(chapter_no, int):
        payload["chapter_no"] = chapter_no
    return payload


def chapter_plan_has_guardrails(beats: Any) -> bool:
    payload = chapter_plan_guard_payload(beats)
    hard = payload.get("hard_requirements", {})
    repair = payload.get("repair_targets", {})
    if not isinstance(hard, dict) or not isinstance(repair, dict):
        return False
    return any(
        [
            _clean_text(hard.get("chapter_goal")),
            _clean_text(hard.get("core_conflict")),
            _clean_text(hard.get("key_turn")),
            bool(_clean_text_list(hard.get("must_happen"))),
            bool(_clean_text_list(hard.get("required_callbacks"))),
            bool(_clean_text_list(hard.get("allowed_progress"))),
            bool(_clean_text_list(hard.get("must_not"))),
            bool(_clean_reserved_list(hard.get("reserved_for_later"))),
            _clean_text(repair.get("ending_hook")),
        ]
    )
