import json
from collections.abc import AsyncIterator
from typing import Any
from app.models.novel import Novel
from app.core.config import settings
from app.services.novel_llm_utils import _ANTI_AI_FLAVOR_BLOCK, _chapter_messages

async def stream_chapter_plan(
    llm_service,
    novel: Novel,
    volume_no: int,
    volume_title: str,
    chapter_no: int,
    memory_json: str,
    prev_batch_context: str = "",
    cross_volume_tail_context: str = "",
    db: Any = None,
) -> AsyncIterator[dict[str, str]]:
    router = llm_service._router(db=db, model=getattr(novel, "plan_model", None))
    batch_chapter_count = 1
    anti_repetition_block = llm_service._get_anti_repetition_constraints(novel, batch_chapter_count)
    
    sys = (
        "你是网络小说总策划。请为指定章节区间生成「章计划」，用于后续逐章写作。"
        "你必须严格输出一个 JSON 对象，不要输出任何解释性文字、不要 Markdown、不要代码块围栏。"
        "输出必须以 { 开头，以 } 结尾；除 JSON 外不得包含任何字符。"
        "【JSON 语法硬要求】所有字符串值内禁止直接换行；若需分段请使用 \\n 转义。"
        "剧情文本中避免使用未转义的英文双引号；可用中文「」或单引号代替。"
        "【核心原则】剧情必须递进，禁止原地踏步式的重复！每一章都必须推动故事前进，不得重复已有的冲突模式。\n"
        f"{_ANTI_AI_FLAVOR_BLOCK}"
    )

    cross_volume_hint = ""
    if cross_volume_tail_context.strip():
        cross_volume_hint = (
            "\n\n【跨卷衔接：上一卷末（须承接，与下列事实无矛盾）】\n"
            f"{cross_volume_tail_context.strip()}\n"
            "要求：本批为当前卷起始章计划，须在人物状态、悬念与未结冲突上自然接续上一卷末；"
            "不得重置剧情线或无视上文已发生的事实；volume_summary 须点出与上一卷的承接关系。\n"
        )

    continuity_hint = ""
    if prev_batch_context:
        continuity_hint = (
            "\n\n【前批次剧情衔接（必须承接）】\n"
            f"{prev_batch_context}\n"
            "要求：本章计划必须自然承接前批次的剧情走向、人物状态和未完结线索；"
            "open_plots_intent_added 若在前批次已出现，本章不得重复声明（除非是新的分支）。\n"
        )

    user = (
        f"【小说标题】{novel.title}\n"
        f"【卷信息】第{volume_no}卷《{volume_title}》，本批次章节范围：第{chapter_no}章-第{chapter_no}章\n\n"
        f"【框架 Markdown（摘要）】\n{(novel.framework_markdown or novel.background or '')[:8000]}\n\n"
        f"【框架 JSON】\n{novel.framework_json or '{}'}\n\n"
        f"【结构化记忆（open_plots/canonical_timeline 等）】\n{memory_json}\n"
        f"{cross_volume_hint}"
        f"{continuity_hint}"
        "【输出要求（严格 JSON）】\n"
        "{\n"
        '  "volume_title": string,\n'
        '  "volume_summary": string,\n'
        '  "chapters": [\n'
        "    {\n"
        '      "chapter_no": number,\n'
        '      "title": string,\n'
        '      "beats": {\n'
        '        "goal": string,\n'
        '        "conflict": string,\n'
        '        "turn": string,\n'
        '        "hook": string,\n'
        '        "plot_summary": string,\n'
        '        "stage_position": string,\n'
        '        "pacing_justification": string,\n'
        '        "expressive_brief": {\n'
        '          "pov_strategy": string,\n'
        '          "emotional_curve": string,\n'
        '          "sensory_focus": string,\n'
        '          "dialogue_strategy": string,\n'
        '          "scene_tempo": string,\n'
        '          "reveal_strategy": string\n'
        '        },\n'
        '        "progress_allowed": string 或 string[],\n'
        '        "must_not": string[],\n'
        '        "reserved_for_later": [ { "item": string, "not_before_chapter": number } ],\n'
        '        "scene_cards": [\n'
        '          {\n'
        '            "label": string,\n'
        '            "goal": string,\n'
        '            "conflict": string,\n'
        '            "content": string,\n'
        '            "outcome": string,\n'
        '            "emotion_beat": string,\n'
        '            "camera": string,\n'
        '            "dialogue_density": string,\n'
        '            "words": number\n'
        '          }\n'
        '        ]\n'
        "      },\n"
        '      "open_plots_intent_added": string[],\n'
        '      "open_plots_intent_resolved": string[]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "volume_summary：用 200～500 字写清本卷在本作中的位置、本卷核心矛盾、阶段目标、与前后卷的衔接、读者在本卷应获得的情绪曲线；"
        "避免空泛一句话，需分层（人物线/主线/副线/悬念）各至少一句。\n"
        "beats 字段说明：plot_summary 为本章剧情梗概（约 5～12 句，须写清场景转换、关键行动、信息边界、章末停笔点）；"
        "stage_position 用一两句说明本章在「当前大纲弧/本卷」中的位置（例如「第一弧约 15% 处、仅完成铺垫」）；"
        "pacing_justification 用一两句说明本章为何**不会**提前触发后续弧或更大阶段的核心事件（避免与 must_not 矛盾）；"
        "expressive_brief 必填，负责规定本章怎么写而不是写什么：至少写清 POV 站位、情绪推进、感官焦点、对白策略、场景节奏、信息揭示方式；"
        "progress_allowed 写明本章允许推进的内容；must_not 列出本章绝对不得出现的情节、能力觉醒、设定点名、剧透；"
        "reserved_for_later 列出须延后到指定章节号及之后才允许在正文成真或点名的条目（not_before_chapter 为全局章节号）；"
        "scene_cards 必填，按顺序拆成 2-4 个场景，每个场景除剧情内容外还要包含 emotion_beat / camera / dialogue_density，确保后续写作有表现抓手。\n\n"
        "【硬约束】\n"
        f"1) chapters 数组必须恰好包含 1 个对象（第 {chapter_no} 章）；\n"
        "2) 每章 beats 必须体现「只推进一个小节拍」（不要一章跨多个大事件）；\n"
        "3) 每章 open_plots_intent_resolved 最多 1 条（可以为空），避免清坑过猛导致快进；\n"
        "4) 若本批次非卷末，章末应自然过渡到下一章，但不得提前解决后续大事件；\n"
        "5) 必须通读【框架 JSON】中的 arcs、人物、金手指/能力、主线节点；若大纲写明某能力/身份/真相「第 N 章」才觉醒或揭露，"
        "则所有 chapter_no < N 的章，beats.must_not 必须包含对应的禁止描述（如不得觉醒、不得点名该能力真名、不得让配角知晓等），"
        "且 plot_summary/turn/hook 不得写到该事件的结果；\n"
        "6) 每章 plot_summary 仅允许写本章内发生的事，不得写到后续章的结局或后验信息；\n"
        "7) 输出前自检：若某章 plot_summary、turn 或 hook 与该章 must_not、或 reserved_for_later 中 not_before_chapter 大于该章 chapter_no 的条目冲突，必须改写该章直至一致；\n"
        "8) reserved_for_later 可为空数组；若框架无明确章节锚点，按 arcs 节拍合理分配 not_before_chapter，且与 must_not 一致；\n"
        "9) 每章必须填写 stage_position 与 pacing_justification，且与 plot_summary、must_not 一致；\n"
        "10) 若本批次章节落在框架 JSON 中某一弧的章节范围内，不得让本批次计划实质跨入下一弧的核心事件；\n"
        + (
            "11) 本批次若包含**全书第1章**（存在 chapter_no=1）：该章必须是「可入场的第1章」——"
            "plot_summary 须写清如何通过场景/对白/观察呈现：基本时空或环境、主角身份与当前处境、主线矛盾或故事契机的来由，"
            "使读者不依赖脑补即可理解谁、何处、因何进入当前局面；"
            "goal 与 conflict 须与上述交代自然衔接，不得写成无情境骨架的事件清单；"
            "must_not 须明确禁止缺乏铺垫的「莫名其妙」开场（例如未解释的多方混战、大段生造专名砸脸、读者尚不知人物关系就写终局式结果等）。\n"
            if chapter_no == 1
            else ""
        )
        + f"{anti_repetition_block}"
    )

    async for chunk in router.chat_text_stream(
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.55,
        web_search=llm_service._novel_web_search(db, flow="volume_plan"),
        timeout=settings.novel_volume_plan_batch_timeout,
        max_tokens=8192,
        **llm_service._bill_kw(db, llm_service._billing_user_id),
    ):
        yield chunk

async def stream_chapter_text(
    llm_service,
    novel: Novel,
    chapter_no: int,
    chapter_title_hint: str,
    memory_json: str,
    continuity_excerpt: str,
    recent_full_context: str = "",
    chapter_plan_hint: str = "",
    db: Any = None,
) -> AsyncIterator[dict[str, str]]:
    router = llm_service._router(model=getattr(novel, "chapter_model", None), db=db)
    messages = _chapter_messages(
        novel,
        chapter_no,
        chapter_title_hint,
        memory_json,
        continuity_excerpt,
        recent_full_context,
        chapter_plan_hint,
        db=db,
    )
    # _budget_chapter_messages
    budget = 12000
    if llm_service._messages_chars(messages) > budget:
        trimmed = messages[:]
        keep_chars = max(100, int((budget - 3000) / 2))
        for idx in [3, 5]:
            if idx < len(trimmed) and trimmed[idx].get("role") == "user":
                trimmed[idx]["content"] = llm_service._trim_text_block(trimmed[idx]["content"], keep_chars)
        if llm_service._messages_chars(trimmed) > budget:
            trimmed[1]["content"] = llm_service._trim_text_block(trimmed[1]["content"], budget - len(trimmed[0].get("content", "")) - 200)
        messages = trimmed
        
    async for chunk in router.chat_text_stream(
        messages=messages,
        temperature=0.85,
        web_search=llm_service._novel_web_search(db, flow="generate"),
        timeout=settings.novel_chapter_timeout,
        max_tokens=8192,
        **llm_service._bill_kw(db, llm_service._billing_user_id),
    ):
        yield chunk
