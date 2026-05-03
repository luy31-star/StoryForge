from __future__ import annotations

from typing import Any

from json_repair import loads as json_repair_loads

from app.services.novel_llm_memory_service import NovelLLMMemoryService
from app.services.novel_llm_utils import _safe_json_dict


class NovelLLMDrawCardService(NovelLLMMemoryService):
    """抽卡（世界观/主角/金手指）能力。"""

    def draw_world_options_sync(
        self,
        styles: list[str],
        subjects: list[str],
        backgrounds: list[str],
        moods: list[str],
        db: Any = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是一个创意设计助手。根据用户需求生成多样化的选项方案。只输出JSON，不要Markdown，不要解释。"
        )
        user_prompt = f"""你是一个创意世界观设计师。请根据以下标签生成6个风格迥异的世界观选项。

标签：{styles} / {subjects} / {backgrounds} / {moods}

要求：
- 每个选项要独特，风格差异化明显
- 每个选项必须包含中文
- 返回严格JSON格式（不要Markdown围栏，不要解释）：
{{
  "options": [
    {{
      "world_type": "社会结构/科技水平/文明形态（如：修仙宗门文明、赛博朋克都市、古希腊城邦等）",
      "main_conflict": "这个世界最核心的冲突是什么（用一句话描述）",
      "social_structure": "社会阶层与主要势力分布（用2-3句话描述）",
      "cultural_features": "文化/宗教/风俗特点（用2-3句话描述，越有特色越好）",
      "unique_rules": "这个世界的2-3条特殊规则或限制（这些规则要有趣味性，并深刻影响剧情走向）",
      "visual_atmosphere": "视觉/氛围关键词（3-5个词，帮助读者快速建立画面感）"
    }},
    ... (共6个选项)
  ]
}}"""
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="draw_world_options",
            novel_id="-",
            chapter_no=None,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            timeout=120.0,
            max_retries=1,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _safe_json_dict(raw)
        if not parsed:
            try:
                repaired = json_repair_loads(raw or "{}")
                parsed = repaired if isinstance(repaired, dict) else {}
            except Exception:
                parsed = {}
        options = parsed.get("options")
        if isinstance(options, list):
            parsed["options"] = options[:6]
        if not parsed.get("options"):
            return {"options": [], "error": "解析失败"}
        return parsed

    def draw_protagonist_options_sync(
        self,
        styles: list[str],
        subjects: list[str],
        protagonist_count: int = 2,
        selected_world: dict[str, Any] | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是一个创意设计助手。根据用户需求生成多样化的选项方案。只输出JSON，不要Markdown，不要解释。"
        )
        
        world_context = ""
        if selected_world:
            world_context = f"\n已确定的世界观背景：\n类型：{selected_world.get('world_type', '')}\n冲突：{selected_world.get('main_conflict', '')}\n特色：{selected_world.get('cultural_features', '')}\n请确保主角设定符合以上世界观逻辑，不要生成与世界观冲突的设定（比如修仙世界出现赛博黑客）。\n"

        user_prompt = f"""你是一个角色设定专家。请根据以下标签为主角生成6个风格各异的设定选项。

标签：{styles} / {subjects}
主角数量：{protagonist_count}{world_context}

要求：
- 每个主角设定要独特，避免同质化
- 每个主角要有明确的社会身份（不能都是"普通学生"或"废柴"）
- 每个选项必须包含中文
- 返回严格JSON格式（不要Markdown围栏，不要解释）：
{{
  "options": [
    {{
      "name": "主角名字（2-4个字，有辨识度）",
      "role_identity": "主角的社会身份+当前处境（用一句话，如：没落世家的废物少主，身负血仇但修为停滞）",
      "core_desire": "主角最核心的欲望/目标（用一句话，要有强烈情感张力）",
      "personality_traits": ["性格关键词1", "性格关键词2", "性格关键词3", "性格关键词4"],
      "starting_ability": "主角初始具备的能力或资源（用2-3句话描述，要有独特性且开局就能用）",
      "backstory_hint": "主角背景故事的关键线索（用2-3句话，给后续剧情发展留足空间）",
      "secret_identity": "主角隐藏的身份或秘密（用1-2句话，可以是悬念钩子）"
    }},
    ... (共6个选项)
  ]
}}"""
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="draw_protagonist_options",
            novel_id="-",
            chapter_no=None,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            timeout=120.0,
            max_retries=1,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _safe_json_dict(raw)
        if not parsed:
            try:
                repaired = json_repair_loads(raw or "{}")
                parsed = repaired if isinstance(repaired, dict) else {}
            except Exception:
                parsed = {}
        options = parsed.get("options")
        if isinstance(options, list):
            parsed["options"] = options[:6]
        if not parsed.get("options"):
            return {"options": [], "error": "解析失败"}
        return parsed

    def draw_cheat_options_sync(
        self,
        styles: list[str],
        subjects: list[str],
        plot_type: str = "",
        selected_world: dict[str, Any] | None = None,
        selected_protagonist: dict[str, Any] | None = None,
        db: Any = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是一个创意设计助手。根据用户需求生成多样化的选项方案。只输出JSON，不要Markdown，不要解释。"
        )

        world_context = ""
        if selected_world:
            world_context = f"已确定的世界观：\n类型：{selected_world.get('world_type', '')}\n"

        protagonist_context = ""
        if selected_protagonist:
            protagonist_context = f"已确定的主角：\n姓名：{selected_protagonist.get('name', '')}\n身份：{selected_protagonist.get('role_identity', '')}\n初始能力：{selected_protagonist.get('starting_ability', '')}\n"

        context_block = ""
        if world_context or protagonist_context:
            context_block = f"\n背景约束：\n{world_context}{protagonist_context}请确保金手指/外挂设定完全贴合上述世界观逻辑与主角现状，不显得突兀。\n"

        user_prompt = f"""你是一个网文金手指设计专家。请根据以下标签生成6个风格各异的金手指/外挂设定选项。

标签：{styles} / {subjects}
题材类型：{plot_type}{context_block}

要求：
- 每个金手指要有独特性，避免"最强系统"这类泛泛设定
- 要有具体的机制描述，不能只是名字
- 每个选项必须包含中文
- 返回严格JSON格式（不要Markdown围栏，不要解释）：
{{
  "options": [
    {{
      "cheat_name": "金手指名称（2-8个字，要有辨识度和吸引力）",
      "cheat_type": "类型：系统/异能/传承/道具/契约/知识/其他",
      "power_level": "强弱定位：初生/成长/巅峰/无解（选择最合适的）",
      "core_mechanic": "核心机制（用2-4句话描述这个能力怎么运作，要有独特性和趣味性）",
      "growth_limit": "成长限制或代价（用2-3句话描述，要有合理性并为剧情制造冲突）",
      "initial_benefit": "主角获得的初始收益（用1-2句话，要具体且开局就能体现效果）",
      "hidden_twist": "这个金手指隐藏的秘密或隐患（用1-2句话，可作为后续剧情伏笔）"
    }},
    ... (共6个选项)
  ]
}}"""
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="draw_cheat_options",
            novel_id="-",
            chapter_no=None,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            timeout=120.0,
            max_retries=1,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _safe_json_dict(raw)
        if not parsed:
            try:
                repaired = json_repair_loads(raw or "{}")
                parsed = repaired if isinstance(repaired, dict) else {}
            except Exception:
                parsed = {}
        options = parsed.get("options")
        if isinstance(options, list):
            parsed["options"] = options[:6]
        if not parsed.get("options"):
            return {"options": [], "error": "解析失败"}
        return parsed
