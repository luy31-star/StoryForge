from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from json_repair import loads as json_repair_loads
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.novel import Novel, NovelMemory
from app.services.memory_schema import (
    dedupe_clean_strs,
    extract_aliases,
    is_irreversible_fact,
    normalize_plot_type,
)
from app.services.novel_llm_chapter_service import NovelLLMChapterService
from app.services.novel_llm_utils import *
from app.services.novel_llm_utils import (
    _canonical_entries_from_payload,
    _dedupe_str_list,
    _relation_identity,
    _revise_chapter_messages,
    _safe_json_dict,
    _short_id,
    _status_implies_inactive,
)

logger = logging.getLogger(__name__)

class NovelLLMMemoryService(NovelLLMChapterService):
    """记忆刷新、归档与一致性校验能力。"""

    def _parse_refresh_memory_response(self, raw: str) -> dict[str, Any]:
        candidates: list[str] = []
        text = (raw or "").strip()
        if text:
            candidates.append(text)
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            extracted = m.group(0).strip()
            if extracted and extracted not in candidates:
                candidates.append(extracted)

        for blob in candidates:
            try:
                parsed = json.loads(blob)
                if isinstance(parsed, dict):
                    return self._normalize_refresh_memory_response(parsed)
            except json.JSONDecodeError:
                pass

        for blob in candidates:
            try:
                parsed = json_repair_loads(blob)
                if isinstance(parsed, dict):
                    return self._normalize_refresh_memory_response(parsed)
            except Exception:
                pass
        return {}

    @staticmethod
    def _empty_refresh_memory_delta() -> dict[str, Any]:
        return {
            "facts_added": [],
            "facts_updated": [],
            "open_plots_added": [],
            "open_plots_resolved": [],
            "canonical_entries": [],
            "characters_added": [],
            "characters_updated": [],
            "characters_inactivated": [],
            "relations_added": [],
            "relations_updated": [],
            "relations_inactivated": [],
            "relations_changed": [],
            "inventory_changed": {"added": [], "removed": []},
            "skills_changed": {"added": [], "updated": [], "removed": []},
            "pets_changed": {"added": [], "updated": [], "removed": []},
            "conflicts_detected": [],
            "forbidden_constraints_added": [],
            "ids_to_remove": [],
            "entity_influence_updates": [],
        }

    @classmethod
    def _normalize_refresh_memory_response(cls, parsed: dict[str, Any]) -> dict[str, Any]:
        normalized = cls._empty_refresh_memory_delta()
        for key, value in parsed.items():
            normalized[key] = value

        # 1. 章节项去重（按 chapter_no）
        raw_entries = normalized.get("canonical_entries")
        if isinstance(raw_entries, list):
            unique_entries_map: dict[int, dict[str, Any]] = {}
            for item in raw_entries:
                norm_item = cls._normalize_delta_entry(item)
                if norm_item:
                    cno = norm_item["chapter_no"]
                    if cno in unique_entries_map:
                        # 如果重复，合并它们
                        unique_entries_map[cno] = cls._merge_timeline_entry(unique_entries_map[cno], norm_item)
                    else:
                        unique_entries_map[cno] = norm_item
            normalized["canonical_entries"] = [unique_entries_map[k] for k in sorted(unique_entries_map.keys())]

        def _dedupe_named_entities(raw: Any) -> list[dict[str, Any]]:
            if not isinstance(raw, list):
                return []
            unique_map: dict[str, dict[str, Any]] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if name:
                    unique_map[name] = item
            return list(unique_map.values())

        def _dedupe_relations(raw: Any) -> list[dict[str, Any]]:
            if not isinstance(raw, list):
                return []
            unique_map: dict[tuple[str, str], dict[str, Any]] = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                if src and dst:
                    unique_map[(src, dst)] = item
            return list(unique_map.values())

        normalized["characters_added"] = _dedupe_named_entities(normalized.get("characters_added"))
        normalized["characters_updated"] = _dedupe_named_entities(normalized.get("characters_updated"))
        normalized["characters_inactivated"] = _dedupe_named_entities(
            normalized.get("characters_inactivated")
        )
        normalized["relations_added"] = _dedupe_relations(normalized.get("relations_added"))
        normalized["relations_updated"] = _dedupe_relations(
            [
                *_dedupe_relations(normalized.get("relations_updated")),
                *_dedupe_relations(normalized.get("relations_changed")),
            ]
        )
        normalized["relations_inactivated"] = _dedupe_relations(
            normalized.get("relations_inactivated")
        )

        # 3. 其他常规字段清理
        inventory_changed = normalized.get("inventory_changed")
        if not isinstance(inventory_changed, dict):
            inventory_changed = {}
        normalized["inventory_changed"] = {
            "added": inventory_changed.get("added") if isinstance(inventory_changed.get("added"), list) else [],
            "removed": inventory_changed.get("removed") if isinstance(inventory_changed.get("removed"), list) else [],
        }

        skills_changed = normalized.get("skills_changed")
        if not isinstance(skills_changed, dict):
            skills_changed = {}
        normalized["skills_changed"] = {
            "added": skills_changed.get("added") if isinstance(skills_changed.get("added"), list) else [],
            "updated": skills_changed.get("updated") if isinstance(skills_changed.get("updated"), list) else [],
            "removed": skills_changed.get("removed") if isinstance(skills_changed.get("removed"), list) else [],
        }

        pets_changed = normalized.get("pets_changed")
        if not isinstance(pets_changed, dict):
            pets_changed = {}
        normalized["pets_changed"] = {
            "added": pets_changed.get("added") if isinstance(pets_changed.get("added"), list) else [],
            "updated": pets_changed.get("updated") if isinstance(pets_changed.get("updated"), list) else [],
            "removed": pets_changed.get("removed") if isinstance(pets_changed.get("removed"), list) else [],
        }
        return normalized

    @staticmethod
    def _extract_chapter_blobs(chapters_summary: str) -> list[dict[str, Any]]:
        text = (chapters_summary or "").strip()
        if not text:
            return []

        pattern = re.compile(r"(?m)^第\s*(\d+)\s*章(?:《([^》\n]*)》|[ \t]+([^\n]+))?\n")
        matches = list(pattern.finditer(text))
        if not matches:
            return []

        out: list[dict[str, Any]] = []
        for idx, match in enumerate(matches):
            chapter_no = int(match.group(1))
            title = str(match.group(2) or match.group(3) or "").strip()
            body_start = match.end()
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            chapter_text = text[body_start:body_end].strip()
            out.append(
                {
                    "chapter_no": chapter_no,
                    "chapter_title": title,
                    "chapter_text": chapter_text,
                }
            )
        return out

    @staticmethod
    def _fallback_list_from_text(text: str, *, limit: int, item_max_chars: int = 120) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if not cleaned:
            return []
        chunks = [
            seg.strip(" -\t")
            for seg in re.split(r"(?:\n{2,}|[。！？!?]\s*)", cleaned)
            if seg and seg.strip(" -\t")
        ]
        out: list[str] = []
        for seg in chunks:
            short = seg[:item_max_chars].strip()
            if short and short not in out:
                out.append(short)
            if len(out) >= limit:
                break
        if not out:
            return [cleaned[:item_max_chars]]
        return out

    @classmethod
    def _build_fallback_canonical_entry(
        cls,
        *,
        chapter_no: int,
        chapter_title: str,
        chapter_text: str,
    ) -> dict[str, Any]:
        key_facts = cls._fallback_list_from_text(chapter_text, limit=3, item_max_chars=120)
        tail_candidates = cls._fallback_list_from_text(chapter_text[-500:], limit=2, item_max_chars=120)
        causal_results = tail_candidates[:1] if tail_candidates else []
        unresolved_hooks = [
            item
            for item in tail_candidates[1:]
            if any(token in item for token in ("?", "？", "将", "未", "待", "是否"))
        ][:2]
        return {
            "chapter_no": chapter_no,
            "chapter_title": (chapter_title or f"第{chapter_no}章").strip(),
            "key_facts": key_facts,
            "causal_results": causal_results,
            "open_plots_added": [],
            "open_plots_resolved": [],
            "emotional_state": "",
            "unresolved_hooks": unresolved_hooks,
        }

    @classmethod
    def _extract_chapter_no(cls, item: Any) -> int | None:
        """从条目提取章节号，处理各种格式（字符串、整数等）"""
        if not isinstance(item, dict):
            return None
        cn = item.get("chapter_no")
        if isinstance(cn, int):
            return cn if cn > 0 else None
        if isinstance(cn, str):
            cn = cn.strip()
            if cn.isdigit():
                return int(cn)
        return None

    @classmethod
    def _supplement_missing_canonical_entries(
        cls,
        delta: dict[str, Any],
        chapters_summary: str,
    ) -> tuple[dict[str, Any], list[int]]:
        blobs = cls._extract_chapter_blobs(chapters_summary)
        if not blobs:
            return delta, []

        existing_entries = delta.get("canonical_entries")
        if not isinstance(existing_entries, list):
            existing_entries = []

        # 1. 先清理和去重已有条目（按 chapter_no）
        existing_nos: set[int] = set()
        unique_entries: list[dict[str, Any]] = []
        for item in existing_entries:
            cno = cls._extract_chapter_no(item)
            if cno is None:
                # 格式不正确的条目保留，但不参与去重判断
                unique_entries.append(item)
                continue
            if cno in existing_nos:
                # 重复条目：找到已存在的并合并
                for idx, existing in enumerate(unique_entries):
                    if cls._extract_chapter_no(existing) == cno:
                        norm_existing = cls._normalize_delta_entry(existing)
                        norm_item = cls._normalize_delta_entry(item)
                        if norm_existing and norm_item:
                            unique_entries[idx] = cls._merge_timeline_entry(norm_existing, norm_item)
                        break
            else:
                existing_nos.add(cno)
                unique_entries.append(item)

        # 2. 为缺失的章节创建兜底条目
        missing_entries: list[dict[str, Any]] = []
        missing_nos: list[int] = []
        for blob in blobs:
            chapter_no = int(blob["chapter_no"])
            if chapter_no in existing_nos:
                continue
            existing_nos.add(chapter_no)
            missing_nos.append(chapter_no)
            missing_entries.append(
                cls._build_fallback_canonical_entry(
                    chapter_no=chapter_no,
                    chapter_title=str(blob.get("chapter_title") or ""),
                    chapter_text=str(blob.get("chapter_text") or ""),
                )
            )

        if not missing_entries:
            return delta, []

        patched = dict(delta)
        patched["canonical_entries"] = [*unique_entries, *missing_entries]
        return patched, missing_nos

    @classmethod
    def _refresh_memory_repair_messages(cls, raw: str) -> list[dict[str, str]]:
        example = json.dumps(cls._empty_refresh_memory_delta(), ensure_ascii=False)
        return [
            {
                "role": "system",
                "content": (
                    "你是记忆增量 JSON 修复器。"
                    "你只能输出一个可被 json.loads() 直接解析的 JSON 对象。"
                    "不要输出解释、Markdown、代码块或多余文字。"
                    "如果原文缺少字段，必须补齐为空数组或空对象。"
                    "输出结构示例："
                    f"{example}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把下面这段模型原始输出修复为合法 JSON 对象，只保留记忆增量本体：\n"
                    f"{raw or ''}"
                ),
            },
        ]

    async def _repair_refresh_memory_response(
        self,
        *,
        router: LLMRouter,
        raw: str,
        db: Any = None,
    ) -> dict[str, Any]:
        try:
            repaired_raw = await router.chat_text(
                messages=self._refresh_memory_repair_messages(raw),
                temperature=0.0,
                timeout=min(120.0, settings.novel_memory_refresh_batch_timeout),
                max_tokens=min(settings.novel_memory_delta_max_tokens, 4096),
                response_format={"type": "json_object"},
                **self._bill_kw(db, self._billing_user_id),
            )
        except Exception:
            logger.exception("memory delta json repair failed(async)")
            return {}
        return self._parse_refresh_memory_response(repaired_raw)

    def _repair_refresh_memory_response_sync(
        self,
        *,
        router: LLMRouter,
        raw: str,
        db: Any = None,
    ) -> dict[str, Any]:
        try:
            repaired_raw = router.chat_text_sync(
                messages=self._refresh_memory_repair_messages(raw),
                temperature=0.0,
                timeout=min(120.0, settings.novel_memory_refresh_batch_timeout),
                max_tokens=min(settings.novel_memory_delta_max_tokens, 4096),
                response_format={"type": "json_object"},
                **self._bill_kw(db, self._billing_user_id),
            )
        except Exception:
            logger.exception("memory delta json repair failed(sync)")
            return {}
        return self._parse_refresh_memory_response(repaired_raw)

    def _build_memory_delta_plan_targets(
        self,
        db: Session | None,
        novel_id: str,
        chapters_summary: str,
    ) -> str:
        if not db:
            return ""
        chapter_nos = [
            int(blob["chapter_no"])
            for blob in self._extract_chapter_blobs(chapters_summary)
            if isinstance(blob, dict) and blob.get("chapter_no")
        ]
        if not chapter_nos:
            return ""
        rows = (
            db.query(NovelChapterPlan)
            .filter(
                NovelChapterPlan.novel_id == novel_id,
                NovelChapterPlan.chapter_no.in_(chapter_nos),
            )
            .order_by(NovelChapterPlan.chapter_no.asc())
            .all()
        )
        if not rows:
            return ""

        sections: list[str] = ["【本批章节对应章计划的结束状态目标】"]
        for row in rows:
            try:
                beats = json.loads(row.beats_json or "{}")
            except json.JSONDecodeError:
                beats = {}
            card = chapter_plan_execution_card(beats)
            targets = card.get("end_state_targets") if isinstance(card, dict) else {}
            if not isinstance(targets, dict):
                continue
            chunks: list[str] = []
            for key, label in (
                ("characters", "角色状态"),
                ("relations", "关系状态"),
                ("items", "物品状态"),
                ("plots", "线索状态"),
            ):
                values = targets.get(key)
                if not isinstance(values, list):
                    continue
                bullets = [str(x).strip() for x in values if str(x).strip()]
                if bullets:
                    chunks.append(f"{label}：\n" + "\n".join(f"  · {x}" for x in bullets[:8]))
            if chunks:
                sections.append(
                    f"第{row.chapter_no}章《{row.chapter_title or f'第{row.chapter_no}章'}》\n"
                    + "\n".join(chunks)
                )
        return "\n\n".join(sections) if len(sections) > 1 else ""

    def _memory_delta_messages(
        self, novel: Novel, chapters_summary: str, prev_memory: str, db: Session | None = None
    ) -> list[dict[str, str]]:
        fj = truncate_framework_json(effective_framework_json_for_prompt(db, novel), 6000)
        compact_prev = build_hot_memory_for_prompt(
            prev_memory,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
        )
        prev_open_plots = format_open_plots_block(prev_memory)
        plan_targets_block = self._build_memory_delta_plan_targets(db, novel.id, chapters_summary)
        sys = (
            "你是小说记忆增量抽取器。"
            "你不能重写整份记忆，只能根据新章节内容输出“本批新增/变更了什么”。"
            "必须输出严格 JSON 对象，不要 Markdown，不要解释。"
            "若某字段没有变化，必须输出空数组或空对象。"
            "若本批输入里包含 1 章或多章内容，则 canonical_entries 必须为本批每一章各输出一条条目，不允许漏章。"
            "输出字段固定为："
            "facts_added[], facts_updated[], open_plots_added[], open_plots_resolved[],"
            "canonical_entries[], characters_added[], characters_updated[], characters_inactivated[],"
            "relations_added[], relations_updated[], relations_inactivated[],"
            "inventory_changed{added[],removed[]}, skills_changed{added[],updated[],removed[]},"
            "pets_changed{added[],updated[],removed[]}, conflicts_detected[],"
            "forbidden_constraints_added[], ids_to_remove[], entity_influence_updates[]。"
            "ids_to_remove[]：非常重要！当你判断某条【待收束线】已收束、某条【硬约束】已失效、或某项技能/道具已遗失/毁坏时，"
            "直接在 ids_to_remove 中填入该条目在下文提供的 4 位短 ID。不要通过文本匹配删除。\n"
            "【同类条目替换与升级规则（通用）】\n"
            "1. 状态/等级更新：若某项属性、技能或物品存在明显的等级递进或阶段更替（如：等级1 -> 等级2，初级 -> 中级），必须在 added 中加入新条目，并务必在 ids_to_remove 中放入旧条目的 ID。严禁同一实体的多个版本/阶段同时处于活跃状态。\n"
            "1.1 若升级后名称发生变化（旧名不再出现），必须把旧条目放入 skills_changed.removed / pets_changed.removed（优先填 ID，没有 ID 才填旧名）。\n"
            "2. 唯一性冲突：对于在设定上具有唯一性或排他性的条目，新条目出现时必须移除旧条目。"
            "canonical_entries 每项结构："
            "{chapter_no:number, chapter_title:string, key_facts:string[], causal_results:string[],"
            " open_plots_added:(string|{body,plot_type,priority,estimated_duration,current_stage,resolve_when})[],"
            " open_plots_resolved:string[],"
            " emotional_state:string, unresolved_hooks:string[]}。"
            "open_plots_added 可为字符串或对象：对象时 plot_type 取 Core|Arc|Transient，"
            "priority 越大越重要，estimated_duration 为预计持续章节数（估算即可），"
            "current_stage 为当前推进到哪一步，resolve_when 为真正收束所需条件。"
            "【人物抽取硬约束】"
            "只要本批章节中出现了明确人名，这个人物就必须被记录，绝对不允许遗漏。"
            "不管是主角、配角、反派、路人、只出场一次的人物，还是回忆/传闻/书信中明确点名的人物，只要出现姓名都要入库。"
            "首次出现的人名必须写入 characters_added；旧人物有状态、立场、伤势、阵营、目标、身份认知变化时必须写入 characters_updated；"
            "人物死亡、长期退场、离队、封印等明确下线写入 characters_inactivated。"
            "人物条目必须使用唯一主名，避免用代称、称谓或模糊指代；若正文里只写称谓，但上下文能确定实名，也必须回填实名。"
            "characters_added / characters_updated / characters_inactivated / entity_influence_updates 可含 influence_score(0-100)、is_active。"
            "【人物关系硬约束】"
            "只要本批章节里出现两个人物之间的亲属、同盟、敌对、上下级、爱慕、利用、师徒、交易、控制、怀疑、冲突等可识别关系，relations 必须有记录，绝对不能缺失。"
            "relations_added 用于新建立的重要关系；relations_updated 用于已有关系变化；relations_inactivated 用于关系失效、断裂或不再成立。"
            "若 characters 中出现了本批新人物或发生状态变化的人物，你必须同步检查并补齐其与其他人物的关系变化；不要只记人物不记关系。"
            "entity_influence_updates 每项：{entity_type, name, influence_score?, is_active?}，"
            "entity_type 为 character|skill|item|pet|plot 之一。"
            "forbidden_constraints_added：新增全局禁止事项（硬设定防火墙），须谨慎，只写正文绝不能违反的规则。"
            "facts_added / facts_updated 不要再重复塞进 notes。"
            "严禁输出全量 world_rules/main_plot/arcs。"
            "open_plots_resolved：每条字符串必须与下文【全书待收束线】或 canonical_entries 中已有 open_plots 的 body 文本完全一致（逐字一致）；"
            "只允许填写真正影响剧情推进、人物关系、核心矛盾、卷目标或后续章节承接的关键收束线；"
            "日常动作、一次性细节、气氛描写、小误会、无后续影响的临时事件，即使结束了也不要写入 open_plots_resolved。"
            "推荐优先使用 ids_to_remove 进行删除。"
            f"合法输出示例：{json.dumps(self._empty_refresh_memory_delta(), ensure_ascii=False)}"
        )
        user = (
            f"【框架 JSON（硬约束）】\n{fj}\n\n"
            f"【旧记忆热层快照（含 ID）】\n{compact_prev}\n\n"
            f"{prev_open_plots}\n\n"
            f"{plan_targets_block}\n\n" if plan_targets_block else
            f"【框架 JSON（硬约束）】\n{fj}\n\n"
            f"【旧记忆热层快照（含 ID）】\n{compact_prev}\n\n"
            f"{prev_open_plots}\n\n"
        )
        user += (
            f"【新章节文本/摘要】\n{chapters_summary}\n\n"
            "任务：提取本批章节相对旧记忆的增量事实。\n"
            "特别提醒：若实体状态/等级发生变更（升级、替换），必须找到旧版本的 ID 放入 ids_to_remove！"
            "如果某条线索在本批明确收束，请将该线索的 ID 放入 ids_to_remove；"
            "如果某条硬约束、技能或物品不再适用，也请放入 ids_to_remove。"
            "如果只是推进但未真正解决，不要移除。"
            "如果章计划里明确给了本章结束状态目标，优先按该目标判断人物、关系和物品的新增/更新/下线。"
            "再次强调：所有出现明确姓名的人物都要记录，且相关人物关系必须补齐，不允许漏人、不允许漏关系。"
            "再次强调：只总结关键收束线，不要总结对主剧情没有实质影响的小收尾。"
        )
        return [
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _is_key_resolved_plot(plot: Any, *, current_chapter_no: int = 0) -> bool:
        if plot is None:
            return False
        if isinstance(plot, dict):
            plot_type = normalize_plot_type(plot.get("plot_type"))
            priority = clamp_int(plot.get("priority"), minimum=0, maximum=100, default=0)
            estimated_duration = clamp_int(
                plot.get("estimated_duration"), minimum=0, maximum=999, default=0
            )
            introduced = clamp_int(
                plot.get("introduced_chapter"), minimum=0, maximum=20000, default=0
            )
            touched = clamp_int(
                plot.get("last_touched_chapter"), minimum=0, maximum=20000, default=0
            )
            current_stage = str(plot.get("current_stage") or "").strip()
            resolve_when = str(plot.get("resolve_when") or "").strip()
        else:
            plot_type = normalize_plot_type(getattr(plot, "plot_type", "Transient"))
            priority = clamp_int(
                getattr(plot, "priority", 0), minimum=0, maximum=100, default=0
            )
            estimated_duration = clamp_int(
                getattr(plot, "estimated_duration", 0),
                minimum=0,
                maximum=999,
                default=0,
            )
            introduced = clamp_int(
                getattr(plot, "introduced_chapter", 0),
                minimum=0,
                maximum=20000,
                default=0,
            )
            touched = clamp_int(
                getattr(plot, "last_touched_chapter", 0),
                minimum=0,
                maximum=20000,
                default=0,
            )
            current_stage = str(getattr(plot, "current_stage", "") or "").strip()
            resolve_when = str(getattr(plot, "resolve_when", "") or "").strip()
        observed_end = max(current_chapter_no, touched, introduced)
        chapter_span = max(0, observed_end - introduced)
        return any(
            (
                plot_type in {"Core", "Arc"},
                priority >= 20,
                estimated_duration >= 4,
                chapter_span >= 3,
                bool(current_stage and resolve_when and plot_type != "Transient"),
            )
        )

    @classmethod
    def _filter_key_resolved_plot_bodies(
        cls,
        bodies: list[str],
        *,
        plot_lookup: dict[str, Any],
        current_chapter_no: int = 0,
    ) -> list[str]:
        kept: list[str] = []
        seen: set[str] = set()
        for body in bodies:
            normalized = str(body or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            plot = plot_lookup.get(normalized)
            if plot is None or cls._is_key_resolved_plot(
                plot, current_chapter_no=current_chapter_no
            ):
                kept.append(normalized)
        return kept

    @staticmethod
    def _normalize_delta_entry(entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        chapter_no = entry.get("chapter_no")
        if isinstance(chapter_no, str) and chapter_no.strip().isdigit():
            chapter_no = int(chapter_no.strip())
        if not isinstance(chapter_no, int) or chapter_no <= 0:
            return None
        # open_plots_added：保留字符串或对象，供合并时解析
        raw_added = entry.get("open_plots_added", [])
        open_plots_added_norm: list[Any] = []
        if isinstance(raw_added, list):
            for x in raw_added:
                if isinstance(x, dict):
                    body = str(x.get("body") or "").strip()
                    if body:
                        open_plots_added_norm.append(
                            {
                                "body": body,
                                "plot_type": normalize_plot_type(x.get("plot_type")),
                                "priority": clamp_int(x.get("priority"), minimum=0, maximum=100, default=0),
                                "estimated_duration": max(
                                    0, clamp_int(x.get("estimated_duration"), minimum=0, maximum=999, default=0)
                                ),
                                "current_stage": str(x.get("current_stage") or "").strip()[:500],
                                "resolve_when": str(x.get("resolve_when") or "").strip()[:500],
                            }
                        )
                else:
                    s = str(x or "").strip()
                    if s:
                        open_plots_added_norm.append(s)
        uh = entry.get("unresolved_hooks")
        if not isinstance(uh, list):
            uh = []
        normalized = {
            "chapter_no": chapter_no,
            "chapter_title": str(entry.get("chapter_title") or "").strip(),
            "key_facts": _dedupe_str_list(entry.get("key_facts", [])),
            "causal_results": _dedupe_str_list(entry.get("causal_results", [])),
            "open_plots_added": open_plots_added_norm,
            "open_plots_resolved": _dedupe_str_list(
                NovelLLMService._open_plot_bodies_from_mixed(entry.get("open_plots_resolved"))
            ),
            "emotional_state": str(entry.get("emotional_state") or "").strip(),
            "unresolved_hooks": _dedupe_str_list(uh),
        }
        return normalized

    @staticmethod
    def _merge_timeline_open_plots_added(base: Any, incoming: Any) -> list[Any]:
        out: list[Any] = []
        seen: set[str] = set()

        def _body(x: Any) -> str:
            if isinstance(x, dict):
                return str(x.get("body") or "").strip()
            return str(x or "").strip()

        for seq in (base if isinstance(base, list) else [], incoming if isinstance(incoming, list) else []):
            for x in seq:
                b = _body(x)
                if not b or b in seen:
                    continue
                seen.add(b)
                out.append(x)
        return out

    @staticmethod
    def _open_plot_bodies_from_mixed(items: Any) -> list[str]:
        out: list[str] = []
        if not isinstance(items, list):
            return out
        for x in items:
            if isinstance(x, dict):
                b = str(x.get("body") or "").strip()
                if b:
                    out.append(b)
            else:
                s = str(x or "").strip()
                if s:
                    out.append(s)
        return out

    @classmethod
    def _merge_timeline_entry(cls, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        merged["chapter_no"] = incoming["chapter_no"]
        merged["chapter_title"] = str(
            incoming.get("chapter_title") or base.get("chapter_title") or ""
        ).strip()
        merged["key_facts"] = _dedupe_str_list(
            [*(base.get("key_facts") or []), *(incoming.get("key_facts") or [])]
        )
        merged["causal_results"] = _dedupe_str_list(
            [*(base.get("causal_results") or []), *(incoming.get("causal_results") or [])]
        )
        merged["open_plots_added"] = cls._merge_timeline_open_plots_added(
            base.get("open_plots_added"), incoming.get("open_plots_added")
        )
        merged["open_plots_resolved"] = _dedupe_str_list(
            [
                *NovelLLMService._open_plot_bodies_from_mixed(base.get("open_plots_resolved")),
                *NovelLLMService._open_plot_bodies_from_mixed(incoming.get("open_plots_resolved")),
            ]
        )
        emo_in = str(incoming.get("emotional_state") or "").strip()
        merged["emotional_state"] = emo_in or str(base.get("emotional_state") or "").strip()
        merged["unresolved_hooks"] = _dedupe_str_list(
            [*(base.get("unresolved_hooks") or []), *(incoming.get("unresolved_hooks") or [])]
        )
        return merged

    @staticmethod
    def _inventory_entry_label_and_detail(entry: Any) -> tuple[str, str]:
        """
        inventory_changed 里 LLM 可能输出字符串或对象（含 item/name/description）。
        label 列必须为短字符串；完整对象写入 detail_json。
        """
        if isinstance(entry, dict):
            lab = str(
                entry.get("item_name")
                or entry.get("name")
                or entry.get("item")
                or entry.get("label")
                or entry.get("title")
                or ""
            ).strip()
            if not lab:
                lab = json.dumps(entry, ensure_ascii=False)[:512]
            else:
                lab = lab[:512]
            return lab, json.dumps(entry, ensure_ascii=False)
        s = str(entry or "").strip()[:512]
        return s, "{}"

    @staticmethod
    def _upsert_normalized_memory_from_delta(
        db: Session,
        novel_id: str,
        delta: dict[str, Any],
        memory_version: int,
        replace_timeline: bool = False,
        chapters_summary: str | None = None,
    ) -> dict[str, int]:
        """
        根据 LLM 返回的增量 Delta，直接更新规范化数据库表。
        返回操作统计。
        """
        stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
            "skills_updated": 0,
            "items_updated": 0,
        }
        
        # 0. 解析正文摘要中的章节号
        target_chapter_nos = []
        if chapters_summary:
            target_chapter_nos = [int(n) for n in re.findall(r"第(\d+)章", chapters_summary)]

        # 0.1 如果是刷新模式，先清空这些章节的旧事实，确保“先删除再更新”
        if replace_timeline and target_chapter_nos:
            # 1. 清空章节级事实
            db.query(NovelMemoryNormChapter).filter(
                NovelMemoryNormChapter.novel_id == novel_id,
                NovelMemoryNormChapter.chapter_no.in_(target_chapter_nos)
            ).update({
                "key_facts_json": "[]",
                "causal_results_json": "[]",
                "open_plots_added_json": "[]",
                "open_plots_resolved_json": "[]",
                "emotional_state": "",
                "unresolved_hooks_json": "[]"
            }, synchronize_session='fetch')
            
            # 2. 【核心加固】同步删除在这几章“出生”的剧情线实体，防止刷新后产生重复或残留的“孤儿”线索
            db.query(NovelMemoryNormPlot).filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.introduced_chapter.in_(target_chapter_nos)
            ).delete(synchronize_session='fetch')

        latest_delta_chapter_no = 0
        
        # 0. 处理全局删除：ids_to_remove
        ids_to_remove = set(delta.get("ids_to_remove") or [])
        if ids_to_remove:
            # 尝试在各分表中根据内容哈希删除或失效匹配项。
            # 人物与关系遵循软下线；物品保持硬删除。
            for table, attr in [
                (NovelMemoryNormPlot, "body"),
                (NovelMemoryNormSkill, "name"),
                (NovelMemoryNormItem, "label"),
                (NovelMemoryNormPet, "name"),
            ]:
                rows = db.query(table).filter(table.novel_id == novel_id).all()
                to_del_ids = []
                for row in rows:
                    val = getattr(row, attr)
                    if val and _short_id(val) in ids_to_remove:
                        to_del_ids.append(row.id)
                if to_del_ids:
                    db.query(table).filter(table.id.in_(to_del_ids)).delete(synchronize_session='fetch')

            for row in (
                db.query(NovelMemoryNormCharacter)
                .filter(NovelMemoryNormCharacter.novel_id == novel_id)
                .all()
            ):
                name = str(getattr(row, "name", "") or "").strip()
                if name and _short_id(name) in ids_to_remove:
                    row.is_active = False
                    row.memory_version = memory_version

            for row in (
                db.query(NovelMemoryNormRelation)
                .filter(NovelMemoryNormRelation.novel_id == novel_id)
                .all()
            ):
                relation_id = _relation_identity(
                    str(getattr(row, "src", "") or "").strip(),
                    str(getattr(row, "dst", "") or "").strip(),
                )
                if relation_id in ids_to_remove:
                    row.is_active = False
                    row.memory_version = memory_version
        active_plot_lookup = {
            str(row.body or "").strip(): row
            for row in db.query(NovelMemoryNormPlot)
            .filter(NovelMemoryNormPlot.novel_id == novel_id)
            .all()
            if str(row.body or "").strip()
        }

        # 1. 更新时间线 canonical_entries
        incoming_entries = delta.get("canonical_entries")
        if isinstance(incoming_entries, list):
            for item in incoming_entries:
                if not isinstance(item, dict):
                    continue
                chapter_no = item.get("chapter_no")
                if not isinstance(chapter_no, int):
                    continue
                latest_delta_chapter_no = max(latest_delta_chapter_no, chapter_no)
                
                # 查找是否存在该章节
                entry = db.query(NovelMemoryNormChapter).filter(
                    NovelMemoryNormChapter.novel_id == novel_id,
                    NovelMemoryNormChapter.chapter_no == chapter_no
                ).first()
                
                if not entry:
                    entry = NovelMemoryNormChapter(
                        novel_id=novel_id,
                        chapter_no=chapter_no,
                        memory_version=memory_version
                    )
                    db.add(entry)
                
                entry.chapter_title = str(item.get("chapter_title") or entry.chapter_title or "").strip()
                
                for field in ("key_facts", "causal_results", "open_plots_resolved"):
                    json_field = f"{field}_json"
                    old_list = json.loads(getattr(entry, json_field) or "[]")
                    inc = item.get(field) or []
                    if not isinstance(inc, list):
                        inc = []
                    
                    if replace_timeline:
                        # 刷新模式：直接使用 LLM 提取的内容替换旧内容（但仍做基础去重）
                        if field == "open_plots_resolved":
                            new_list = NovelLLMService._filter_key_resolved_plot_bodies(
                                NovelLLMService._open_plot_bodies_from_mixed(inc),
                                plot_lookup=active_plot_lookup,
                                current_chapter_no=chapter_no,
                            )
                        else:
                            new_list = _dedupe_str_list(inc)
                    else:
                        # 增量模式：追加
                        if field == "open_plots_resolved":
                            inc_norm = NovelLLMService._filter_key_resolved_plot_bodies(
                                NovelLLMService._open_plot_bodies_from_mixed(inc),
                                plot_lookup=active_plot_lookup,
                                current_chapter_no=chapter_no,
                            )
                            new_list = _dedupe_str_list([*old_list, *inc_norm])
                        else:
                            new_list = _dedupe_str_list([*old_list, *inc])
                    setattr(entry, json_field, json.dumps(new_list, ensure_ascii=False))

                oa_raw = item.get("open_plots_added") or []
                if not isinstance(oa_raw, list):
                    oa_raw = []
                bodies_add: list[str] = []
                for x in oa_raw:
                    if isinstance(x, dict):
                        b = str(x.get("body") or "").strip()
                        if b:
                            bodies_add.append(b)
                            plot = db.query(NovelMemoryNormPlot).filter(
                                NovelMemoryNormPlot.novel_id == novel_id,
                                NovelMemoryNormPlot.body == b,
                            ).first()
                            if plot:
                                plot.plot_type = normalize_plot_type(x.get("plot_type"))
                                plot.priority = clamp_int(
                                    x.get("priority"), minimum=0, maximum=100, default=0
                                )
                                plot.estimated_duration = max(
                                    0,
                                    clamp_int(
                                        x.get("estimated_duration"),
                                        minimum=0,
                                        maximum=999,
                                        default=0,
                                    ),
                                )
                                plot.current_stage = str(
                                    x.get("current_stage") or plot.current_stage or ""
                                ).strip()[:2000]
                                plot.resolve_when = str(
                                    x.get("resolve_when") or plot.resolve_when or ""
                                ).strip()[:2000]
                                if chapter_no > 0:
                                    if not getattr(plot, "introduced_chapter", 0):
                                        plot.introduced_chapter = chapter_no
                                    plot.last_touched_chapter = chapter_no
                                active_plot_lookup[b] = plot
                    else:
                        s = str(x or "").strip()
                        if s:
                            bodies_add.append(s)
                
                if replace_timeline:
                    # 刷新模式：替换 open_plots_added
                    entry.open_plots_added_json = json.dumps(
                        _dedupe_str_list(bodies_add), ensure_ascii=False
                    )
                else:
                    # 增量模式：追加
                    old_oa = json.loads(entry.open_plots_added_json or "[]")
                    entry.open_plots_added_json = json.dumps(
                        _dedupe_str_list([*old_oa, *bodies_add]), ensure_ascii=False
                    )

                emo = str(item.get("emotional_state") or "").strip()
                if emo:
                    entry.emotional_state = emo[:2000]
                
                uh = item.get("unresolved_hooks")
                if isinstance(uh, list) and uh:
                    if replace_timeline:
                        # 刷新模式：替换
                        new_uh = _dedupe_str_list([str(x).strip() for x in uh if str(x).strip()])
                    else:
                        # 增量模式：追加
                        old_uh = json.loads(entry.unresolved_hooks_json or "[]")
                        if not isinstance(old_uh, list):
                            old_uh = []
                        new_uh = _dedupe_str_list(
                            [
                                *old_uh,
                                *[str(x).strip() for x in uh if str(x).strip()],
                            ]
                        )
                    entry.unresolved_hooks_json = json.dumps(new_uh, ensure_ascii=False)

                entry.memory_version = memory_version
                stats["canonical_entries"] += 1

        # 2. 处理 open_plots 活跃列表
        raw_top_add = delta.get("open_plots_added", [])
        if not isinstance(raw_top_add, list):
            raw_top_add = []
        for plot_add in raw_top_add:
            if isinstance(plot_add, dict):
                body = str(plot_add.get("body") or "").strip()
                pt = normalize_plot_type(plot_add.get("plot_type"))
                pr = clamp_int(plot_add.get("priority"), minimum=0, maximum=100, default=0)
                est = max(
                    0,
                    clamp_int(
                        plot_add.get("estimated_duration"),
                        minimum=0,
                        maximum=999,
                        default=0,
                    ),
                )
                current_stage = str(plot_add.get("current_stage") or "").strip()
                resolve_when = str(plot_add.get("resolve_when") or "").strip()
            else:
                body = str(plot_add or "").strip()
                pt, pr, est = "Transient", 0, 0
                current_stage, resolve_when = "", ""
            if not body:
                continue
            exists = db.query(NovelMemoryNormPlot).filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.body == body,
            ).first()
            if not exists:
                max_order = (
                    db.query(func.max(NovelMemoryNormPlot.sort_order))
                    .filter(NovelMemoryNormPlot.novel_id == novel_id)
                    .scalar()
                    or 0
                )
                new_plot = NovelMemoryNormPlot(
                    novel_id=novel_id,
                    body=body,
                    sort_order=max_order + 1,
                    memory_version=memory_version,
                    plot_type=pt,
                    priority=pr,
                    estimated_duration=est,
                    current_stage=current_stage[:2000],
                    resolve_when=resolve_when[:2000],
                    introduced_chapter=latest_delta_chapter_no,
                    last_touched_chapter=latest_delta_chapter_no,
                )
                db.add(new_plot)
                active_plot_lookup[body] = new_plot
                stats["open_plots_added"] += 1
            else:
                exists.plot_type = pt
                exists.priority = pr
                exists.estimated_duration = est
                exists.current_stage = (current_stage or exists.current_stage or "")[:2000]
                exists.resolve_when = (resolve_when or exists.resolve_when or "")[:2000]
                if latest_delta_chapter_no > 0:
                    if not getattr(exists, "introduced_chapter", 0):
                        exists.introduced_chapter = latest_delta_chapter_no
                    exists.last_touched_chapter = latest_delta_chapter_no
                exists.memory_version = memory_version
                active_plot_lookup[body] = exists

        # 移除已结案的线索（与 plot.body 对齐：dict 取 body，禁止把 dict 绑进 SQL IN）
        top_resolved = NovelLLMService._filter_key_resolved_plot_bodies(
            NovelLLMService._open_plot_bodies_from_mixed(delta.get("open_plots_resolved")),
            plot_lookup=active_plot_lookup,
            current_chapter_no=latest_delta_chapter_no,
        )
        if top_resolved:
            db.query(NovelMemoryNormPlot).filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.body.in_(top_resolved)
            ).delete(synchronize_session='fetch')
            stats["open_plots_resolved"] += len(top_resolved)

        # 3. 更新角色（新增 / 更新 / 软下线）
        def _ensure_character_row(name: str) -> NovelMemoryNormCharacter:
            char = (
                db.query(NovelMemoryNormCharacter)
                .filter(
                    NovelMemoryNormCharacter.novel_id == novel_id,
                    NovelMemoryNormCharacter.name == name,
                )
                .first()
            )
            if char:
                return char
            max_order = (
                db.query(func.max(NovelMemoryNormCharacter.sort_order))
                .filter(NovelMemoryNormCharacter.novel_id == novel_id)
                .scalar()
                or 0
            )
            char = NovelMemoryNormCharacter(
                novel_id=novel_id,
                name=name,
                sort_order=max_order + 1,
                memory_version=memory_version,
            )
            db.add(char)
            return char

        def _apply_character_item(
            item: dict[str, Any],
            *,
            force_inactive: bool = False,
        ) -> NovelMemoryNormCharacter | None:
            name = str(item.get("name") or "").strip()
            if not name:
                return None
            char = _ensure_character_row(name)
            if item.get("role"):
                char.role = str(item["role"]).strip()
            status = str(item.get("status") or "").strip()
            if status:
                char.status = status

            traits = item.get("traits")
            if traits:
                old_traits = json.loads(char.traits_json or "[]")
                if isinstance(traits, list):
                    new_traits = _dedupe_str_list([*old_traits, *traits])
                else:
                    new_traits = _dedupe_str_list([*old_traits, str(traits)])
                char.traits_json = json.dumps(new_traits, ensure_ascii=False)

            aliases = dedupe_clean_strs(item.get("aliases"))
            if not aliases:
                aliases = extract_aliases(item)
            if aliases:
                old_aliases = json.loads(char.aliases_json or "[]")
                if not isinstance(old_aliases, list):
                    old_aliases = []
                char.aliases_json = json.dumps(
                    dedupe_clean_strs([*old_aliases, *aliases]),
                    ensure_ascii=False,
                )

            tags = item.get("tags")
            if isinstance(tags, list) and tags:
                old_tags = json.loads(char.tags_json or "[]")
                if not isinstance(old_tags, list):
                    old_tags = []
                char.tags_json = json.dumps(
                    dedupe_clean_strs([*old_tags, *[str(x) for x in tags]]),
                    ensure_ascii=False,
                )

            introduced_chapter = coerce_int(
                item.get("introduced_chapter") or item.get("source_chapter_no"),
                default=int(char.introduced_chapter or 0),
            )
            source_chapter_no = coerce_int(
                item.get("source_chapter_no"),
                default=int(char.source_chapter_no or introduced_chapter),
            )
            last_seen_chapter_no = coerce_int(
                item.get("last_seen_chapter_no"),
                default=max(
                    latest_delta_chapter_no,
                    int(char.last_seen_chapter_no or 0),
                    introduced_chapter,
                ),
            )
            expired_raw = item.get("expired_chapter")
            expired_chapter = (
                coerce_int(expired_raw, default=0) if expired_raw is not None else None
            )
            char.introduced_chapter = introduced_chapter
            char.source_chapter_no = source_chapter_no
            char.last_seen_chapter_no = last_seen_chapter_no
            char.expired_chapter = expired_chapter
            if item.get("identity_stage"):
                char.identity_stage = str(item.get("identity_stage") or "").strip()[:64]
            if item.get("exposed_identity_level") is not None:
                char.exposed_identity_level = str(
                    item.get("exposed_identity_level") or ""
                ).strip()[:32]

            detail = json.loads(char.detail_json or "{}")
            for k, v in item.items():
                if k not in ("name", "role", "status", "traits", "is_active"):
                    detail[k] = v
            if latest_delta_chapter_no > 0:
                detail["last_seen_chapter"] = latest_delta_chapter_no
                detail["last_touched_chapter"] = latest_delta_chapter_no
            if force_inactive:
                if latest_delta_chapter_no > 0:
                    detail["deactivated_at_chapter"] = latest_delta_chapter_no
                if status:
                    detail["inactive_reason"] = status
            char.detail_json = json.dumps(detail, ensure_ascii=False)

            if item.get("influence_score") is not None:
                try:
                    char.influence_score = int(item["influence_score"])
                except (TypeError, ValueError):
                    pass
            explicit_active = item.get("is_active")
            if explicit_active is not None:
                char.is_active = bool(explicit_active)
            elif force_inactive or _status_implies_inactive(status):
                char.is_active = False
            elif not status or char.is_active is None:
                char.is_active = True
            explicit_lifecycle = str(item.get("lifecycle_state") or "").strip() or None
            char.lifecycle_state = infer_lifecycle_state(
                is_active=bool(char.is_active),
                introduced_chapter=int(char.introduced_chapter or 0),
                last_seen_chapter=int(char.last_seen_chapter_no or 0),
                expired_chapter=char.expired_chapter,
                explicit=explicit_lifecycle,
            )
            char.memory_version = memory_version
            return char

        for bucket_key in ("characters_added", "characters_updated"):
            incoming_chars = delta.get(bucket_key)
            if isinstance(incoming_chars, list):
                for item in incoming_chars:
                    if not isinstance(item, dict):
                        continue
                    if _apply_character_item(item) is not None:
                        stats["characters_updated"] += 1

        incoming_chars_inactivated = delta.get("characters_inactivated")
        if isinstance(incoming_chars_inactivated, list):
            for item in incoming_chars_inactivated:
                if not isinstance(item, dict):
                    continue
                if _apply_character_item(item, force_inactive=True) is not None:
                    stats["characters_updated"] += 1

        # 3b. 实体影响力批量更新
        inf_updates = delta.get("entity_influence_updates")
        if isinstance(inf_updates, list):
            for u in inf_updates:
                if not isinstance(u, dict):
                    continue
                et = str(u.get("entity_type") or "").strip().lower()
                name = str(u.get("name") or "").strip()
                if not name:
                    continue
                score = u.get("influence_score")
                active = u.get("is_active")
                if et == "character":
                    row = (
                        db.query(NovelMemoryNormCharacter)
                        .filter(
                            NovelMemoryNormCharacter.novel_id == novel_id,
                            NovelMemoryNormCharacter.name == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            row.is_active = bool(active)
                        row.memory_version = memory_version
                elif et == "skill":
                    row = (
                        db.query(NovelMemoryNormSkill)
                        .filter(
                            NovelMemoryNormSkill.novel_id == novel_id,
                            NovelMemoryNormSkill.name == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            if not bool(active):
                                db.delete(row)
                                row = None
                            else:
                                row.is_active = True
                        if row is not None:
                            row.memory_version = memory_version
                elif et == "item":
                    row = (
                        db.query(NovelMemoryNormItem)
                        .filter(
                            NovelMemoryNormItem.novel_id == novel_id,
                            NovelMemoryNormItem.label == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            if not bool(active):
                                db.delete(row)
                                row = None
                            else:
                                row.is_active = True
                        if row is not None:
                            row.memory_version = memory_version
                elif et == "pet":
                    row = (
                        db.query(NovelMemoryNormPet)
                        .filter(
                            NovelMemoryNormPet.novel_id == novel_id,
                            NovelMemoryNormPet.name == name,
                        )
                        .first()
                    )
                    if row:
                        if score is not None:
                            try:
                                row.influence_score = int(score)
                            except (TypeError, ValueError):
                                pass
                        if active is not None:
                            row.is_active = bool(active)
                        row.memory_version = memory_version
                elif et == "plot":
                    row = (
                        db.query(NovelMemoryNormPlot)
                        .filter(
                            NovelMemoryNormPlot.novel_id == novel_id,
                            NovelMemoryNormPlot.body == name,
                        )
                        .first()
                    )
                    if row and score is not None:
                        try:
                            row.priority = int(score)
                        except (TypeError, ValueError):
                            pass
                        row.memory_version = memory_version

        # 4. 关系（新增 / 更新 / 软失效）
        def _ensure_relation_row(src: str, dst: str) -> NovelMemoryNormRelation:
            rel = (
                db.query(NovelMemoryNormRelation)
                .filter(
                    NovelMemoryNormRelation.novel_id == novel_id,
                    NovelMemoryNormRelation.src == src,
                    NovelMemoryNormRelation.dst == dst,
                )
                .first()
            )
            if rel:
                return rel
            max_order = (
                db.query(func.max(NovelMemoryNormRelation.sort_order))
                .filter(NovelMemoryNormRelation.novel_id == novel_id)
                .scalar()
                or 0
            )
            rel = NovelMemoryNormRelation(
                novel_id=novel_id,
                src=src,
                dst=dst,
                sort_order=max_order + 1,
                memory_version=memory_version,
            )
            db.add(rel)
            return rel

        def _apply_relation_item(
            item: dict[str, Any],
            *,
            force_inactive: bool = False,
        ) -> NovelMemoryNormRelation | None:
            src = str(item.get("from") or "").strip()
            dst = str(item.get("to") or "").strip()
            relation = str(item.get("relation") or "").strip()
            if not (src and dst):
                return None
            rel = _ensure_relation_row(src, dst)
            if relation:
                rel.relation = relation
            explicit_active = item.get("is_active")
            if explicit_active is not None:
                rel.is_active = bool(explicit_active)
            else:
                rel.is_active = not force_inactive
            rel.memory_version = memory_version
            return rel

        for bucket_key in ("relations_added", "relations_updated", "relations_changed"):
            incoming_relations = delta.get(bucket_key)
            if isinstance(incoming_relations, list):
                for item in incoming_relations:
                    if not isinstance(item, dict):
                        continue
                    _apply_relation_item(item, force_inactive=False)

        incoming_relations_inactivated = delta.get("relations_inactivated")
        if isinstance(incoming_relations_inactivated, list):
            for item in incoming_relations_inactivated:
                if not isinstance(item, dict):
                    continue
                _apply_relation_item(item, force_inactive=True)

        # 5. 物品（added/removed 可能为字符串或 dict，禁止把 dict 直接绑到 label 列）
        inv_changed = delta.get("inventory_changed")
        if isinstance(inv_changed, dict):
            added = inv_changed.get("added") or []
            removed = inv_changed.get("removed") or []

            removed_labels: list[str] = []
            removed_short_ids: set[str] = set()
            for x in removed:
                if isinstance(x, dict):
                    rid = str(x.get("id") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", rid):
                        removed_short_ids.add(rid)
                else:
                    token = str(x or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", token):
                        removed_short_ids.add(token)
                lab, _ = NovelLLMService._inventory_entry_label_and_detail(x)
                if lab:
                    removed_labels.append(lab)
            if removed_short_ids:
                for row in db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id
                ).all():
                    label = str(getattr(row, "label", "") or "").strip()
                    if label and _short_id(label).lower() in removed_short_ids:
                        removed_labels.append(label)
            if removed_labels:
                removed_labels = _dedupe_str_list(removed_labels)
                db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id,
                    NovelMemoryNormItem.label.in_(removed_labels),
                ).delete(synchronize_session=False)

            for raw in added:
                label, detail_json = NovelLLMService._inventory_entry_label_and_detail(raw)
                if not label:
                    continue
                score = None
                active = None
                if isinstance(raw, dict):
                    score = raw.get("influence_score")
                    active = raw.get("is_active")
                exists = db.query(NovelMemoryNormItem).filter(
                    NovelMemoryNormItem.novel_id == novel_id,
                    NovelMemoryNormItem.label == label,
                ).first()
                if not exists:
                    max_order = (
                        db.query(func.max(NovelMemoryNormItem.sort_order))
                        .filter(NovelMemoryNormItem.novel_id == novel_id)
                        .scalar()
                        or 0
                    )
                    new_item = NovelMemoryNormItem(
                        novel_id=novel_id,
                        label=label,
                        detail_json=detail_json,
                        sort_order=max_order + 1,
                        memory_version=memory_version,
                    )
                    if score is not None:
                        new_item.influence_score = clamp_int(score, minimum=0, maximum=100, default=0)
                    if active is not None:
                        new_item.is_active = bool(active)
                    db.add(new_item)
                else:
                    if isinstance(raw, dict) and detail_json != "{}":
                        exists.detail_json = detail_json
                    if score is not None:
                        exists.influence_score = clamp_int(score, minimum=0, maximum=100, default=0)
                    if active is not None:
                        exists.is_active = bool(active)
                    else:
                        exists.is_active = True
                    exists.memory_version = memory_version
                stats["items_updated"] += 1

        # 6. 技能
        skills_changed = delta.get("skills_changed")
        if isinstance(skills_changed, dict):
            added = skills_changed.get("added") or []
            updated = skills_changed.get("updated") or []
            removed = skills_changed.get("removed") or []

            removed_names: list[str] = []
            removed_short_ids: set[str] = set()
            for raw in removed:
                if isinstance(raw, dict):
                    name = str(raw.get("name") or "").strip()
                    rid = str(raw.get("id") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", rid):
                        removed_short_ids.add(rid)
                else:
                    name = str(raw or "").strip()
                    token = name.lower()
                    if re.fullmatch(r"[0-9a-f]{4}", token):
                        removed_short_ids.add(token)
                if name:
                    removed_names.append(name)
            if removed_short_ids:
                for row in db.query(NovelMemoryNormSkill).filter(
                    NovelMemoryNormSkill.novel_id == novel_id
                ).all():
                    n = str(getattr(row, "name", "") or "").strip()
                    if n and _short_id(n).lower() in removed_short_ids:
                        removed_names.append(n)
            if removed_names:
                removed_names = _dedupe_str_list(removed_names)
                db.query(NovelMemoryNormSkill).filter(
                    NovelMemoryNormSkill.novel_id == novel_id,
                    NovelMemoryNormSkill.name.in_(removed_names),
                ).delete(synchronize_session=False)
            
            for item in [*added, *updated]:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                else:
                    name = str(item or "").strip()
                
                if not name:
                    continue
                
                skill = db.query(NovelMemoryNormSkill).filter(
                    NovelMemoryNormSkill.novel_id == novel_id,
                    NovelMemoryNormSkill.name == name
                ).first()
                
                if not skill:
                    max_order = db.query(func.max(NovelMemoryNormSkill.sort_order)).filter(
                        NovelMemoryNormSkill.novel_id == novel_id
                    ).scalar() or 0
                    skill = NovelMemoryNormSkill(
                        novel_id=novel_id,
                        name=name,
                        sort_order=max_order + 1,
                        memory_version=memory_version
                    )
                    db.add(skill)
                
                if isinstance(item, dict):
                    aliases = dedupe_clean_strs(item.get("aliases"))
                    if aliases:
                        old_aliases = json.loads(skill.aliases_json or "[]")
                        if not isinstance(old_aliases, list):
                            old_aliases = []
                        skill.aliases_json = json.dumps(
                            dedupe_clean_strs([*old_aliases, *aliases]),
                            ensure_ascii=False,
                        )
                    tags = item.get("tags")
                    if isinstance(tags, list) and tags:
                        old_tags = json.loads(skill.tags_json or "[]")
                        if not isinstance(old_tags, list):
                            old_tags = []
                        skill.tags_json = json.dumps(
                            dedupe_clean_strs([*old_tags, *[str(x) for x in tags]]),
                            ensure_ascii=False,
                        )
                    detail = json.loads(skill.detail_json or "{}")
                    for k, v in item.items():
                        if k != "name":
                            detail[k] = v
                    skill.detail_json = json.dumps(detail, ensure_ascii=False)
                    if item.get("influence_score") is not None:
                        skill.influence_score = clamp_int(
                            item.get("influence_score"), minimum=0, maximum=100, default=0
                        )
                    if item.get("is_active") is not None:
                        skill.is_active = bool(item.get("is_active"))
                    else:
                        skill.is_active = True
                    introduced_chapter = coerce_int(
                        item.get("introduced_chapter") or item.get("source_chapter_no"),
                        default=int(skill.introduced_chapter or 0),
                    )
                    source_chapter_no = coerce_int(
                        item.get("source_chapter_no"),
                        default=int(skill.source_chapter_no or introduced_chapter),
                    )
                    last_used_chapter = coerce_int(
                        item.get("last_used_chapter"),
                        default=int(skill.last_used_chapter or 0),
                    )
                    last_seen_chapter_no = coerce_int(
                        item.get("last_seen_chapter_no"),
                        default=max(
                            latest_delta_chapter_no,
                            int(skill.last_seen_chapter_no or 0),
                            last_used_chapter,
                            introduced_chapter,
                        ),
                    )
                    expired_raw = item.get("expired_chapter")
                    skill.introduced_chapter = introduced_chapter
                    skill.source_chapter_no = source_chapter_no
                    skill.last_used_chapter = last_used_chapter
                    skill.last_seen_chapter_no = last_seen_chapter_no
                    skill.expired_chapter = (
                        coerce_int(expired_raw, default=0)
                        if expired_raw is not None
                        else None
                    )
                    explicit_lifecycle = (
                        str(item.get("lifecycle_state") or "").strip() or None
                    )
                    skill.lifecycle_state = infer_lifecycle_state(
                        is_active=bool(skill.is_active),
                        introduced_chapter=int(skill.introduced_chapter or 0),
                        last_seen_chapter=int(skill.last_seen_chapter_no or 0),
                        expired_chapter=skill.expired_chapter,
                        explicit=explicit_lifecycle,
                    )
                skill.memory_version = memory_version
                stats["skills_updated"] += 1

        # 6b. 宠物 / 同伴
        pets_changed = delta.get("pets_changed")
        if isinstance(pets_changed, dict):
            added = pets_changed.get("added") or []
            updated = pets_changed.get("updated") or []
            removed = pets_changed.get("removed") or []

            removed_names: list[str] = []
            removed_short_ids: set[str] = set()
            for raw in removed:
                if isinstance(raw, dict):
                    name = str(raw.get("name") or "").strip()
                    rid = str(raw.get("id") or "").strip().lower()
                    if re.fullmatch(r"[0-9a-f]{4}", rid):
                        removed_short_ids.add(rid)
                else:
                    name = str(raw or "").strip()
                    token = name.lower()
                    if re.fullmatch(r"[0-9a-f]{4}", token):
                        removed_short_ids.add(token)
                if name:
                    removed_names.append(name)
            if removed_short_ids:
                for row in db.query(NovelMemoryNormPet).filter(
                    NovelMemoryNormPet.novel_id == novel_id
                ).all():
                    n = str(getattr(row, "name", "") or "").strip()
                    if n and _short_id(n).lower() in removed_short_ids:
                        removed_names.append(n)
            if removed_names:
                removed_names = _dedupe_str_list(removed_names)
                db.query(NovelMemoryNormPet).filter(
                    NovelMemoryNormPet.novel_id == novel_id,
                    NovelMemoryNormPet.name.in_(removed_names),
                ).update(
                    {
                        NovelMemoryNormPet.is_active: False,
                        NovelMemoryNormPet.memory_version: memory_version,
                    },
                    synchronize_session=False,
                )

            for item in [*added, *updated]:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                else:
                    name = str(item or "").strip()
                if not name:
                    continue
                pet = db.query(NovelMemoryNormPet).filter(
                    NovelMemoryNormPet.novel_id == novel_id,
                    NovelMemoryNormPet.name == name,
                ).first()
                if not pet:
                    max_order = db.query(func.max(NovelMemoryNormPet.sort_order)).filter(
                        NovelMemoryNormPet.novel_id == novel_id
                    ).scalar() or 0
                    pet = NovelMemoryNormPet(
                        novel_id=novel_id,
                        name=name,
                        sort_order=max_order + 1,
                        memory_version=memory_version,
                    )
                    db.add(pet)
                if isinstance(item, dict):
                    detail = json.loads(pet.detail_json or "{}")
                    for k, v in item.items():
                        if k != "name":
                            detail[k] = v
                    pet.detail_json = json.dumps(detail, ensure_ascii=False)
                    if item.get("influence_score") is not None:
                        pet.influence_score = clamp_int(
                            item.get("influence_score"), minimum=0, maximum=100, default=0
                        )
                    if item.get("is_active") is not None:
                        pet.is_active = bool(item.get("is_active"))
                    else:
                        pet.is_active = True
                pet.memory_version = memory_version

        # 7. 更新 Outline (main_plot, forbidden_constraints 等)
        outline = db.get(NovelMemoryNormOutline, novel_id)
        if not outline:
            outline = NovelMemoryNormOutline(novel_id=novel_id)
            db.add(outline)
        
        fc_add = delta.get("forbidden_constraints_added", [])
        if isinstance(fc_add, list) and fc_add:
            fc = json.loads(outline.forbidden_constraints_json or "[]")
            if not isinstance(fc, list):
                fc = []
            fc = _dedupe_str_list(
                [
                    *fc,
                    *[str(x).strip() for x in fc_add if str(x).strip()],
                ]
            )
            outline.forbidden_constraints_json = json.dumps(fc, ensure_ascii=False)

        outline.memory_version = memory_version

        return stats

    def _merge_memory_delta(
        self,
        prev_memory_json: str,
        delta: dict[str, Any],
        replace_timeline: bool = False,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        prev_data = _safe_json_dict(prev_memory_json)
        data = dict(prev_data)
        stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
        }

        # 1. 时间线处理
        canonical_map: dict[int, dict[str, Any]] = {}
        for item in _canonical_entries_from_payload(prev_data):
            normalized = self._normalize_delta_entry(item)
            if normalized is not None:
                canonical_map[normalized["chapter_no"]] = normalized

        incoming_entries = delta.get("canonical_entries")
        if isinstance(incoming_entries, list):
            for item in incoming_entries:
                normalized = self._normalize_delta_entry(item)
                if normalized is None:
                    continue
                chapter_no = normalized["chapter_no"]
                if replace_timeline:
                    # 刷新模式：直接覆盖该章节的时间线条目
                    canonical_map[chapter_no] = normalized
                else:
                    # 增量模式：合并
                    canonical_map[chapter_no] = self._merge_timeline_entry(
                        canonical_map.get(chapter_no, {"chapter_no": chapter_no}), normalized
                    )
                stats["canonical_entries"] += 1

        ordered_timeline = [canonical_map[k] for k in sorted(canonical_map.keys())]
        latest_timeline_chapter_no = (
            ordered_timeline[-1]["chapter_no"] if ordered_timeline else 0
        )

        # 2. 核心 ID 删除逻辑：IDS TO REMOVE
        ids_to_remove = set(delta.get("ids_to_remove") or [])

        def _normalize_plot_obj(raw: Any, *, chapter_no: int = 0) -> dict[str, Any] | None:
            if isinstance(raw, dict):
                body = str(raw.get("body") or raw.get("text") or "").strip()
                if not body:
                    return None
                iid = raw.get("id") or _short_id(body)
                return {
                    "id": iid,
                    "body": body,
                    "plot_type": normalize_plot_type(raw.get("plot_type")),
                    "priority": clamp_int(raw.get("priority"), minimum=0, maximum=100, default=0),
                    "estimated_duration": max(0, clamp_int(raw.get("estimated_duration"), minimum=0, maximum=999, default=0)),
                    "current_stage": str(raw.get("current_stage") or "").strip()[:500],
                    "resolve_when": str(raw.get("resolve_when") or "").strip()[:500],
                    "introduced_chapter": max(0, clamp_int(raw.get("introduced_chapter"), minimum=0, maximum=20000, default=chapter_no)),
                    "last_touched_chapter": max(0, clamp_int(raw.get("last_touched_chapter"), minimum=0, maximum=20000, default=chapter_no)),
                }
            body = str(raw or "").strip()
            if not body: return None
            return {
                "id": _short_id(body), "body": body, "plot_type": "Transient", "priority": 0, 
                "estimated_duration": 0, "current_stage": "", "resolve_when": "", 
                "introduced_chapter": chapter_no, "last_touched_chapter": chapter_no
            }

        def _merge_plot_state(base: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base or {})
            merged["id"] = incoming.get("id") or merged.get("id") or _short_id(incoming["body"])
            merged["body"] = incoming["body"]
            merged["plot_type"] = normalize_plot_type(incoming.get("plot_type") or merged.get("plot_type"))
            merged["priority"] = clamp_int(incoming.get("priority", merged.get("priority", 0)), minimum=0, maximum=100, default=0)
            merged["estimated_duration"] = max(0, clamp_int(incoming.get("estimated_duration", merged.get("estimated_duration", 0)), minimum=0, maximum=999, default=0))
            merged["current_stage"] = str(incoming.get("current_stage") or merged.get("current_stage") or "").strip()[:500]
            merged["resolve_when"] = str(incoming.get("resolve_when") or merged.get("resolve_when") or "").strip()[:500]
            introduced = max(0, clamp_int(merged.get("introduced_chapter") or incoming.get("introduced_chapter"), minimum=0, maximum=20000, default=0))
            if introduced <= 0: introduced = latest_timeline_chapter_no
            merged["introduced_chapter"] = introduced
            merged["last_touched_chapter"] = max(
                clamp_int(merged.get("last_touched_chapter"), minimum=0, maximum=20000, default=0),
                clamp_int(incoming.get("last_touched_chapter"), minimum=0, maximum=20000, default=latest_timeline_chapter_no)
            )
            return merged

        # 3. Open Plots 合并与清理
        plot_map: dict[str, dict[str, Any]] = {}
        prev_open_plots = prev_data.get("open_plots")
        if isinstance(prev_open_plots, list):
            for item in prev_open_plots:
                normalized_plot = _normalize_plot_obj(item)
                if normalized_plot: plot_map[normalized_plot["body"]] = normalized_plot
        
        # 移除 ID 在 ids_to_remove 中的项
        plot_keys_to_del = [k for k, v in plot_map.items() if v.get("id") in ids_to_remove]
        for k in plot_keys_to_del: plot_map.pop(k)

        raw_top_add = delta.get("open_plots_added", [])
        top_added_bodies = self._open_plot_bodies_from_mixed(raw_top_add if isinstance(raw_top_add, list) else [])
        for item in raw_top_add if isinstance(raw_top_add, list) else []:
            normalized_plot = _normalize_plot_obj(item, chapter_no=latest_timeline_chapter_no)
            if normalized_plot:
                plot_map[normalized_plot["body"]] = _merge_plot_state(plot_map.get(normalized_plot["body"]), normalized_plot)

        # 4. 角色更新 (ID 化，虽然角色通常按名匹配)
        characters_by_name: dict[str, dict[str, Any]] = {}
        prev_characters = prev_data.get("characters", [])
        if isinstance(prev_characters, list):
            for item in prev_characters:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        # 分配 ID
                        if "id" not in item: item["id"] = _short_id(name)
                        characters_by_name[name] = dict(item)
        
        # 人物遵循软下线，不在合并时直接删除
        for character in characters_by_name.values():
            if character.get("id") in ids_to_remove:
                character["is_active"] = False

        for bucket_key in ("characters_added", "characters_updated"):
            incoming_chars = delta.get(bucket_key)
            if isinstance(incoming_chars, list):
                for item in incoming_chars:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    base = characters_by_name.get(
                        name, {"name": name, "id": _short_id(name), "is_active": True}
                    )
                    for key in ("role", "status"):
                        val = str(item.get(key) or "").strip()
                        if val:
                            base[key] = val
                    traits = item.get("traits")
                    if isinstance(traits, list):
                        base["traits"] = _dedupe_str_list(traits)
                    elif "traits" not in base:
                        base["traits"] = []
                    if item.get("influence_score") is not None:
                        try:
                            base["influence_score"] = clamp_int(
                                item["influence_score"], minimum=0, maximum=100, default=0
                            )
                        except Exception:
                            pass
                    if item.get("is_active") is not None:
                        base["is_active"] = bool(item["is_active"])
                    elif _status_implies_inactive(item.get("status")):
                        base["is_active"] = False
                    characters_by_name[name] = base
                    stats["characters_updated"] += 1
        incoming_chars_inactivated = delta.get("characters_inactivated")
        if isinstance(incoming_chars_inactivated, list):
            for item in incoming_chars_inactivated:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                base = characters_by_name.get(
                    name, {"name": name, "id": _short_id(name), "is_active": False}
                )
                for key in ("role", "status"):
                    val = str(item.get(key) or "").strip()
                    if val:
                        base[key] = val
                traits = item.get("traits")
                if isinstance(traits, list):
                    base["traits"] = _dedupe_str_list(traits)
                elif "traits" not in base:
                    base["traits"] = []
                if item.get("influence_score") is not None:
                    try:
                        base["influence_score"] = clamp_int(
                            item["influence_score"], minimum=0, maximum=100, default=0
                        )
                    except Exception:
                        pass
                base["is_active"] = False
                characters_by_name[name] = base
                stats["characters_updated"] += 1
        data["characters"] = list(characters_by_name.values())

        # 5. Forbidden Constraints (ID 化)
        fc_map: dict[str, dict[str, Any]] = {}
        fc_prev = prev_data.get("forbidden_constraints", [])
        if isinstance(fc_prev, list):
            for x in fc_prev:
                if isinstance(x, dict):
                    body = str(x.get("body") or "").strip()
                    iid = x.get("id") or _short_id(body)
                    if body: fc_map[iid] = {"body": body, "id": iid}
                else:
                    body = str(x).strip()
                    if body:
                        iid = _short_id(body)
                        fc_map[iid] = {"body": body, "id": iid}
        
        # 移除
        for iid in ids_to_remove: fc_map.pop(iid, None)
        
        # 新增
        fc_add = delta.get("forbidden_constraints_added", [])
        if isinstance(fc_add, list):
            for x in fc_add:
                body = str(x).strip()
                if body:
                    iid = _short_id(body)
                    fc_map[iid] = {"body": body, "id": iid}
        data["forbidden_constraints"] = list(fc_map.values())

        # 6. Relations (ID 化)
        relation_map: dict[str, dict[str, Any]] = {}
        prev_relations = prev_data.get("relations", [])
        if isinstance(prev_relations, list):
            for item in prev_relations:
                if not isinstance(item, dict): continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                if src and dst:
                    iid = item.get("id") or _relation_identity(src, dst)
                    relation_map[iid] = {
                        "id": iid, "from": src, "to": dst, 
                        "relation": str(item.get("relation") or "").strip(),
                        "is_active": True if item.get("is_active") is None else bool(item.get("is_active")),
                    }
        # 关系遵循软失效，不在合并时直接删除
        for relation in relation_map.values():
            if relation.get("id") in ids_to_remove:
                relation["is_active"] = False
        # 更新/新增
        for bucket_key in ("relations_added", "relations_updated", "relations_changed"):
            incoming_relations = delta.get(bucket_key)
            if isinstance(incoming_relations, list):
                for item in incoming_relations:
                    if not isinstance(item, dict):
                        continue
                    src = str(item.get("from") or "").strip()
                    dst = str(item.get("to") or "").strip()
                    relation = str(item.get("relation") or "").strip()
                    if src and dst:
                        iid = item.get("id") or _relation_identity(src, dst)
                        base = relation_map.get(
                            iid,
                            {"id": iid, "from": src, "to": dst, "relation": relation, "is_active": True},
                        )
                        if relation:
                            base["relation"] = relation
                        if item.get("is_active") is not None:
                            base["is_active"] = bool(item.get("is_active"))
                        else:
                            base["is_active"] = True
                        relation_map[iid] = base
        incoming_relations_inactivated = delta.get("relations_inactivated")
        if isinstance(incoming_relations_inactivated, list):
            for item in incoming_relations_inactivated:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("from") or "").strip()
                dst = str(item.get("to") or "").strip()
                relation = str(item.get("relation") or "").strip()
                if src and dst:
                    iid = item.get("id") or _relation_identity(src, dst)
                    base = relation_map.get(
                        iid,
                        {"id": iid, "from": src, "to": dst, "relation": relation, "is_active": False},
                    )
                    if relation:
                        base["relation"] = relation
                    base["is_active"] = False
                    relation_map[iid] = base
        data["relations"] = list(relation_map.values())

        # 7. Generic Collections: Inventory, Skills, Pets (ID 化)
        def _merge_named_collection_with_id(key: str, changed_key: str):
            prev_items = prev_data.get(key, [])
            changed = delta.get(changed_key)
            item_map: dict[str, dict[str, Any]] = {}
            if isinstance(prev_items, list):
                for x in prev_items:
                    if isinstance(x, dict):
                        name = str(x.get("name") or x.get("label") or "").strip()
                        iid = x.get("id") or _short_id(name)
                        if name: item_map[iid] = {**x, "id": iid, "name": name}
            
            # 移除
            for iid in ids_to_remove: item_map.pop(iid, None)
            # LLM 手动指定的删除
            if isinstance(changed, dict):
                removed = changed.get("removed", [])
                if isinstance(removed, list):
                    for r in removed:
                        rid = str(r).strip()
                        item_map.pop(rid, None)
                        # 兜底：按名删
                        to_del = [k for k, v in item_map.items() if v.get("name") == rid]
                        for k in to_del: item_map.pop(k)

                # 更新/新增
                for field in ("added", "updated"):
                    bucket = changed.get(field)
                    if isinstance(bucket, list):
                        for raw in bucket:
                            if not isinstance(raw, dict): continue
                            name = str(raw.get("name") or raw.get("label") or "").strip()
                            if not name: continue
                            iid = raw.get("id") or _short_id(name)
                            base = item_map.get(iid, {"id": iid, "name": name, "is_active": True})
                            for k, v in raw.items():
                                if k in ("id", "name"): continue
                                base[k] = v
                            item_map[iid] = base
                data[key] = list(item_map.values())

        _merge_named_collection_with_id("inventory", "inventory_changed")
        _merge_named_collection_with_id("skills", "skills_changed")
        _merge_named_collection_with_id("pets", "pets_changed")

        # 8. 移除冗余模块
        for old_key in ("notes", "world_rules", "arcs", "themes", "timeline_archive_summary", "main_plot_history"):
            data.pop(old_key, None)

        if not isinstance(data.get("main_plot"), str) or not str(data.get("main_plot")).strip():
            data["main_plot"] = str(prev_data.get("main_plot") or "")

        data["canonical_timeline"] = ordered_timeline
        data["canonical_timeline_hot"] = []
        data["canonical_timeline_cold"] = []

        return data, stats

    def _postprocess_memory_layers(
        self, payload_json: str, prev_memory_json: str = "{}"
    ) -> str:
        data = _safe_json_dict(payload_json)
        prev_data = _safe_json_dict(prev_memory_json)
        if not data: return payload_json

        # 确保关键列表存在
        for key in ("characters", "relations", "inventory", "skills", "pets", "open_plots", "forbidden_constraints"):
            if not isinstance(data.get(key), list):
                data[key] = prev_data.get(key, []) if isinstance(prev_data.get(key), list) else []
        
        if not isinstance(data.get("main_plot"), str):
            data["main_plot"] = str(prev_data.get("main_plot") or "")

        # 移除已弃用字段
        for old_key in ("notes", "world_rules", "arcs", "themes", "timeline_archive_summary", "main_plot_history"):
            data.pop(old_key, None)

        # 确保 open_plots 都有 ID
        if isinstance(data.get("open_plots"), list):
            for p in data["open_plots"]:
                if isinstance(p, dict) and "id" not in p:
                    p["id"] = _short_id(str(p.get("body") or ""))

        full_entries = _canonical_entries_from_payload(data)
        normalized_entries: list[dict[str, Any]] = []
        for item in full_entries:
            normalized = self._normalize_delta_entry(item)
            if normalized: normalized_entries.append(normalized)
        normalized_entries.sort(key=lambda x: x["chapter_no"])

        hot_n = max(1, int(settings.novel_timeline_hot_n))
        hot = normalized_entries[-hot_n:] if len(normalized_entries) > hot_n else normalized_entries
        cold = normalized_entries[:-hot_n] if len(normalized_entries) > hot_n else []

        data["canonical_timeline_hot"] = hot
        data["canonical_timeline_cold"] = cold
        data["canonical_timeline"] = hot
        return json.dumps(data, ensure_ascii=False)


    def _validate_memory_with_db(
        self,
        db: Session,
        novel_id: str,
        delta: dict[str, Any],
        candidate_json: str,
    ) -> dict[str, list[str]]:
        """
        利用数据库当前状态，校验 LLM 返回的增量是否合法，防止幻觉导致的误删除或冲突。
        """
        result = self._empty_validation_result()

        # 1. 时间线章节号去重（自动修复，不再报错阻断）
        incoming_entries = delta.get("canonical_entries")
        if isinstance(incoming_entries, list):
            seen_nos: set[int] = set()
            for item in incoming_entries:
                cn = self._extract_chapter_no(item)
                if cn is None:
                    continue
                if cn in seen_nos:
                    # 自动去重，记录警告但不阻断
                    result["warnings"].append(
                        f"检测到重复章节号 {cn}，已自动合并"
                    )
                seen_nos.add(cn)

        # 2. 校验角色更新
        incoming_chars = delta.get("characters_updated")
        if isinstance(incoming_chars, list):
            for item in incoming_chars:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                # 如果只有 role/status 更新，检查角色是否存在
                # 如果是全新的角色（没有在 DB 中），这通常意味着模型在“更新”一个它认为存在的但实际不存在的角色
                # 但在这里我们允许 Upsert，所以也许不需要报错，除非它是误删了其他信息
            
            # 自动去重角色更新
            seen_char_names: set[str] = set()
            unique_chars: list[dict[str, Any]] = []
            for item in incoming_chars:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                if name in seen_char_names:
                    result["warnings"].append(f"角色 '{name}' 重复更新，已合并")
                    for idx, existing in enumerate(unique_chars):
                        if str(existing.get("name", "")).strip() == name:
                            unique_chars[idx] = {**existing, **item}
                            break
                else:
                    seen_char_names.add(name)
                    unique_chars.append(item)
            
            if unique_chars:
                delta["characters_updated"] = unique_chars

        return self._merge_validation_results(result)

    @staticmethod
    def _empty_validation_result() -> dict[str, list[str]]:
        return {
            "blocking_errors": [],
            "warnings": [],
            "auto_pass_notes": [],
        }

    @staticmethod
    def _merge_validation_results(*parts: dict[str, list[str]]) -> dict[str, list[str]]:
        merged = NovelLLMService._empty_validation_result()
        for part in parts:
            if not isinstance(part, dict):
                continue
            for key in merged:
                vals = part.get(key)
                if isinstance(vals, list):
                    merged[key].extend(str(v).strip() for v in vals if str(v).strip())
        for key in merged:
            merged[key] = _dedupe_str_list(merged[key])
        return merged

    def _classify_removed_open_plots(
        self,
        db: Session | None,
        novel_id: str | None,
        removed_open: set[str],
    ) -> dict[str, list[str]]:
        result = self._empty_validation_result()
        if not removed_open:
            return result
        if not db or not novel_id:
            result["warnings"].append(
                "活跃 open_plots 被无理由删除：" + "；".join(sorted(removed_open)[:5])
            )
            return result

        latest_chapter_no = (
            db.query(func.max(NovelMemoryNormChapter.chapter_no))
            .filter(NovelMemoryNormChapter.novel_id == novel_id)
            .scalar()
            or 0
        )
        rows = (
            db.query(NovelMemoryNormPlot)
            .filter(
                NovelMemoryNormPlot.novel_id == novel_id,
                NovelMemoryNormPlot.body.in_(list(removed_open)),
            )
            .all()
        )
        by_body = {str(row.body or "").strip(): row for row in rows}
        for body in sorted(removed_open):
            row = by_body.get(body)
            if row is None:
                result["warnings"].append(f"活跃 open_plots 疑似被删除：{body}")
                continue
            plot_type = str(getattr(row, "plot_type", "Transient") or "Transient")
            priority = int(getattr(row, "priority", 0) or 0)
            estimated_duration = int(getattr(row, "estimated_duration", 0) or 0)
            touched = max(
                int(getattr(row, "last_touched_chapter", 0) or 0),
                int(getattr(row, "introduced_chapter", 0) or 0),
            )
            is_stale = (
                estimated_duration > 0
                and touched > 0
                and latest_chapter_no > 0
                and (latest_chapter_no - touched)
                > (estimated_duration + settings.novel_open_plot_stale_grace_chapters)
            )
            can_auto_pass = (
                plot_type.lower() == "transient"
                and priority <= 3
                and (is_stale or (0 < estimated_duration <= 3))
            )
            if can_auto_pass:
                note = (
                    f"自动放行：低风险待收束线可移出热层：{body}"
                    f"（plot_type={plot_type}，priority={priority}，estimated_duration={estimated_duration}"
                )
                if is_stale:
                    note += "，已 stale"
                note += "）"
                result["auto_pass_notes"].append(note)
            else:
                result["warnings"].append(
                    f"活跃 open_plots 疑似被删除：{body}"
                    f"（plot_type={plot_type}，priority={priority}，estimated_duration={estimated_duration}）"
                )
        return self._merge_validation_results(result)

    def _classify_removed_characters(
        self,
        db: Session | None,
        novel_id: str | None,
        missing_chars: set[str],
    ) -> dict[str, list[str]]:
        result = self._empty_validation_result()
        if not missing_chars:
            return result
        if not db or not novel_id:
            result["warnings"].append("已有角色被删除：" + "；".join(sorted(missing_chars)[:5]))
            return result

        rows = (
            db.query(NovelMemoryNormCharacter)
            .filter(
                NovelMemoryNormCharacter.novel_id == novel_id,
                NovelMemoryNormCharacter.name.in_(list(missing_chars)),
            )
            .all()
        )
        by_name = {str(row.name or "").strip(): row for row in rows}
        for name in sorted(missing_chars):
            row = by_name.get(name)
            if row is None:
                result["warnings"].append(f"已有角色疑似被删除：{name}")
                continue
            influence_score = int(getattr(row, "influence_score", 0) or 0)
            is_active = bool(getattr(row, "is_active", True))
            if (not is_active) or influence_score <= 2:
                result["auto_pass_notes"].append(
                    f"自动放行：低影响或已退场角色可从热层移出：{name}"
                    f"（影响力={influence_score}，{'活跃' if is_active else '已退场'}）"
                )
            else:
                result["warnings"].append(
                    f"已有角色疑似被删除：{name}"
                    f"（影响力={influence_score}，{'活跃' if is_active else '已退场'}）"
                )
        return self._merge_validation_results(result)

    def _validate_memory_payload(
        self,
        candidate_json: str,
        prev_memory_json: str,
        *,
        delta: dict[str, Any] | None = None,
        db: Session | None = None,
        novel_id: str | None = None,
    ) -> dict[str, list[str]]:
        data = _safe_json_dict(candidate_json)
        prev_data = _safe_json_dict(prev_memory_json)
        result = self._empty_validation_result()
        if not data:
            result["blocking_errors"].append("候选记忆不是合法 JSON 对象")
            return result

        for key in ("characters", "relations", "inventory", "skills", "pets", "open_plots"):
            if not isinstance(data.get(key), list):
                result["blocking_errors"].append(f"{key} 必须为数组")
        for key in ("world_rules", "arcs", "themes", "notes", "timeline_archive_summary"):
            if key in data and not isinstance(data.get(key), list):
                result["blocking_errors"].append(f"{key} 必须为数组")
        if "main_plot" in data and not isinstance(data.get("main_plot"), str):
            result["blocking_errors"].append("main_plot 必须为字符串")

        entries = _canonical_entries_from_payload(data)
        last_no = 0
        seen: set[int] = set()
        for entry in entries:
            normalized = self._normalize_delta_entry(entry)
            if normalized is None:
                result["blocking_errors"].append("canonical_timeline 存在非法条目")
                continue
            chapter_no = normalized["chapter_no"]
            if chapter_no in seen:
                result["blocking_errors"].append(f"canonical_timeline 第 {chapter_no} 章重复")
            if chapter_no < last_no:
                result["blocking_errors"].append("canonical_timeline 章节号必须递增")
            seen.add(chapter_no)
            last_no = max(last_no, chapter_no)

        prev_open = set(self._open_plot_bodies_from_mixed(prev_data.get("open_plots", [])))
        new_open = set(self._open_plot_bodies_from_mixed(data.get("open_plots", [])))
        removed_open = prev_open - new_open
        resolved = set()
        for entry in entries:
            if isinstance(entry, dict):
                resolved.update(
                    _dedupe_str_list(
                        NovelLLMService._open_plot_bodies_from_mixed(entry.get("open_plots_resolved"))
                    )
                )
        if delta:
            resolved.update(
                _dedupe_str_list(
                    NovelLLMService._open_plot_bodies_from_mixed(delta.get("open_plots_resolved"))
                )
            )
        unexpected_removed = removed_open - resolved
        if unexpected_removed:
            result = self._merge_validation_results(
                result,
                self._classify_removed_open_plots(db, novel_id, unexpected_removed),
            )

        # 不再校验 open_plots_resolved 是否落在「历史激活池」内，避免表述微差导致阻断；格式与非空由 JSON 结构保证。

        prev_chars = {
            str(item.get("name") or "").strip()
            for item in prev_data.get("characters", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        new_chars = {
            str(item.get("name") or "").strip()
            for item in data.get("characters", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        missing_chars = prev_chars - new_chars
        if missing_chars:
            result = self._merge_validation_results(
                result,
                self._classify_removed_characters(db, novel_id, missing_chars),
            )

        return self._merge_validation_results(result)

    @staticmethod
    def _get_latest_memory_version(db: Session, novel_id: str) -> int:
        return db.query(func.max(NovelMemory.version)).filter(
            NovelMemory.novel_id == novel_id
        ).scalar() or 0

    async def _apply_memory_delta_batch(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        skip_snapshot: bool = False,
    ) -> dict[str, Any]:
        router = self._router(db=db)
        raw = await self._chat_text_with_timeout_retry(
            router=router,
            operation="memory_refresh",
            novel_id=novel.id,
            messages=self._memory_delta_messages(novel, chapters_summary, prev_memory, db=db if isinstance(db, Session) else None),
            temperature=0.2,
            web_search=self._novel_web_search(db, flow="memory_refresh"),
            timeout=settings.novel_memory_refresh_batch_timeout,
            max_tokens=settings.novel_memory_delta_max_tokens,
            response_format={"type": "json_object"},
            **self._bill_kw(db, self._billing_user_id),
        )
        delta = self._parse_refresh_memory_response(raw)
        if not delta:
            logger.warning(
                "memory delta invalid json(async) | novel_id=%s provider=%s model=%s raw_preview=%r",
                novel.id,
                "ai302",
                router.model or "-",
                (raw or "")[:800],
            )
            delta = await self._repair_refresh_memory_response(
                router=router,
                raw=raw,
                db=db,
            )
        if delta:
            delta, supplemented_nos = self._supplement_missing_canonical_entries(
                delta, chapters_summary
            )
            if supplemented_nos:
                logger.warning(
                    "memory delta canonical supplemented(async) | novel_id=%s chapters=%s",
                    novel.id,
                    supplemented_nos,
                )
        if not delta:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": "{}",
                "errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "blocking_errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "warnings": [],
                "auto_pass_notes": [],
                "stats": {},
                "stage_status": {
                    "delta": "failed",
                    "validation": "skipped",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }
        
        # 1. 计算合并后的 JSON (用于校验和快照)
        merged, stats = self._merge_memory_delta(prev_memory, delta, replace_timeline=replace_timeline)
        candidate_json = self._postprocess_memory_layers(
            json.dumps(merged, ensure_ascii=False), prev_memory_json=prev_memory
        )
        
        # 2. 校验
        validation = self._validate_memory_payload(
            candidate_json,
            prev_memory,
            delta=delta,
            db=db if isinstance(db, Session) else None,
            novel_id=novel.id if db else None,
        )
        if db:
            db_validation = self._validate_memory_with_db(db, novel.id, delta, candidate_json)
            validation = self._merge_validation_results(validation, db_validation)

        blocking_errors = validation["blocking_errors"]
        warnings = validation["warnings"]
        auto_pass_notes = validation["auto_pass_notes"]

        if blocking_errors:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": candidate_json,
                "errors": blocking_errors,
                "blocking_errors": blocking_errors,
                "warnings": warnings,
                "auto_pass_notes": auto_pass_notes,
                "stats": stats,
                "delta": delta,
                "stage_status": {
                    "delta": "ok",
                    "validation": "blocked",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }

        # 3. 如果没有 blocking_errors 且有 db，则执行规范化表更新
        new_version = 0
        norm_status = "skipped"
        snapshot_status = "skipped" if skip_snapshot else "pending"
        if db and not blocking_errors:
            try:
                # 使用 Savepoint 保护事务，防止局部失败导致全局回滚（如章节审批状态丢失）
                with db.begin_nested():
                    new_version = self._get_latest_memory_version(db, novel.id) + 1
                    db_stats = self._upsert_normalized_memory_from_delta(
                        db,
                        novel.id,
                        delta,
                        new_version,
                        replace_timeline=replace_timeline,
                        chapters_summary=chapters_summary,
                    )
                    # 合并统计信息
                    for k, v in db_stats.items():
                        stats[k] = max(stats.get(k, 0), v)
                    norm_status = "ok"
                    
                    # 确保大纲表存在，防止 sync 时由于缺少 outline 行导致快照为空
                    from app.models.novel_memory_norm import NovelMemoryNormOutline
                    outline = db.get(NovelMemoryNormOutline, novel.id)
                    if not outline:
                        outline = NovelMemoryNormOutline(
                            novel_id=novel.id,
                            memory_version=new_version,
                            main_plot=novel.intro or "",
                        )
                        db.add(outline)
                    else:
                        outline.memory_version = new_version

                    # 真源为规范化表：快照由分表派生
                    if not skip_snapshot:
                        snap_ver = sync_json_snapshot_from_normalized(
                            db, novel.id, summary="规范化存储自动快照（batch/incremental）"
                        )
                        new_version = snap_ver
                        snapshot_status = "ok"
                    else:
                        snapshot_status = "skipped"
                
                # 显式 flush 确保状态可见，但由外部调用者（Router）负责最终 commit
                db.flush()
                
                if not skip_snapshot:
                    latest_row = (
                        db.query(NovelMemory)
                        .filter(NovelMemory.novel_id == novel.id)
                        .order_by(NovelMemory.version.desc())
                        .first()
                    )
                    if latest_row and latest_row.payload_json:
                        candidate_json = latest_row.payload_json
            except Exception as e:
                # 局部回滚 Savepoint，不影响外部事务（如章节审批状态）
                logger.exception("Failed to update normalized memory tables (savepoint rolled back): %s", e)
                return {
                    "ok": False,
                    "status": "failed",
                    "payload_json": prev_memory,
                    "candidate_json": candidate_json,
                    "errors": [f"更新规范化表失败：{e}"],
                    "blocking_errors": [],
                    "warnings": warnings,
                    "auto_pass_notes": auto_pass_notes,
                    "stats": stats,
                    "delta": delta,
                    "error": f"更新规范化表失败: {e}",
                    "stage_status": {
                        "delta": "ok",
                        "validation": "ok",
                        "norm": "failed",
                        "snapshot": "failed" if not skip_snapshot else "skipped",
                    },
                }
        
        return {
            "ok": True,
            "status": "warning" if warnings else "ok",
            "payload_json": candidate_json,
            "candidate_json": candidate_json,
            "errors": [],
            "blocking_errors": [],
            "warnings": warnings,
            "auto_pass_notes": auto_pass_notes,
            "stats": stats,
            "delta": delta,
            "version": new_version,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if warnings else "ok",
                "norm": norm_status,
                "snapshot": snapshot_status,
            },
        }

    def _apply_memory_delta_batch_sync(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        skip_snapshot: bool = False,
    ) -> dict[str, Any]:
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="memory_refresh",
            novel_id=novel.id,
            messages=self._memory_delta_messages(novel, chapters_summary, prev_memory, db=db if isinstance(db, Session) else None),
            temperature=0.2,
            timeout=settings.novel_memory_refresh_batch_timeout,
            web_search=self._novel_web_search(db, flow="memory_refresh"),
            max_tokens=settings.novel_memory_delta_max_tokens,
            response_format={"type": "json_object"},
            **self._bill_kw(db, self._billing_user_id),
        )
        delta = self._parse_refresh_memory_response(raw)
        if not delta:
            logger.warning(
                "memory delta invalid json(sync) | novel_id=%s provider=%s model=%s raw_preview=%r",
                novel.id,
                "ai302",
                router.model or "-",
                (raw or "")[:800],
            )
            delta = self._repair_refresh_memory_response_sync(
                router=router,
                raw=raw,
                db=db,
            )
        if delta:
            delta, supplemented_nos = self._supplement_missing_canonical_entries(
                delta, chapters_summary
            )
            if supplemented_nos:
                logger.warning(
                    "memory delta canonical supplemented(sync) | novel_id=%s chapters=%s",
                    novel.id,
                    supplemented_nos,
                )
        if not delta:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": "{}",
                "errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "blocking_errors": ["LLM 未返回合法的记忆增量 JSON（已尝试二次修复）"],
                "warnings": [],
                "auto_pass_notes": [],
                "stats": {},
                "stage_status": {
                    "delta": "failed",
                    "validation": "skipped",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }
        
        # 1. 计算合并后的 JSON (用于校验和快照)
        merged, stats = self._merge_memory_delta(prev_memory, delta, replace_timeline=replace_timeline)
        candidate_json = self._postprocess_memory_layers(
            json.dumps(merged, ensure_ascii=False), prev_memory_json=prev_memory
        )
        
        # 2. 校验
        validation = self._validate_memory_payload(
            candidate_json,
            prev_memory,
            delta=delta,
            db=db if isinstance(db, Session) else None,
            novel_id=novel.id if db else None,
        )
        if db:
            db_validation = self._validate_memory_with_db(db, novel.id, delta, candidate_json)
            validation = self._merge_validation_results(validation, db_validation)

        blocking_errors = validation["blocking_errors"]
        warnings = validation["warnings"]
        auto_pass_notes = validation["auto_pass_notes"]

        if blocking_errors:
            return {
                "ok": False,
                "status": "blocked",
                "payload_json": prev_memory,
                "candidate_json": candidate_json,
                "errors": blocking_errors,
                "blocking_errors": blocking_errors,
                "warnings": warnings,
                "auto_pass_notes": auto_pass_notes,
                "stats": stats,
                "delta": delta,
                "stage_status": {
                    "delta": "ok",
                    "validation": "blocked",
                    "norm": "skipped",
                    "snapshot": "skipped",
                },
            }

        # 3. 如果没有 blocking_errors 且有 db，则执行规范化表更新
        new_version = 0
        norm_status = "skipped"
        snapshot_status = "skipped" if skip_snapshot else "pending"
        if db and not blocking_errors:
            try:
                with db.begin_nested():
                    new_version = self._get_latest_memory_version(db, novel.id) + 1
                    db_stats = self._upsert_normalized_memory_from_delta(
                        db,
                        novel.id,
                        delta,
                        new_version,
                        replace_timeline=replace_timeline,
                        chapters_summary=chapters_summary,
                    )
                    # 合并统计信息
                    for k, v in db_stats.items():
                        stats[k] = max(stats.get(k, 0), v)
                    norm_status = "ok"
                    
                    # 确保大纲表存在
                    from app.models.novel_memory_norm import NovelMemoryNormOutline
                    outline = db.get(NovelMemoryNormOutline, novel.id)
                    if not outline:
                        outline = NovelMemoryNormOutline(
                            novel_id=novel.id,
                            memory_version=new_version,
                            main_plot=novel.intro or "",
                        )
                        db.add(outline)
                    else:
                        outline.memory_version = new_version

                    if not skip_snapshot:
                        snap_ver = sync_json_snapshot_from_normalized(
                            db, novel.id, summary="规范化存储自动快照（batch_sync/incremental）"
                        )
                        new_version = snap_ver
                        snapshot_status = "ok"
                    else:
                        snapshot_status = "skipped"
                
                db.flush()
                
                if not skip_snapshot:
                    latest_row = (
                        db.query(NovelMemory)
                        .filter(NovelMemory.novel_id == novel.id)
                        .order_by(NovelMemory.version.desc())
                        .first()
                    )
                    if latest_row and latest_row.payload_json:
                        candidate_json = latest_row.payload_json
            except Exception as e:
                logger.exception("Failed to update normalized memory tables (sync savepoint): %s", e)
                return {
                    "ok": False,
                    "status": "failed",
                    "error": f"更新规范化表失败: {e}",
                    "payload_json": prev_memory,
                    "candidate_json": candidate_json,
                    "errors": [f"更新规范化表失败：{e}"],
                    "blocking_errors": [],
                    "warnings": warnings,
                    "auto_pass_notes": auto_pass_notes,
                    "stats": stats,
                    "delta": delta,
                    "stage_status": {
                        "delta": "ok",
                        "validation": "ok",
                        "norm": "failed",
                        "snapshot": "failed" if not skip_snapshot else "skipped",
                    },
                }
        
        return {
            "ok": True,
            "status": "warning" if warnings else "ok",
            "payload_json": candidate_json,
            "candidate_json": candidate_json,
            "errors": [],
            "blocking_errors": [],
            "warnings": warnings,
            "auto_pass_notes": auto_pass_notes,
            "stats": stats,
            "delta": delta,
            "version": new_version,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if warnings else "ok",
                "norm": norm_status,
                "snapshot": snapshot_status,
            },
        }

    async def refresh_memory_from_chapters(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """刷新记忆，采用增量抽取 + 代码合并。"""
        batch_chars = settings.novel_memory_refresh_batch_chars
        summary_len = len(chapters_summary or "")
        logger.info(
            "refresh_memory start | summary_len=%d batch_chars=%d",
            summary_len,
            batch_chars,
        )
        current_memory = prev_memory
        total_stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
        }
        collected_warnings: list[str] = []
        collected_auto_pass_notes: list[str] = []
        batch_num = 0
        pos = 0
        while pos < summary_len:
            batch_num += 1
            end = summary_len if batch_chars <= 0 else min(pos + batch_chars, summary_len)
            if batch_chars > 0 and end < summary_len:
                boundary = chapters_summary.rfind("\n\n第", pos, end)
                if boundary > pos + batch_chars // 2:
                    end = boundary
            batch_summary = chapters_summary[pos:end].strip()
            if not batch_summary:
                pos = end
                continue
            
            # 解析该批次包含的章节号，用于进度显示
            chapter_nos = sorted([int(n) for n in re.findall(r"第(\d+)章", batch_summary)])
            ch_info = f"第 {chapter_nos[0]}-{chapter_nos[-1]} 章" if len(chapter_nos) > 1 else (f"第 {chapter_nos[0]} 章" if chapter_nos else "未知章节")

            is_last_batch = (end >= summary_len)
            try:
                result = await self._apply_memory_delta_batch(
                    novel,
                    batch_summary,
                    current_memory,
                    db=db,
                    replace_timeline=replace_timeline,
                    skip_snapshot=not is_last_batch,
                )
                if not result["ok"]:
                    result["batch"] = batch_num
                    return result
                
                # 实时持久化：每批次成功后立即提交
                if db:
                    db.commit()
                    logger.info("refresh_memory (async) batch commit success | batch=%d | chapters=%s", batch_num, ch_info)
                    if progress_callback:
                        progress_callback(batch_num, ch_info, result.get("stats"))

                current_memory = result["payload_json"]
                collected_warnings.extend(_dedupe_str_list(result.get("warnings", [])))
                collected_auto_pass_notes.extend(_dedupe_str_list(result.get("auto_pass_notes", [])))
                for key in total_stats:
                    total_stats[key] += int(result.get("stats", {}).get(key, 0))
            except Exception as e:
                if db:
                    db.rollback()
                logger.exception("refresh_memory (async) batch failed | batch=%d", batch_num)
                return {"ok": False, "error": f"批次 {batch_num} ({ch_info}) 执行异常: {e}", "batch": batch_num}
            pos = end
        
        out: dict[str, Any] = {
            "ok": True,
            "status": "warning" if collected_warnings else "ok",
            "payload_json": current_memory,
            "candidate_json": current_memory,
            "errors": [],
            "blocking_errors": [],
            "warnings": _dedupe_str_list(collected_warnings),
            "auto_pass_notes": _dedupe_str_list(collected_auto_pass_notes),
            "stats": total_stats,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if collected_warnings else "ok",
                "norm": "ok" if db else "skipped",
                "snapshot": "ok" if db else "skipped",
            },
        }
        if db:
            out["version"] = self._get_latest_memory_version(db, novel.id)
        return out

    def refresh_memory_from_chapters_sync(
        self,
        novel: Novel,
        chapters_summary: str,
        prev_memory: str,
        db: Any = None,
        replace_timeline: bool = False,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """同步版本的记忆刷新，采用增量抽取 + 代码合并。"""
        # 不再根据 MD5 跳过，确保每一章都经过 LLM 重新扫描提取
        active_summary = chapters_summary.strip()
        
        if not active_summary:
            return {
                "ok": True,
                "status": "ok",
                "payload_json": prev_memory,
                "candidate_json": prev_memory,
                "errors": [],
                "blocking_errors": [],
                "warnings": [],
                "auto_pass_notes": ["无需更新：章节摘要为空"],
                "stats": {},
            }

        batch_chars = settings.novel_memory_refresh_batch_chars
        summary_len = len(active_summary)
        current_memory = prev_memory
        total_stats = {
            "canonical_entries": 0,
            "open_plots_added": 0,
            "open_plots_resolved": 0,
            "characters_updated": 0,
        }
        collected_warnings: list[str] = []
        collected_auto_pass_notes: list[str] = []
            
        batch_num = 0
        pos = 0
        while pos < summary_len:
            batch_num += 1
            end = summary_len if batch_chars <= 0 else min(pos + batch_chars, summary_len)
            if batch_chars > 0 and end < summary_len:
                # 寻找章节标题标记作为物理切分点，确保章节完整性
                boundary = active_summary.find("\n\n第", min(pos + batch_chars // 2, summary_len))
                if boundary != -1 and boundary < pos + batch_chars * 1.5:
                    end = boundary
            
            batch_summary = active_summary[pos:end].strip()
            if not batch_summary:
                pos = end
                continue
            
            # 解析该批次包含的章节号，用于进度显示
            chapter_nos = sorted([int(n) for n in re.findall(r"第(\d+)章", batch_summary)])
            ch_info = f"第 {chapter_nos[0]}-{chapter_nos[-1]} 章" if len(chapter_nos) > 1 else (f"第 {chapter_nos[0]} 章" if chapter_nos else "未知章节")

            # 如果还有下一批，则跳过快照生成，只更新规范化表
            is_last_batch = (end >= summary_len)
            try:
                result = self._apply_memory_delta_batch_sync(
                    novel,
                    batch_summary,
                    current_memory,
                    db=db,
                    replace_timeline=replace_timeline,
                    skip_snapshot=not is_last_batch,
                )
                if not result["ok"]:
                    result["batch"] = batch_num
                    return result
                
                # 实时持久化：每批次成功后立即提交
                if db:
                    db.commit()
                    logger.info("refresh_memory batch commit success | batch=%d | chapters=%s", batch_num, ch_info)
                    if progress_callback:
                        progress_callback(batch_num, ch_info, result.get("stats"))

                current_memory = result["payload_json"]
                collected_warnings.extend(_dedupe_str_list(result.get("warnings", [])))
                collected_auto_pass_notes.extend(_dedupe_str_list(result.get("auto_pass_notes", [])))
                for key in total_stats:
                    total_stats[key] += int(result.get("stats", {}).get(key, 0))
            except Exception as e:
                if db:
                    db.rollback()
                logger.exception("refresh_memory batch failed | batch=%d", batch_num)
                return {"ok": False, "error": f"批次 {batch_num} ({ch_info}) 执行异常: {e}", "batch": batch_num}
            
            pos = end
        
        out_sync: dict[str, Any] = {
            "ok": True,
            "status": "warning" if collected_warnings else "ok",
            "payload_json": current_memory,
            "candidate_json": current_memory,
            "errors": [],
            "blocking_errors": [],
            "warnings": _dedupe_str_list(collected_warnings),
            "auto_pass_notes": _dedupe_str_list(collected_auto_pass_notes),
            "stats": total_stats,
            "stage_status": {
                "delta": "ok",
                "validation": "warning" if collected_warnings else "ok",
                "norm": "ok" if db else "skipped",
                "snapshot": "ok" if db else "skipped",
            },
        }
        if db:
            out_sync["version"] = self._get_latest_memory_version(db, novel.id)
        return out_sync
        
        out_sync: dict[str, Any] = {
            "ok": True,
            "status": "warning" if collected_warnings else "ok",
            "payload_json": current_memory,
            "candidate_json": current_memory,
            "errors": [],
            "blocking_errors": [],
            "warnings": _dedupe_str_list(collected_warnings),
            "auto_pass_notes": _dedupe_str_list(collected_auto_pass_notes),
            "stats": total_stats,
        }
        if db:
            out_sync["version"] = self._get_latest_memory_version(db, novel.id)
        return out_sync

    def consolidate_memory_archive_sync(
        self,
        novel: Novel,
        db: Any,
    ) -> dict[str, Any]:
        """
        将较早章节的 key_facts 压缩并入 outline.timeline_archive_json，
        并裁剪过久章节的 key_facts，降低 token 与噪声。
        """
        novel_id = novel.id
        outline = db.get(NovelMemoryNormOutline, novel_id)
        if not outline:
            return {"ok": False, "reason": "no_outline"}
        hot_n = max(1, int(settings.novel_timeline_hot_n))
        rows = (
            db.query(NovelMemoryNormChapter)
            .filter(NovelMemoryNormChapter.novel_id == novel_id)
            .order_by(NovelMemoryNormChapter.chapter_no.asc())
            .all()
        )
        if len(rows) <= hot_n + 3:
            return {"ok": True, "skipped": True, "reason": "too_few_chapters"}
        max_no = max(r.chapter_no for r in rows)
        cutoff = max_no - hot_n
        old_rows = [r for r in rows if r.chapter_no <= cutoff]
        facts: list[str] = []
        for r in old_rows:
            kf = json.loads(r.key_facts_json or "[]")
            if isinstance(kf, list):
                facts.extend([str(x).strip() for x in kf if str(x).strip()])
        if not facts:
            return {"ok": True, "skipped": True, "reason": "no_facts"}
        irreversible = [fact for fact in facts if is_irreversible_fact(fact)]
        reversible = [fact for fact in facts if fact not in irreversible]
        facts = [*irreversible[:150], *reversible[:100]]
        router = self._router(db=db)
        sys = (
            "你是长篇连载编辑。将下列「早期章节关键事实」压缩为 3～12 条阶段性摘要短句，"
            "每条独立一行，不要编号，不要编造新事实，可合并同义表述。"
        )
        user = "\n".join(facts[:200])
        raw = router.chat_text_sync(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.25,
            web_search=False,
            timeout=180.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        bullets = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()][:16]
        arch = json.loads(outline.timeline_archive_json or "[]")
        if not isinstance(arch, list):
            arch = []
        merged = _dedupe_str_list([*arch, *bullets])[-48:]
        outline.timeline_archive_json = json.dumps(merged, ensure_ascii=False)
        trimmed = 0
        for r in old_rows:
            kf = json.loads(r.key_facts_json or "[]")
            if isinstance(kf, list) and len(kf) > 2:
                r.key_facts_json = json.dumps(kf[-2:], ensure_ascii=False)
                trimmed += 1
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        try:
            sync_json_snapshot_from_normalized(db, novel_id, summary="记忆压缩后同步快照")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "consolidate_memory_archive_sync: snapshot sync failed | novel_id=%s",
                novel_id,
            )
        return {
            "ok": True,
            "skipped": False,
            "archive_lines_added": len(bullets),
            "chapters_trimmed": trimmed,
        }

    def audit_chapter_against_constraints_sync(
        self,
        novel: Novel,
        chapter_text: str,
        db: Any,
    ) -> dict[str, Any]:
        """
        轻量 LLM 审计：正文是否违反规范化记忆中的 forbidden_constraints。
        """
        if not settings.novel_setting_audit_on_approve:
            return {"ok": True, "violations": [], "skipped": True}
        outline = db.get(NovelMemoryNormOutline, novel.id)
        if not outline:
            return {"ok": True, "violations": [], "skipped": True}
        try:
            fc = json.loads(getattr(outline, "forbidden_constraints_json", None) or "[]")
        except json.JSONDecodeError:
            fc = []
        if not isinstance(fc, list) or not fc:
            return {"ok": True, "violations": [], "skipped": True}
        router = self._router(db=db)
        sys = (
            "你是小说设定审计员。只输出一个 JSON 对象，不要 Markdown。"
            '格式：{"violations":["..."]}；violations 列出正文明确违反的禁止项，无则 []。'
        )
        user = (
            "【禁止项】\n"
            f"{json.dumps(fc, ensure_ascii=False)}\n\n"
            "【待审计正文】\n"
            f"{(chapter_text or '')[:14000]}"
        )
        raw = router.chat_text_sync(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.15,
            web_search=False,
            timeout=180.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = self._parse_refresh_memory_response(raw)
        v = parsed.get("violations") if isinstance(parsed, dict) else []
        if not isinstance(v, list):
            v = []
        violations = [str(x).strip() for x in v if str(x).strip()]
        return {"ok": len(violations) == 0, "violations": violations}

    async def propose_memory_update_from_chapter(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        chapter_title: str,
        chapter_text: str,
        prev_memory: str,
        db: Any = None,
    ) -> dict[str, Any]:
        chapter_blob = f"第{chapter_no}章《{chapter_title or f'第{chapter_no}章'}》\n{chapter_text}"
        return await self._apply_memory_delta_batch(novel, chapter_blob, prev_memory, db=db)

    def propose_memory_update_from_chapter_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        chapter_title: str,
        chapter_text: str,
        prev_memory: str,
        db: Any = None,
    ) -> dict[str, Any]:
        chapter_blob = f"第{chapter_no}章《{chapter_title or f'第{chapter_no}章'}》\n{chapter_text}"
        return self._apply_memory_delta_batch_sync(novel, chapter_blob, prev_memory, db=db)

    def calibrate_memory_from_chapters_sync(
        self,
        db: Session,
        novel: Novel,
        *,
        chapter_window: int = 10,
    ) -> dict[str, Any]:
        """每隔 N 章对热层记忆做一次全量校准，修正 LLM 累积误差。

        逻辑：
        1. 取最近 chapter_window 章已审定章节正文
        2. 取当前热层记忆 JSON
        3. 让 LLM 对比两者，输出修正增量（只含差异）
        4. 通过 _merge_memory_delta 合并
        5. 校验 + 规范化表更新 + 快照同步
        """
        from app.models.novel import Chapter, NovelMemory
        from app.services.novel_repo import latest_memory_json

        if settings.novel_memory_calibration_interval <= 0:
            return {"ok": True, "skipped": True, "reason": "calibration_disabled"}

        # 1. 取最近 N 章已审定章节
        chapters = (
            db.query(Chapter)
            .filter(Chapter.novel_id == novel.id, Chapter.status == "approved")
            .order_by(Chapter.chapter_no.desc())
            .limit(chapter_window)
            .all()
        )
        if len(chapters) < 3:
            return {"ok": True, "skipped": True, "reason": "too_few_chapters"}

        chapters = sorted(chapters, key=lambda c: c.chapter_no)
        chapters_summary_parts = []
        for ch in chapters:
            title = ch.title or f"第{ch.chapter_no}章"
            # 截取每章前 4000 字避免上下文溢出
            text = (ch.content or "")[:4000]
            chapters_summary_parts.append(
                f"第{ch.chapter_no}章《{title}》\n{text}"
            )
        chapters_blob = "\n\n---\n\n".join(chapters_summary_parts)

        # 2. 取当前热层记忆
        prev_memory = latest_memory_json(db, novel.id)

        # 3. 构建校准 prompt
        router = self._router(db=db)
        compact_prev = build_hot_memory_for_prompt(
            prev_memory,
            timeline_hot_n=settings.novel_timeline_hot_n,
            open_plots_hot_max=settings.novel_open_plots_hot_max,
            characters_hot_max=settings.novel_characters_hot_max,
        )
        prev_open_plots = format_open_plots_block(prev_memory)

        sys = (
            "你是小说记忆校准器。你的任务是比较「当前热层记忆」和「最近章节实际内容」，"
            "找出两者之间的差异并输出修正增量。\n"
            "常见差异类型：\n"
            "1. 记忆中有但章节中未体现或已矛盾的人物状态/关系\n"
            "2. 章节中有但记忆中遗漏的人物、事件、线索\n"
            "3. 时间线条目中的关键事实与章节实际内容不符\n"
            "4. 已收束的线索仍标记为 open_plots\n"
            "5. 未收束的线索被误标为已收束\n"
            "输出严格 JSON 对象，字段与记忆增量格式一致：\n"
            "facts_added[], facts_updated[], open_plots_added[], open_plots_resolved[],\n"
            "canonical_entries[], characters_added[], characters_updated[], characters_inactivated[],\n"
            "relations_added[], relations_updated[], relations_inactivated[],\n"
            "inventory_changed{added[],removed[]}, skills_changed{added[],updated[],removed[]},\n"
            "pets_changed{added[],updated[],removed[]}, conflicts_detected[],\n"
            "forbidden_constraints_added[], ids_to_remove[], entity_influence_updates[]。\n"
            "只输出确实需要修正的部分，没有差异的字段输出空数组。"
            "不要重写整份记忆，只输出修正增量。"
        )
        user = (
            f"【当前热层记忆（含 ID）】\n{compact_prev}\n\n"
            f"{prev_open_plots}\n\n"
            f"【最近 {len(chapters)} 章实际内容】\n{chapters_blob}\n\n"
            "任务：对比当前记忆与实际章节内容，输出需要修正的增量。\n"
            "重点关注：遗漏的人物、矛盾的状态、错误的时间线、过期的线索标记。"
        )

        try:
            raw = self._chat_text_sync_with_timeout_retry(
                router=router,
                operation="memory_calibration",
                novel_id=novel.id,
                messages=[
                    {"role": "system", "content": sys},
                    {"role": "user", "content": user},
                ],
                temperature=0.15,
                timeout=settings.novel_memory_refresh_batch_timeout,
                web_search=self._novel_web_search(db, flow="memory_refresh"),
                max_tokens=settings.novel_memory_delta_max_tokens,
                response_format={"type": "json_object"},
                **self._bill_kw(db, self._billing_user_id),
            )
        except Exception as e:
            logger.warning(
                "memory_calibration_llm_failed | novel_id=%s error=%s",
                novel.id, e,
            )
            return {"ok": False, "error": str(e), "skipped": False}

        delta = self._parse_refresh_memory_response(raw)
        if not delta:
            delta = self._repair_refresh_memory_response_sync(
                router=router, raw=raw, db=db,
            )
        if not delta:
            return {
                "ok": False,
                "error": "LLM 未返回合法的校准 JSON",
                "skipped": False,
            }

        # 检查是否有实际修正
        has_changes = any(
            isinstance(delta.get(k), list) and len(delta.get(k)) > 0
            for k in [
                "facts_added", "facts_updated", "open_plots_added", "open_plots_resolved",
                "canonical_entries", "characters_added", "characters_updated",
                "characters_inactivated", "relations_added", "relations_updated",
                "relations_inactivated", "ids_to_remove",
            ]
        )
        if not has_changes:
            return {"ok": True, "skipped": False, "changes": 0, "message": "记忆与章节一致，无需修正"}

        # 4. 合并修正增量
        merged, stats = self._merge_memory_delta(prev_memory, delta)
        candidate_json = self._postprocess_memory_layers(
            json.dumps(merged, ensure_ascii=False), prev_memory_json=prev_memory
        )

        # 5. 校验
        validation = self._validate_memory_payload(
            candidate_json, prev_memory, delta=delta, db=db, novel_id=novel.id,
        )
        db_validation = self._validate_memory_with_db(db, novel.id, delta, candidate_json)
        validation = self._merge_validation_results(validation, db_validation)

        if validation["blocking_errors"]:
            return {
                "ok": False,
                "error": "校准增量被校验拦截",
                "blocking_errors": validation["blocking_errors"],
                "skipped": False,
            }

        # 6. 写入规范化表 + 快照
        try:
            with db.begin_nested():
                new_version = self._get_latest_memory_version(db, novel.id) + 1
                self._upsert_normalized_memory_from_delta(
                    db, novel.id, delta, new_version, replace_timeline=False,
                )
                # 写入快照
                mem_row = NovelMemory(
                    novel_id=novel.id,
                    version=new_version,
                    payload_json=candidate_json,
                    source="calibration",
                )
                db.add(mem_row)
                db.flush()
        except Exception as e:
            logger.warning("memory_calibration_write_failed | novel_id=%s error=%s", novel.id, e)
            return {"ok": False, "error": str(e), "skipped": False}

        # 7. 同步 novel.memory_json
        novel.memory_json = candidate_json
        db.flush()

        logger.info(
            "memory_calibration_done | novel_id=%s stats=%s",
            novel.id, stats,
        )
        return {"ok": True, "skipped": False, "stats": stats, "changes": sum(stats.values())}

    async def revise_chapter(
        self,
        novel: Novel,
        chapter: Chapter,
        memory_json: str,
        feedback_bodies: list[str],
        user_prompt: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return await router.chat_text(
            messages=self._budget_chapter_messages(
                _revise_chapter_messages(
                    novel, chapter, memory_json, feedback_bodies, user_prompt, db
                )
            ),
            temperature=0.65,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )

    def revise_chapter_sync(
        self,
        novel: Novel,
        chapter: Chapter,
        memory_json: str,
        feedback_bodies: list[str],
        user_prompt: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db)
        return router.chat_text_sync(
            messages=self._budget_chapter_messages(
                _revise_chapter_messages(
                    novel, chapter, memory_json, feedback_bodies, user_prompt, db
                )
            ),
            temperature=0.65,
            timeout=600.0,
            web_search=self._novel_web_search(db, flow="default"),
            **self._bill_kw(db, self._billing_user_id),
        )

    # ─── Draw Card (抽卡) Options ─────────────────────────────────────────────

