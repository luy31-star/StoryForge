from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from app.services.novel_llm_utils import *
from app.services.novel_llm_utils import (
    _notify_progress,
    _writing_style_block,
    _safe_json_dict,
    _sanitize_base_framework_payload,
    _trim_base_framework_markdown,
    _strip_last_fenced_block,
    _parse_framework_json_from_reply,
    _merge_framework_markdown_sections,
    _merge_framework_payloads,
    _build_prior_volumes_arcs_context_block,
    _merge_arcs_into_framework,
    _volume_plan_parse_llm_json_to_dict,
    _ANTI_AI_FLAVOR_BLOCK,
    _build_chapter_context_bundle,
)

class NovelLLMCoreService:
    """小说相关 302 Chat；默认智谱 GLM-4.7，可按配置开启联网搜索。"""

    def __init__(self, billing_user_id: str | None = None) -> None:
        # 与历史实现保持兼容：一致性修订/记忆刷新仍走 AI302Client（sync + async）
        self._client = AI302Client()
        self._billing_user_id = billing_user_id

    @staticmethod
    def _timeout_retry_attempts() -> int:
        return max(1, int(settings.novel_llm_timeout_retries) + 1)

    @staticmethod
    def _timeout_retry_backoff(attempt: int) -> float:
        base = max(0.0, float(settings.novel_llm_timeout_retry_backoff_seconds))
        return base * max(1, attempt)

    async def _chat_text_with_timeout_retry(
        self,
        *,
        router: LLMRouter,
        operation: str,
        novel_id: str,
        chapter_no: int | None = None,
        timeout: float,
        **kwargs: Any,
    ) -> str:
        attempts = self._timeout_retry_attempts()
        for attempt in range(1, attempts + 1):
            try:
                return await router.chat_text(timeout=timeout, **kwargs)
            except httpx.TimeoutException:
                logger.warning(
                    "llm timeout(async) | op=%s novel_id=%s chapter_no=%s attempt=%s/%s timeout=%.1fs provider=%s model=%s",
                    operation,
                    novel_id,
                    chapter_no,
                    attempt,
                    attempts,
                    timeout,
                    "ai302",
                    router.model or "-",
                )
                if attempt >= attempts:
                    raise
                await asyncio.sleep(self._timeout_retry_backoff(attempt))

    def _chat_text_sync_with_timeout_retry(
        self,
        *,
        router: LLMRouter,
        operation: str,
        novel_id: str,
        chapter_no: int | None = None,
        timeout: float,
        **kwargs: Any,
    ) -> str:
        attempts = self._timeout_retry_attempts()
        for attempt in range(1, attempts + 1):
            try:
                return router.chat_text_sync(timeout=timeout, **kwargs)
            except httpx.TimeoutException:
                logger.warning(
                    "llm timeout(sync) | op=%s novel_id=%s chapter_no=%s attempt=%s/%s timeout=%.1fs provider=%s model=%s",
                    operation,
                    novel_id,
                    chapter_no,
                    attempt,
                    attempts,
                    timeout,
                    "ai302",
                    router.model or "-",
                )
                if attempt >= attempts:
                    raise
                time.sleep(self._timeout_retry_backoff(attempt))

    @staticmethod
    def _bill_kw(db: Any, billing_user_id: str | None) -> dict[str, Any]:
        if not billing_user_id:
            return {}
        out: dict[str, Any] = {"billing_user_id": billing_user_id}
        if db is not None:
            out["billing_db"] = db
        return out

    def _router(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        db: Any = None,
    ) -> LLMRouter:
        # 仅支持 302.AI；ignore provider
        return LLMRouter(model=model, user_id=self._billing_user_id, db=db)

    def _novel_web_search(
        self,
        db: Any = None,
        *,
        flow: Literal[
            "default",
            "inspiration",
            "generate",
            "volume_plan",
            "memory_refresh",
        ] = "default",
    ) -> bool:
        fallback = (
            True if flow == "inspiration" else bool(settings.ai302_novel_web_search)
        )
        close_db = False
        use_db = db
        if use_db is None:
            use_db = SessionLocal()
            close_db = True
        try:
            cfg = get_runtime_web_search_config(use_db, user_id=self._billing_user_id)
            if flow == "inspiration":
                return bool(cfg.novel_inspiration_web_search)
            if flow == "generate":
                return bool(cfg.novel_generate_web_search)
            if flow == "volume_plan":
                return bool(cfg.novel_volume_plan_web_search)
            if flow == "memory_refresh":
                return bool(cfg.novel_memory_refresh_web_search)
            return bool(cfg.novel_web_search)
        except Exception:
            return fallback
        finally:
            if close_db and use_db is not None:
                use_db.close()

    @staticmethod
    def _messages_chars(messages: list[dict[str, str]]) -> int:
        return sum(len(m.get("content", "")) for m in messages)

    @staticmethod
    def _trim_text_block(block: str, max_chars: int) -> str:
        raw = str(block or "").strip()
        if max_chars <= 0 or len(raw) <= max_chars:
            return raw
        half = max_chars // 2
        if half < 80:
            return raw[-max_chars:]
        return raw[:half] + "\n…（中间已裁剪）…\n" + raw[-(max_chars - half - 14):]

    @classmethod
    def _budget_chapter_messages(
        cls,
        messages: list[dict[str, str]],
        *,
        budget: int | None = None,
    ) -> list[dict[str, str]]:
        if budget is None:
            budget = max(12000, int(settings.novel_prompt_char_budget))
        if cls._messages_chars(messages) <= budget:
            return messages

        trimmed = [dict(m) for m in messages]
        if len(trimmed) < 2:
            return trimmed
        user_text = trimmed[1].get("content", "")
        blocks = user_text.split("\n\n")
        lowered = [
            ("【最近已审定章节完整正文（增强衔接）】", 9000),
            ("【前文衔接摘录", 3200),
            ("【与本章最相关的记忆召回】", 2600),
            ("【冷层历史召回（按需）】", 1800),
            ("【过程章素材（用于降速但不拖沓）】", 1200),
        ]
        for marker, keep_chars in lowered:
            if cls._messages_chars(trimmed) <= budget:
                break
            for idx, block in enumerate(blocks):
                if block.startswith(marker):
                    blocks[idx] = cls._trim_text_block(block, keep_chars)
                    break
            trimmed[1]["content"] = "\n\n".join(blocks)

        if cls._messages_chars(trimmed) > budget:
            trimmed[1]["content"] = cls._trim_text_block(trimmed[1]["content"], budget - len(trimmed[0].get("content", "")) - 200)
        return trimmed

    async def inspiration_chat(self, messages: list[dict[str, str]], db: Any = None) -> str:
        """新建小说阶段：多轮对话 + 强制联网搜索，获取创作灵感。"""
        router = self._router(db=db)
        system = (
            "你是网络小说策划助手。请使用联网搜索能力，根据用户问题检索题材热点、类型套路、设定参考，"
            "并给出可执行的创作灵感。回答尽量结构化，可包含：题材方向、核心冲突、人设建议、世界观要点、文风提示。"
            "若用户希望填入表单，请在末段用简短列表对应：书名建议、简介要点、背景设定要点、文风关键词。"
        )
        out: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            out.append({"role": role, "content": m["content"]})
        return await router.chat_text(
            messages=out,
            temperature=0.75,
            web_search=self._novel_web_search(db, flow="inspiration"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )

    async def inspiration_chat_stream(
        self, messages: list[dict[str, str]], db: Any = None
    ) -> AsyncIterator[dict[str, str]]:
        router = self._router(db=db)
        system = (
            "你是网络小说策划助手。请使用联网搜索能力，根据用户问题检索题材热点、类型套路、设定参考，"
            "并给出可执行的创作灵感。回答尽量结构化，可包含：题材方向、核心冲突、人设建议、世界观要点、文风提示。"
            "若用户希望填入表单，请在末段用简短列表对应：书名建议、简介要点、背景设定要点、文风关键词。"
        )
        out: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            out.append({"role": role, "content": m["content"]})
        async for evt in router.chat_text_stream(
            messages=out,
            temperature=0.75,
            web_search=self._novel_web_search(db, flow="inspiration"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        ):
            yield evt

    async def chapter_context_chat(
        self,
        novel: Novel,
        *,
        memory_json: str,
        approved_chapters_summary: str,
        continuity_excerpt: str,
        messages: list[dict[str, str]],
        llm_provider: str | None = None,
        llm_model: str | None = None,
        db: Any = None,
    ) -> str:
        """章节侧问答：基于小说框架、记忆与已写章节上下文回答问题。"""
        router = self._router(provider=llm_provider, model=llm_model, db=db)
        bible = novel.framework_markdown[:6000] if novel.framework_markdown else novel.background
        fj_block = truncate_framework_json(effective_framework_json_for_prompt(db, novel), 4000)
        memory_blocks = _build_chapter_context_bundle(
            memory_json=memory_json,
            chapter_no=0,
            chapter_title_hint="",
            chapter_plan_hint="".join(m.get("content", "") for m in messages[-2:]),
            use_cold_recall=False,
            cold_recall_items=0,
            db=db,
            novel_id=novel.id,
        )
        sys = (
            "你是小说章节助手。请严格基于用户提供的小说上下文回答："
            "框架 Markdown、框架 JSON、结构化记忆、已写章节摘录。"
            "目标：帮助用户判断设定一致性、续写方向、伏笔回收、人物动机、节奏与冲突设计。"
            "若上下文中没有明确依据，请明确说明「当前信息不足」，并给出最小化假设选项。"
            "不要编造未提供的硬设定。回答尽量简洁、可执行。"
        )
        context_user = (
            f"【小说标题】{novel.title}\n\n"
            f"【框架 Markdown】\n{bible}\n\n"
            f"【框架 JSON（截断）】\n{fj_block}\n\n"
            f"{chr(10).join(memory_blocks)}\n\n"
            f"【已审定章节摘要（近段）】\n{approved_chapters_summary or '（暂无）'}\n\n"
            f"【连续性衔接摘录】\n{continuity_excerpt or '（暂无）'}"
        )
        out: list[dict[str, str]] = [
            {"role": "system", "content": sys},
            {"role": "user", "content": context_user},
        ]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            out.append({"role": role, "content": content})

        return await router.chat_text(
            messages=out,
            temperature=0.45,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )

    async def chapter_context_chat_stream(
        self,
        novel: Novel,
        *,
        memory_json: str,
        approved_chapters_summary: str,
        continuity_excerpt: str,
        messages: list[dict[str, str]],
        llm_provider: str | None = None,
        llm_model: str | None = None,
        db: Any = None,
    ) -> AsyncIterator[dict[str, str]]:
        router = self._router(provider=llm_provider, model=llm_model, db=db)
        bible = novel.framework_markdown[:6000] if novel.framework_markdown else novel.background
        fj_block = truncate_framework_json(effective_framework_json_for_prompt(db, novel), 4000)
        memory_blocks = _build_chapter_context_bundle(
            memory_json=memory_json,
            chapter_no=0,
            chapter_title_hint="",
            chapter_plan_hint="".join(m.get("content", "") for m in messages[-2:]),
            use_cold_recall=False,
            cold_recall_items=0,
            db=db,
            novel_id=novel.id,
        )
        sys = (
            "你是小说章节助手。请严格基于用户提供的小说上下文回答："
            "框架 Markdown、框架 JSON、结构化记忆、已写章节摘录。"
            "目标：帮助用户判断设定一致性、续写方向、伏笔回收、人物动机、节奏与冲突设计。"
            "若上下文中没有明确依据，请明确说明「当前信息不足」，并给出最小化假设选项。"
            "不要编造未提供的硬设定。回答尽量简洁、可执行。"
        )
        context_user = (
            f"【小说标题】{novel.title}\n\n"
            f"【框架 Markdown】\n{bible}\n\n"
            f"【框架 JSON（截断）】\n{fj_block}\n\n"
            f"{chr(10).join(memory_blocks)}\n\n"
            f"【已审定章节摘要（近段）】\n{approved_chapters_summary or '（暂无）'}\n\n"
            f"【连续性衔接摘录】\n{continuity_excerpt or '（暂无）'}"
        )
        out: list[dict[str, str]] = [
            {"role": "system", "content": sys},
            {"role": "user", "content": context_user},
        ]
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            out.append({"role": role, "content": content})
        async for evt in router.chat_text_stream(
            messages=out,
            temperature=0.45,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        ):
            yield evt

    def _framework_style_block_for_novel(self, novel: Novel, db: Any = None) -> str:
        if not novel.writing_style_id or not db:
            return ""
        ws = db.get(WritingStyle, novel.writing_style_id)
        if not ws:
            return ""
        return f"\n【写作风格深度定制要求】\n{_writing_style_block(ws)}\n"

    def _framework_target_meta(self, novel: Novel) -> tuple[int, int, int]:
        target_chapters = int(getattr(novel, "target_chapters", 0) or 0)
        volume_size = 50
        volume_n = (target_chapters + volume_size - 1) // volume_size if target_chapters > 0 else 0
        return target_chapters, volume_size, volume_n

    async def _generate_framework_base_stage(
        self,
        novel: Novel,
        *,
        mode: Literal["create", "regen", "characters"],
        db: Any = None,
        instruction: str = "",
        characters: list[dict[str, Any]] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        router = self._router(db=db, model=getattr(novel, "framework_model", None))
        ref = load_reference_text_for_llm(
            novel.reference_storage_key,
            novel.id,
            novel.reference_public_url,
        )
        target_chapters, _, _ = self._framework_target_meta(novel)
        ws_block = self._framework_style_block_for_novel(novel, db=db)

        tc_scale = int(target_chapters) if isinstance(target_chapters, int) and target_chapters > 0 else 120
        framework_depth_contract = (
            "【基础大纲要求】\n"
            "- 根据用户提供的简介和背景，整理出：一、世界观与核心设定；二、核心人物（至少3-4名）；三、主线剧情。\n"
            "- 内容要直接可用，无需刻意堆砌过多设定。因为世界观、主角、金手指等设定可能已经在简介和背景中确定，请直接提炼并合理扩写即可。\n"
            "- JSON中的 characters 至少包含核心主角和主要配角，主线 main_plot 写出明确的剧情阶段。\n"
        )

        framework_markdown_structure_contract = (
            "【Markdown 结构要求】\n"
            "- 只输出基础框架，必须包含且仅按以下三个一级章节组织：## 一、世界观与核心设定；## 二、核心人物；## 三、主线剧情与长期矛盾。\n"
            "- 除非用户明确要求改变格式，否则不要改章节标题名、不要改章节顺序、不要把人物或主线拆成额外的同级大节。\n"
        )
        framework_content_contract = (
            "【内容要求】\n"
            "- 世界观：除法则与力量体系外，须点名主要势力/地理或空间结构、资源稀缺性、普通人 vs 超凡者的日常差异。\n"
            "- 人物：禁止只写「高冷/温柔」等抽象词；traits 要能指导对白与行为；说明人物在主线中的功能（推动/阻碍/误导/牺牲等）。\n"
            "- 主线：必须写清「谁想要什么、为何现在拿不到、拿不到会怎样」；并写出可执行故事线：至少点明主要对手或制度性阻力在做什么、"
            "至少两处中盘反转或信息反转的伏笔位、至少两个带代价或时限的压力点；避免只用抽象词概括成长或逆袭。\n"
        )

        if mode == "create":
            sys = (
                "你是资深网文策划与世界观编辑。当前是第一阶段，只生成基础框架：设定、人物、主线，不生成卷级概览，不生成分卷剧情大纲（arcs）。\n"
                "请输出两部分：1) 完整可读 Markdown；2) 末尾单独一个 JSON 代码块，包含 "
                "world_rules, main_plot, characters[{name,role,traits,motivation}], themes 等基础键；"
                "可以补充 forbidden_constraints、key_locations、key_factions 等硬约束或索引键，但严禁输出 arcs、volume_overview、volumes。\n"
                f"{framework_markdown_structure_contract}"
                f"{framework_content_contract}"
                f"{framework_depth_contract}"
                f"{_ANTI_AI_FLAVOR_BLOCK}\n"
                "参考文本仅借鉴结构与文风，禁止抄袭原句。"
            )
            user = (
                f"书名：{novel.title}\n简介：{novel.intro}\n"
                f"背景设定：{novel.background}\n文风关键词：{novel.style}\n"
                f"{ws_block}"
                f"目标章节数：{target_chapters}\n\n"
                "请把简介与背景设定中的信息**展开、细化、落地**到 Markdown 与 JSON 中，而不是复述一遍短句；"
                "若简介与背景互有缺口，可在不违背用户意图的前提下做合理推演补全。\n"
                "本阶段不要写卷级概览，不要写分卷剧情大纲，不要输出 arcs。\n\n"
                f"参考文本节选：\n{ref or '（无）'}"
            )
        elif mode == "regen":
            fj_block = truncate_framework_json(framework_json_base_str(novel), 9000)
            md_block = (novel.framework_markdown or "")[:9000]
            sys = (
                "你是资深网文策划与世界观编辑。当前是第一阶段重构，只重写基础框架：设定、人物、主线。"
                "卷级概览与分卷剧情大纲（arcs）将在第二阶段单独生成。\n"
                "请输出两部分：1) 完整可读 Markdown；2) 末尾单独一个 JSON 代码块，包含 "
                "world_rules, main_plot, characters[{name,role,traits,motivation}], themes 等基础键；"
                "可以补充 forbidden_constraints、key_locations、key_factions 等硬约束，但严禁输出 arcs、volume_overview、volumes。\n"
                f"{framework_markdown_structure_contract}"
                f"{framework_content_contract}"
                f"{framework_depth_contract}"
                f"{_ANTI_AI_FLAVOR_BLOCK}\n"
                "参考文本仅借鉴结构与文风，禁止抄袭原句。"
            )
            user = (
                f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风关键词：{novel.style}\n"
                f"{ws_block}"
                f"目标章节数：{target_chapters}\n\n"
                f"【当前框架 Markdown（截断）】\n{md_block or '（空）'}\n\n"
                f"【当前框架 JSON（截断）】\n{fj_block}\n\n"
                f"【用户修改指令】\n{(instruction or '').strip()}\n\n"
                "请优先保留当前版本里已经合理、可用的部分，在此基础上重写并补强；若用户指令未明确要求换格式，就继续维持三段式基础大纲骨架。\n"
                "本阶段只处理设定/人物/主线，不要输出卷级概览，不要输出 arcs。\n\n"
                f"参考文本节选：\n{ref or '（无）'}"
            )
        else:
            fj_block = truncate_framework_json(framework_json_base_str(novel), 9000)
            md_block = (novel.framework_markdown or "")[:9000]
            chars_text = json.dumps(characters or [], ensure_ascii=False)
            sys = (
                "你是资深网文策划与世界观编辑。当前是第一阶段人物定向修订，只重写基础框架：设定、人物、主线。"
                "卷级概览与分卷剧情大纲（arcs）将在第二阶段基于本结果单独生成。\n"
                "请输出两部分：1) 完整可读 Markdown；2) 末尾单独一个 JSON 代码块，包含 "
                "world_rules, main_plot, characters[{name,role,traits,motivation}], themes 等基础键；"
                "可以补充 forbidden_constraints、key_locations、key_factions 等硬约束，但严禁输出 arcs、volume_overview、volumes。\n"
                "要求：人物列表以用户提供为准；需要时可以补充少量关键配角，但不得删除用户给出的主角。\n"
                f"{framework_depth_contract}"
                f"{_ANTI_AI_FLAVOR_BLOCK}"
            )
            user = (
                f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风：{novel.style}\n"
                f"{ws_block}"
                f"目标章节数：{target_chapters}\n\n"
                f"【当前框架 Markdown（截断）】\n{md_block or '（空）'}\n\n"
                f"【当前框架 JSON（截断）】\n{fj_block}\n\n"
                f"【用户确认后的人物列表（JSON）】\n{chars_text}\n\n"
                "请将人物变更融入基础框架：\n"
                "- 若人物改名，需全局替换并保持一致\n"
                "- traits 要落到动机/行为模式/关系张力上\n"
                "- 本阶段不要输出卷级概览，不要输出 arcs"
            )

        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.55 if mode != "create" else 0.6,
            max_tokens=settings.novel_framework_max_tokens,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _sanitize_base_framework_payload(_parse_framework_json_from_reply(text))
        markdown = _trim_base_framework_markdown(_strip_last_fenced_block(text) or text)
        return markdown or text, parsed

    async def _generate_framework_arcs_stage(
        self,
        novel: Novel,
        *,
        base_markdown: str,
        base_payload: dict[str, Any],
        db: Any = None,
        instruction: str = "",
        characters: list[dict[str, Any]] | None = None,
        target_volume_nos: list[int] | None = None,
        prior_volumes_arcs_context: str = "",
    ) -> tuple[str, dict[str, Any]]:
        router = self._router(db=db, model=getattr(novel, "framework_model", None))
        ref = load_reference_text_for_llm(
            novel.reference_storage_key,
            novel.id,
            novel.reference_public_url,
        )
        target_chapters, volume_size, volume_n = self._framework_target_meta(novel)
        ws_block = self._framework_style_block_for_novel(novel, db=db)
        base_json_text = json.dumps(base_payload, ensure_ascii=False)
        chars_block = (
            f"\n【最新人物列表（JSON）】\n{json.dumps(characters or [], ensure_ascii=False)}\n"
            if characters is not None
            else ""
        )
        instruction_block = (
            f"\n【需要同步遵守的修改指令】\n{instruction.strip()}\n"
            if instruction.strip()
            else ""
        )

        # 根据是否指定卷号生成不同的 system prompt
        if target_volume_nos:
            vol_nos_str = ",".join(str(v) for v in sorted(target_volume_nos))
            volume_scope_hint = (
                f"当前只需生成第 {vol_nos_str} 卷的 arcs，不要输出其他卷的 arcs。"
                f"总卷数约 {volume_n if volume_n else '请按目标章节数估算'}，"
                f"但本请求只处理指定的卷号。\n"
            )
        else:
            volume_scope_hint = (
                f"- 默认每卷约 {volume_size} 章；总卷数约 {volume_n if volume_n else '请按目标章节数估算'}。\n"
            )

        vol_seg_block = ""
        tc = int(target_chapters) if isinstance(target_chapters, int) and target_chapters > 0 else 0
        if target_volume_nos and tc > 0:
            parts: list[str] = []
            for raw in sorted(target_volume_nos):
                try:
                    vn = int(raw)
                except (TypeError, ValueError):
                    continue
                if vn < 1:
                    continue
                lo = (vn - 1) * volume_size + 1
                hi = min(tc, vn * volume_size)
                if lo > hi:
                    continue
                n_arc = max(1, (hi - lo + 1 + 4) // 5)
                parts.append(
                    f"  · 第{vn}卷为全书第 {lo}—{hi} 章：JSON 的 arcs 中，针对该卷**必须出现恰好 {n_arc} 条** arc，"
                    f"按**每 5 章一条**连续切分（相邻 arc 的章节号衔接、不重不漏，最后一条可到 {hi}）。"
                )
            if parts:
                vol_seg_block = (
                    "【本请求须满足的卷内条数（与下方 JSON 的 arcs 数组一一对应）】\n"
                    + "\n".join(parts)
                    + "\n"
                )

        prior_arcs_sys = ""
        if prior_volumes_arcs_context.strip():
            prior_arcs_sys = (
                "若用户消息中包含「已生成的前序分卷剧情弧线摘要」，你必须将其视为已定剧情走向："
                "新卷 arcs 与卷级概览须自然承接其中人物状态、未收束悬念与冲突升级，不得重置或无视前序已定内容。\n"
            )
        sys = (
            "你是资深网文策划与长篇连载分卷编辑。当前是第二阶段：只负责补完「卷级概览 + 分卷剧情大纲（Arcs）」。\n"
            f"{prior_arcs_sys}"
            "你必须严格沿用既有的世界观、人物、主线，不得重写 world_rules、main_plot、characters、themes，只能在其基础上细化长篇推进节奏。\n"
            "请输出两部分：1) 只包含新增部分的 Markdown 片段，且只写 `## 四、卷级概览` 与 `## 五、分卷剧情大纲 (Arcs)` 两节；"
            "2) 末尾单独一个 JSON 代码块，只包含 volume_overview 与 arcs 两个键，其中 arcs 必填。\n"
            "【卷级概览要求】\n"
            f"{volume_scope_hint}"
            "- 用卷为粒度概括每卷的主目标、核心冲突、阶段成果、卷末钩子。\n"
            "【分卷剧情 arcs 的硬性切分（必须遵守）】\n"
            f"- 以全书连续章号书写 from_chapter、to_chapter；默认每卷约 {volume_size} 章。\n"
            "- **每一卷内**按**每 5 章为一条 arc** 切分：在标准 50 章的卷中必须输出**恰好 10 条** arc，"
            "对应全书章号 1-5、6-10、11-15、16-20、21-25、26-30、31-35、36-40、41-45、46-50"
            f"（若该卷在全书中的章节起点不是 1，则整体平移到该卷的 from–to 范围内，仍保持每 5 章一条）。\n"
            "- 若某卷章数不是 5 的倍数，最后一条 arc 的 to_chapter 可到该卷末，前面仍按每 5 章一条。\n"
            "- **禁止**仅用 1-30、31-50 等两三条粗弧代替整卷的 5 章细弧。\n"
            "- 每个 arc 使用 JSON 整数 from_chapter、to_chapter（勿用字符串）；\n"
            "每条必须包含 **title**（短标题）与 **summary**（必填，**至少约 80 个汉字**），"
            "写清该段内的目标、冲突、转折、人物与伏笔；**禁止**只输出标题不写 summary。\n"
            "每条 arc **还必须**包含以下与执行约束相关的键（都不得为空泛占位）：\n"
            "- **hook**（string）：本段收束时留给下一段的悬念/钩子，1-3 句，可接剧情。\n"
            "- **must_not**（string[]）：**至少 1 条**，写明本段内**禁止**提前推进、揭露或完结的内容（如终局真相、某身份、某势力底牌等）。\n"
            "- **progress_allowed**（string 或 string[]）：**至少 1 项**，写明本段**允许且应当**推进到的阶段/可写事件，与 must_not 不矛盾。\n"
            "- 若仍有余力，可在 arc 内附加 sub_arcs 或 key_events 作补充，**但不得**用子结构代替使 summary、hook、must_not、progress_allowed 留空。\n"
            f"{_ANTI_AI_FLAVOR_BLOCK}\n"
            "参考文本仅借鉴结构与文风，禁止抄袭原句。"
        )
        user = (
            f"书名：{novel.title}\n简介：{novel.intro}\n背景设定：{novel.background}\n文风关键词：{novel.style}\n"
            f"{ws_block}"
            f"目标章节数：{target_chapters}\n"
            f"分卷规则：默认每卷 {volume_size} 章；总卷数约：{volume_n if volume_n else '（请按目标章节数自行估算）'}\n"
            f"{vol_seg_block}\n"
            f"【第一阶段基础框架 Markdown】\n{base_markdown or '（空）'}\n\n"
            f"【第一阶段基础框架 JSON】\n{base_json_text}\n"
            f"{instruction_block}"
            f"{chars_block}\n"
            + (
                f"\n【已生成的前序分卷剧情弧线摘要（承接用；勿逐字复述，须与本批新卷内容连贯）】\n"
                f"{prior_volumes_arcs_context.strip()}\n"
                if prior_volumes_arcs_context.strip()
                else ""
            )
            + "请只补全卷级概览与 arcs，不要重复输出前面已经定好的设定/人物/主线全文。\n\n"
            f"参考文本节选：\n{ref or '（无）'}"
        )
        text = await router.chat_text(
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
            temperature=0.55,
            max_tokens=settings.novel_framework_max_tokens,
            web_search=self._novel_web_search(db, flow="default"),
            timeout=600.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _parse_framework_json_from_reply(text)
        markdown = _strip_last_fenced_block(text)
        return markdown or text, parsed

    async def generate_framework(
        self,
        novel: Novel,
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """返回 (markdown 正文, 尽力解析的 json 字符串)。"""
        _notify_progress(progress_callback, "第一阶段：生成设定、人物与主线")
        base_markdown, base_payload = await self._generate_framework_base_stage(
            novel,
            mode="create",
            db=db,
        )
        _notify_progress(progress_callback, "第二阶段：生成卷级概览与分卷剧情大纲（Arcs）")
        arcs_markdown, arcs_payload = await self._generate_framework_arcs_stage(
            novel,
            base_markdown=base_markdown,
            base_payload=base_payload,
            db=db,
        )
        final_markdown = _merge_framework_markdown_sections(base_markdown, arcs_markdown)
        final_payload = _merge_framework_payloads(base_payload, arcs_payload)
        return final_markdown, json.dumps(final_payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    #  仅生成基础框架（大纲 + 人物 + 主线，不含 arcs）
    # ------------------------------------------------------------------
    async def generate_base_framework(
        self,
        novel: Novel,
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
        *,
        mode: Literal["create", "regen"] = "create",
        instruction: str = "",
    ) -> tuple[str, str]:
        """只生成基础框架（设定/人物/主线），不含 arcs。返回 (markdown, json_string)。"""
        _notify_progress(progress_callback, "生成设定、人物与主线")
        base_markdown, base_payload = await self._generate_framework_base_stage(
            novel,
            mode=mode,
            db=db,
            instruction=instruction,
        )
        return base_markdown, json.dumps(base_payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    #  为指定卷号生成 arcs（增量）
    # ------------------------------------------------------------------
    async def generate_arcs_for_volumes(
        self,
        novel: Novel,
        *,
        target_volume_nos: list[int] | None = None,
        instruction: str = "",
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """
        为指定卷号生成 arcs 并增量合并到 framework_json。
        返回 (更新后的 markdown, 更新后的 json_string)。
        如果 target_volume_nos 为 None，则生成所有卷的 arcs。
        """
        # 从当前 framework_json 中提取 base 部分
        current_fw = _safe_json_dict(novel.framework_json or "{}")
        base_payload = _sanitize_base_framework_payload(current_fw)
        base_markdown = _trim_base_framework_markdown(novel.framework_markdown or "")

        _notify_progress(progress_callback, f"生成第{','.join(str(v) for v in (target_volume_nos or []))}卷的 Arcs")

        prior_ctx = ""
        if target_volume_nos:
            try:
                min_v = min(int(x) for x in target_volume_nos)
            except (TypeError, ValueError):
                min_v = 1
            if min_v > 1:
                _, vs, _ = self._framework_target_meta(novel)
                prior_ctx = _build_prior_volumes_arcs_context_block(
                    current_fw,
                    min_target_volume_no=min_v,
                    volume_size=vs,
                )

        arcs_markdown, arcs_payload = await self._generate_framework_arcs_stage(
            novel,
            base_markdown=base_markdown,
            base_payload=base_payload,
            db=db,
            instruction=instruction,
            target_volume_nos=target_volume_nos,
            prior_volumes_arcs_context=prior_ctx,
        )

        # 增量合并：只替换/追加指定卷的 arcs
        final_payload = _merge_arcs_into_framework(current_fw, arcs_payload, target_volume_nos)
        final_markdown = _merge_framework_markdown_sections(base_markdown, arcs_markdown)
        return final_markdown, json.dumps(final_payload, ensure_ascii=False)

    async def regenerate_framework(
        self,
        novel: Novel,
        instruction: str,
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """仅重写基础大纲；分卷 Arcs 在卷表单独生成/维护。"""
        return await self.generate_base_framework(
            novel,
            db=db,
            progress_callback=progress_callback,
            mode="regen",
            instruction=instruction,
        )

    async def update_framework_characters(
        self,
        novel: Novel,
        characters: list[dict[str, Any]],
        db: Any = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        """仅更新基础框架中的人物与相关设定；卷级 Arcs 不受影响。"""
        _notify_progress(progress_callback, "按新人物设定重写基础框架")
        base_markdown, base_payload = await self._generate_framework_base_stage(
            novel,
            mode="characters",
            db=db,
            characters=characters,
        )
        return base_markdown, json.dumps(base_payload, ensure_ascii=False)

    async def generate_volume_chapter_plan_batch_json(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """
        生成“指定章节区间”的一批章计划，并返回严格 JSON 字符串。

        设计目的：
        - 前端/用户手动点击推进，每次只跑一批，成功即落库，避免整卷循环导致超时白跑。
        - 通过 prev_batch_context 传递上一批末两章关键信息，保证连续性。
        - cross_volume_tail_context：新开卷首批时由调用方注入上一卷末计划/正文摘录。
        """
        batch_label = f"卷{volume_no} 批次 {from_chapter}-{to_chapter}"
        batch_json_str = await self._generate_single_batch_plan(
            novel=novel,
            volume_no=volume_no,
            volume_title=volume_title,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            memory_json=memory_json,
            prev_batch_context=prev_batch_context,
            cross_volume_tail_context=cross_volume_tail_context,
            db=db,
        )
        batch_data = self._parse_volume_plan_llm_json(batch_json_str, batch_label=batch_label)
        raw_chapters = batch_data.get("chapters", [])
        if not isinstance(raw_chapters, list):
            raw_chapters = []
        chapters = self._normalize_volume_plan_batch_chapters(
            raw_chapters,
            batch_start=from_chapter,
            batch_end=to_chapter,
            batch_label=batch_label,
        )
        result = {
            "volume_title": volume_title,
            "volume_summary": f"第{volume_no}卷，批次第{from_chapter}-{to_chapter}章",
            "chapters": chapters,
        }
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _volume_plan_chapter_sort_key(ch: dict) -> int:
        cn = ch.get("chapter_no")
        if isinstance(cn, int):
            return cn
        if isinstance(cn, str) and cn.strip().lstrip("-").isdigit():
            try:
                return int(cn.strip())
            except ValueError:
                pass
        return 1 << 30

    def _sort_volume_plan_chapters(self, chapters: list[Any]) -> list[dict]:
        return sorted(
            (c for c in chapters if isinstance(c, dict)),
            key=self._volume_plan_chapter_sort_key,
        )

    def _parse_volume_plan_llm_json(self, batch_json_str: str, *, batch_label: str) -> dict:
        try:
            return _volume_plan_parse_llm_json_to_dict(batch_json_str)
        except json.JSONDecodeError as e:
            snippet = (batch_json_str or "")[:1200]
            logger.warning(
                "%s 卷章计划 JSON 解析失败 | err=%s pos=%s snippet_head=%r",
                batch_label,
                e,
                getattr(e, "pos", None),
                snippet[:500],
            )
            raise RuntimeError(f"{batch_label} 返回非法 JSON：{e}") from e

    def _normalize_volume_plan_batch_chapters(
        self,
        chapters: list[Any],
        *,
        batch_start: int,
        batch_end: int,
        batch_label: str,
    ) -> list[dict]:
        expected = batch_end - batch_start + 1
        sorted_ch = self._sort_volume_plan_chapters(chapters)
        if len(sorted_ch) > expected:
            logger.warning(
                "%s 章条目数为 %d，多于本批 %d 条，已截断（第 %d-%d 章）",
                batch_label,
                len(sorted_ch),
                expected,
                batch_start,
                batch_end,
            )
            sorted_ch = sorted_ch[:expected]
        elif len(sorted_ch) < expected:
            logger.warning(
                "%s 章条目数为 %d，少于本批 %d 条，仍按已生成条目落库（第 %d-%d 章）",
                batch_label,
                len(sorted_ch),
                expected,
                batch_start,
                batch_end,
            )
        for i, ch in enumerate(sorted_ch):
            ch["chapter_no"] = batch_start + i
            beats = ch.get("beats")
            ch["beats"] = normalize_beats_to_v2(beats if isinstance(beats, dict) else {})
        return sorted_ch

    def _validate_merged_volume_plan_chapters(
        self,
        chapters: list[dict],
        *,
        from_chapter: int,
        to_chapter: int,
        volume_no: int,
    ) -> None:
        total = to_chapter - from_chapter + 1
        if len(chapters) != total:
            logger.warning(
                "第 %s 卷章计划合并后共 %d 条，期望 %d 条（第 %d-%d 章），条数不足时仍返回已生成部分",
                volume_no,
                len(chapters),
                total,
                from_chapter,
                to_chapter,
            )
        if len(chapters) != total:
            return
        for i, ch in enumerate(chapters):
            expect_no = from_chapter + i
            cn = ch.get("chapter_no")
            if cn != expect_no:
                raise RuntimeError(
                    f"第 {volume_no} 卷章计划 chapter_no 不连续："
                    f"第 {i + 1} 条期望 {expect_no}，实际 {cn!r}"
                )

    async def generate_volume_chapter_plan_json(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        db: Any = None,
    ) -> str:
        """
        生成整卷章计划（严格 JSON 文本）。该 JSON 会由路由解析并落库。
        采用分批生成策略，避免单次请求超时，同时保证批次间剧情连续性。
        """
        batch_size = max(1, settings.novel_volume_plan_batch_size)
        total_chapters = to_chapter - from_chapter + 1

        # 如果章节数不超过批次大小，直接单次生成
        if total_chapters <= batch_size:
            batch_json_str = await self._generate_single_batch_plan(
                novel=novel,
                volume_no=volume_no,
                volume_title=volume_title,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                memory_json=memory_json,
                prev_batch_context="",
                cross_volume_tail_context="",
                db=db,
            )
            batch_data = self._parse_volume_plan_llm_json(
                batch_json_str, batch_label="整卷章计划"
            )
            raw_chapters = batch_data.get("chapters", [])
            if not isinstance(raw_chapters, list):
                raw_chapters = []
            chapters = self._normalize_volume_plan_batch_chapters(
                raw_chapters,
                batch_start=from_chapter,
                batch_end=to_chapter,
                batch_label="整卷章计划",
            )
            self._validate_merged_volume_plan_chapters(
                chapters,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                volume_no=volume_no,
            )
            result = {
                "volume_title": volume_title,
                "volume_summary": f"第{volume_no}卷，共{len(chapters)}章",
                "chapters": chapters,
            }
            return json.dumps(result, ensure_ascii=False)

        # 分批生成
        all_chapters: list[dict] = []
        prev_batch_context = ""
        batch_num = 0

        for batch_start in range(from_chapter, to_chapter + 1, batch_size):
            batch_end = min(batch_start + batch_size - 1, to_chapter)
            batch_num += 1
            logger.info(
                "generate_volume_chapter_plan batch %d | chapters %d-%d | total %d",
                batch_num,
                batch_start,
                batch_end,
                total_chapters,
            )

            batch_json_str = await self._generate_single_batch_plan(
                novel=novel,
                volume_no=volume_no,
                volume_title=volume_title,
                from_chapter=batch_start,
                to_chapter=batch_end,
                memory_json=memory_json,
                prev_batch_context=prev_batch_context,
                cross_volume_tail_context="",
                db=db,
            )

            batch_data = self._parse_volume_plan_llm_json(
                batch_json_str, batch_label=f"批次 {batch_num}"
            )
            raw_chapters = batch_data.get("chapters", [])
            if not isinstance(raw_chapters, list):
                raw_chapters = []

            chapters = self._normalize_volume_plan_batch_chapters(
                raw_chapters,
                batch_start=batch_start,
                batch_end=batch_end,
                batch_label=f"批次 {batch_num}",
            )
            all_chapters.extend(chapters)

            # 构建下一批次的上下文（最后2章的关键信息）
            prev_batch_context = self._build_next_batch_context(
                chapters=chapters,
                volume_title=volume_title,
            )

        merged = self._sort_volume_plan_chapters(all_chapters)
        self._validate_merged_volume_plan_chapters(
            merged,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            volume_no=volume_no,
        )

        # 合并结果
        result = {
            "volume_title": volume_title,
            "volume_summary": f"第{volume_no}卷，共{len(merged)}章",
            "chapters": merged,
        }
        return json.dumps(result, ensure_ascii=False)

    async def _generate_single_batch_plan(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """生成单批次章计划"""
        router = self._router(db=db, model=getattr(novel, "plan_model", None))
        batch_chapter_count = to_chapter - from_chapter + 1

        # 根据篇幅获取对应的防重复约束
        anti_repetition_block = self._get_anti_repetition_constraints(novel, batch_chapter_count)

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

        # 构建前文上下文提示
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
            f"【卷信息】第{volume_no}卷《{volume_title}》，本批次章节范围：第{from_chapter}章-第{to_chapter}章\n\n"
            f"【框架 Markdown（摘要）】\n{(novel.framework_markdown or novel.background or '')[:8000]}\n\n"
            f"【框架 JSON】\n{novel.framework_json or '{}'}\n\n"
            f"【结构化记忆（open_plots/canonical_timeline 等）】\n{memory_json}\n"
            f"{cross_volume_hint}"
            f"{continuity_hint}"
            "【输出要求（严格 JSON）】\n"
            "{\n"
            '  \"volume_title\": string,\n'
            '  \"volume_summary\": string,\n'
            '  \"chapters\": [\n'
            "    {\n"
            '      \"chapter_no\": number,\n'
            '      \"title\": string,\n'
            '      \"beats\": {\n'
            '        \"goal\": string,\n'
            '        \"conflict\": string,\n'
            '        \"turn\": string,\n'
            '        \"hook\": string,\n'
            '        \"plot_summary\": string,\n'
            '        \"stage_position\": string,\n'
            '        \"pacing_justification\": string,\n'
            '        \"expressive_brief\": {\n'
            '          \"pov_strategy\": string,\n'
            '          \"emotional_curve\": string,\n'
            '          \"sensory_focus\": string,\n'
            '          \"dialogue_strategy\": string,\n'
            '          \"scene_tempo\": string,\n'
            '          \"reveal_strategy\": string\n'
            '        },\n'
            '        \"progress_allowed\": string 或 string[],\n'
            '        \"must_not\": string[],\n'
            '        \"reserved_for_later\": [ { \"item\": string, \"not_before_chapter\": number } ],\n'
            '        \"scene_cards\": [\n'
            '          {\n'
            '            \"label\": string,\n'
            '            \"goal\": string,\n'
            '            \"conflict\": string,\n'
            '            \"content\": string,\n'
            '            \"outcome\": string,\n'
            '            \"emotion_beat\": string,\n'
            '            \"camera\": string,\n'
            '            \"dialogue_density\": string,\n'
            '            \"words\": number\n'
            '          }\n'
            '        ]\n'
            "      },\n"
            '      \"open_plots_intent_added\": string[],\n'
            '      \"open_plots_intent_resolved\": string[]\n'
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
            f"1) chapters 数组必须恰好包含 {batch_chapter_count} 个对象（第 {from_chapter}～{to_chapter} 章，缺一不可、也不可合并）；"
            f"chapter_no 从 {from_chapter} 起连续递增；输出前自检 JSON 中 chapters.length === {batch_chapter_count}；\n"
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
                if from_chapter <= 1 <= to_chapter
                else ""
            )
            + f"{anti_repetition_block}"
        )
        return await router.chat_text(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.55,
            web_search=self._novel_web_search(db, flow="volume_plan"),
            timeout=settings.novel_volume_plan_batch_timeout,
            max_tokens=8192,
            **self._bill_kw(db, self._billing_user_id),
        )

    @staticmethod
    def _get_anti_repetition_constraints(novel: Novel, batch_chapter_count: int) -> str:
        """根据小说篇幅返回对应的防重复约束提示词

        篇幅定义：
        - 短篇：≤50章 - 节奏紧凑，每章必须推进
        - 中篇：51-200章 - 适度推进，允许过渡和蓄势
        - 长篇：>200章 - 张弛有度，允许支线、人物发展、休整章节
        """
        target = getattr(novel, "target_chapters", 0) or 0

        # 短篇：严格紧凑
        if target <= 50:
            return """【短篇节奏约束 - 严格推进】
11) 短篇节奏必须紧凑：每章必须有实质性推进，不允许「纯过渡/纯对话/纯描述」章节；
12) 禁止重复使用相同的心理活动模式：如「心里乱成一团」、「感到深深的疲惫」等固定句式；
13) 禁止重复的环境描写开场：同一卷内各章的场景氛围必须有所变化；
14) 每章 conflict 必须与前3章有本质区别或递进，不得「换汤不换药」；
15) 人物情绪必须递进：不得在同一情绪层级反复横跳，必须朝向解决或恶化方向演进。
"""

        # 长篇：张弛有度
        if target > 200:
            return """【长篇节奏约束 - 张弛有度】
11) 长篇允许节奏变化：章节可分为「推进章」「蓄势章」「过渡章」「人物章」「支线章」等不同类型，不必每章都推进主线；
12) 避免固定套路化描写即可，但不要求每章都完全不同：相似的心理状态可在不同情境下出现，但需有合理差异；
13) 环境描写可适当重复（如同一地点的多次到访），但需体现时间、氛围、人物心境的变化；
14) conflict 可有层次地展开：允许在同一冲突主题下分多章逐步升级，不必每章都是新冲突；
15) 人物情绪发展允许反复和挣扎：真实的人物塑造允许情绪回退、自我怀疑、短暂动摇，不必单向递进；
16) 多线叙事鼓励：允许并鼓励支线发展、配角视角、背景铺陈，这些「非主线推进」内容对长篇质量至关重要。
"""

        # 中篇：平衡策略（默认）
        return """【中篇节奏约束 - 平衡推进】
11) 中篇需保持适度推进：每1-2章应有可见的进展，允许必要的过渡和蓄势章节；
12) 避免固定套路化描写：不重复使用完全相同的心理/环境描写句式；
13) 同一卷内场景氛围需有变化：但允许相关章节的场景延续；
14) conflict 需有递进或变化：同一主题可分章展开，但需体现层次升级；
15) 人物情绪应总体递进：允许短暂波动，但总体趋势应朝向发展或变化。
"""

    def _generate_single_batch_plan_sync(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """生成单批次章计划（同步，供 Celery worker 使用）。"""
        router = self._router(db=db, model=getattr(novel, "plan_model", None))
        batch_chapter_count = to_chapter - from_chapter + 1

        # 根据篇幅获取对应的防重复约束
        anti_repetition_block = self._get_anti_repetition_constraints(novel, batch_chapter_count)

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
            f"【卷信息】第{volume_no}卷《{volume_title}》，本批次章节范围：第{from_chapter}章-第{to_chapter}章\n\n"
            f"【框架 Markdown（摘要）】\n{(novel.framework_markdown or novel.background or '')[:8000]}\n\n"
            f"【框架 JSON】\n{novel.framework_json or '{}'}\n\n"
            f"【结构化记忆（open_plots/canonical_timeline 等）】\n{memory_json}\n"
            f"{cross_volume_hint}"
            f"{continuity_hint}"
            "【输出要求（严格 JSON）】\n"
            "{\n"
            '  \"volume_title\": string,\n'
            '  \"volume_summary\": string,\n'
            '  \"chapters\": [\n'
            "    {\n"
            '      \"chapter_no\": number,\n'
            '      \"title\": string,\n'
            '      \"beats\": {\n'
            '        \"goal\": string,\n'
            '        \"conflict\": string,\n'
            '        \"turn\": string,\n'
            '        \"hook\": string,\n'
            '        \"plot_summary\": string,\n'
            '        \"stage_position\": string,\n'
            '        \"pacing_justification\": string,\n'
            '        \"expressive_brief\": {\n'
            '          \"pov_strategy\": string,\n'
            '          \"emotional_curve\": string,\n'
            '          \"sensory_focus\": string,\n'
            '          \"dialogue_strategy\": string,\n'
            '          \"scene_tempo\": string,\n'
            '          \"reveal_strategy\": string\n'
            '        },\n'
            '        \"progress_allowed\": string 或 string[],\n'
            '        \"must_not\": string[],\n'
            '        \"reserved_for_later\": [ { \"item\": string, \"not_before_chapter\": number } ],\n'
            '        \"scene_cards\": [\n'
            '          {\n'
            '            \"label\": string,\n'
            '            \"goal\": string,\n'
            '            \"conflict\": string,\n'
            '            \"content\": string,\n'
            '            \"outcome\": string,\n'
            '            \"emotion_beat\": string,\n'
            '            \"camera\": string,\n'
            '            \"dialogue_density\": string,\n'
            '            \"words\": number\n'
            '          }\n'
            '        ]\n'
            "      },\n"
            '      \"open_plots_intent_added\": string[],\n'
            '      \"open_plots_intent_resolved\": string[]\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "volume_summary：用 200～500 字写清本卷在本作中的位置、本卷核心矛盾、阶段目标、与前后卷的衔接、读者在本卷应获得的情绪曲线；"
            "避免空泛一句话，需分层（人物线/主线/副线/悬念）各至少一句。\n"
            "beats 字段说明：plot_summary 为本章剧情梗概（约 5～12 句，须写清场景转换、关键行动、信息边界、章末停笔点）；"
            "stage_position 用一两句说明本章在「当前大纲弧/本卷」中的位置（例如「第一弧约 15% 处、仅完成铺垫」）；"
            "pacing_justification 用一两句说明本章为何**不会**提前触发后续弧或更大阶段的核心事件（避免与 must_not 矛盾）；"
            "progress_allowed 写明本章允许推进的内容；must_not 列出本章绝对不得出现的情节、能力觉醒、设定点名、剧透；"
            "reserved_for_later 列出须延后到指定章节号及之后才允许在正文成真或点名的条目（not_before_chapter 为全局章节号）。\n\n"
            "【硬约束】\n"
            f"1) chapters 数组必须恰好包含 {batch_chapter_count} 个对象（第 {from_chapter}～{to_chapter} 章，缺一不可、也不可合并）；"
            f"chapter_no 从 {from_chapter} 起连续递增；输出前自检 JSON 中 chapters.length === {batch_chapter_count}；\n"
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
                "【全书第1章（仅当本批次含第1章时适用）】\n"
                "若 chapters 含 chapter_no=1：该章须为「可入场」第1章——plot_summary/goal/conflict 须体现基本时空或环境、主角身份与处境、故事契机的来由；"
                "must_not 须明确禁止缺乏铺垫的莫名其妙开场（未解释的多方混战、大段生造专名、人物关系未明就写终局式结果等）。\n"
                if from_chapter <= 1 <= to_chapter
                else ""
            )
            + (
                "【防剧情重复硬约束 - 必须遵守】\n"
                "11) 自检：若前批次已出现「质疑-举证-被否定」的冲突循环，本批次不得再使用相同模式，必须让剧情进入新阶段（如：误会加深导致关系破裂、发现新证据、引入新人物、冲突升级等）；\n"
                "12) 禁止重复使用相同的心理活动描写模式：如「心里乱成一团」、「感到深深的疲惫」、「嘴角挂着冷笑」等固定句式，同一卷内不得在不同章重复出现；\n"
                "13) 禁止重复的环境描写开场：如「月光惨白」、「村里的狗吠」、「红木桌子」等，同一卷内各章的场景氛围必须有所变化（时间、天气、环境、氛围）；\n"
                "14) 每章的 conflict 必须与前3章的冲突有本质区别或递进，不得只是换汤不换药的重复争吵；自检：如果本章 conflict 只是前章的「再来一次」，必须重新设计；\n"
                "15) 人物情绪必须递进：如二舅对男主的态度应从信任→怀疑→动摇→愤怒→决裂逐步演变，不得在同一情绪层级反复横跳。\n"
            )
        )
        return router.chat_text_sync(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.55,
            web_search=self._novel_web_search(db, flow="volume_plan"),
            timeout=settings.novel_volume_plan_batch_timeout,
            max_tokens=8192,
            **self._bill_kw(db, self._billing_user_id),
        )

    def generate_volume_chapter_plan_batch_json_sync(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        from_chapter: int,
        to_chapter: int,
        memory_json: str,
        prev_batch_context: str = "",
        cross_volume_tail_context: str = "",
        db: Any = None,
    ) -> str:
        """同步版：生成指定区间的一批章计划 JSON 字符串（供 Celery）。"""
        batch_label = f"卷{volume_no} 批次 {from_chapter}-{to_chapter}"
        batch_json_str = self._generate_single_batch_plan_sync(
            novel=novel,
            volume_no=volume_no,
            volume_title=volume_title,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            memory_json=memory_json,
            prev_batch_context=prev_batch_context,
            cross_volume_tail_context=cross_volume_tail_context,
            db=db,
        )
        batch_data = self._parse_volume_plan_llm_json(batch_json_str, batch_label=batch_label)
        raw_chapters = batch_data.get("chapters", [])
        if not isinstance(raw_chapters, list):
            raw_chapters = []
        chapters = self._normalize_volume_plan_batch_chapters(
            raw_chapters,
            batch_start=from_chapter,
            batch_end=to_chapter,
            batch_label=batch_label,
        )
        result = {
            "volume_title": volume_title,
            "volume_summary": f"第{volume_no}卷，批次第{from_chapter}-{to_chapter}章",
            "chapters": chapters,
        }
        return json.dumps(result, ensure_ascii=False)

    async def regenerate_single_chapter_plan(
        self,
        novel: Novel,
        *,
        volume_no: int,
        volume_title: str,
        chapter_no: int,
        memory_json: str,
        prev_chapters: list[dict] = None,
        next_chapters: list[dict] = None,
        user_instruction: str = "",
        db: Any = None,
    ) -> dict:
        """重生成单章计划，支持前后文参考和自定义指令"""
        router = self._router(db=db, model=getattr(novel, "plan_model", None))
        sys = (
            "你是网络小说高级编剧。你的任务是根据用户指令修订或重生成指定章节的「章计划」。"
            "你必须严格输出一个 JSON 对象，不要输出任何解释性文字。"
            "【JSON 语法要求】字符串值内禁止直接换行；剧情文本避免未转义双引号。\n"
            f"{_ANTI_AI_FLAVOR_BLOCK}"
        )

        # 构建参考上下文
        ref_context = ""
        if prev_chapters:
            ref_context += "\n【前文计划参考（必须承接）】\n"
            for c in prev_chapters:
                ref_context += f"第{c.get('chapter_no')}章《{c.get('title')}》: {c.get('beats', {}).get('plot_summary', '')[:300]}\n"
        
        if next_chapters:
            ref_context += "\n【后文计划参考（需保证因果逻辑不冲突）】\n"
            for c in next_chapters:
                ref_context += f"第{c.get('chapter_no')}章《{c.get('title')}》: {c.get('beats', {}).get('plot_summary', '')[:300]}\n"

        user = (
            f"【小说标题】{novel.title}\n"
            f"【本章位置】第{volume_no}卷《{volume_title}》，第{chapter_no}章\n\n"
            f"【用户修订指令】\n{user_instruction or '请根据大纲和前后文重新优化本章计划，增强戏剧冲突。'}\n\n"
            f"【框架摘要】\n{(novel.framework_markdown or novel.background or '')[:5000]}\n\n"
            f"{ref_context}\n"
            "【输出格式（严格 JSON）】\n"
            "{\n"
            '  "chapter_no": number,\n'
            '  "title": string,\n'
            '  "beats": {\n'
            '    "goal": string,\n'
            '    "conflict": string,\n'
            '    "turn": string,\n'
            '    "hook": string,\n'
            '    "plot_summary": string,\n'
            '    "stage_position": string,\n'
            '    "pacing_justification": string,\n'
            '    "expressive_brief": {\n'
            '      "pov_strategy": string,\n'
            '      "emotional_curve": string,\n'
            '      "sensory_focus": string,\n'
            '      "dialogue_strategy": string,\n'
            '      "scene_tempo": string,\n'
            '      "reveal_strategy": string\n'
            '    },\n'
            '    "progress_allowed": string[],\n'
            '    "must_not": string[],\n'
            '    "reserved_for_later": [ { "item": string, "not_before_chapter": number } ],\n'
            '    "scene_cards": [\n'
            '      {\n'
            '        "label": string,\n'
            '        "goal": string,\n'
            '        "conflict": string,\n'
            '        "content": string,\n'
            '        "outcome": string,\n'
            '        "emotion_beat": string,\n'
            '        "camera": string,\n'
            '        "dialogue_density": string,\n'
            '        "words": number\n'
            '      }\n'
            '    ]\n'
            '  },\n'
            '  "open_plots_intent_added": string[],\n'
            '  "open_plots_intent_resolved": string[]\n'
            "}\n"
        )

        resp = await router.chat_text(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.6,
            timeout=120.0,
            max_tokens=3000,
            **self._bill_kw(db, self._billing_user_id),
        )
        
        # 解析 JSON
        try:
            data = _volume_plan_parse_llm_json_to_dict(resp)
            # 兼容处理：如果是包装在 {"chapters": [...]} 里的单项
            if "chapters" in data and isinstance(data["chapters"], list) and len(data["chapters"]) > 0:
                data = data["chapters"][0]
            data["chapter_no"] = chapter_no # 强制修正
            data["beats"] = normalize_beats_to_v2(data.get("beats") or {})
            return data
        except Exception as e:
            logger.error("regenerate_single_chapter_plan parse failed: %s | resp=%r", e, resp[:500])
            raise RuntimeError(f"单章计划解析失败：{e}")

    def _build_next_batch_context(
        self,
        chapters: list[dict],
        volume_title: str,
    ) -> str:
        """构建下一批次的衔接上下文"""
        if not chapters:
            return ""

        ordered = self._sort_volume_plan_chapters(chapters)

        # 取排序后最后 2 章（或更少）的关键信息
        tail_chapters = ordered[-2:] if len(ordered) >= 2 else ordered

        context_parts = []
        for ch in tail_chapters:
            if not isinstance(ch, dict):
                continue
            ch_no = ch.get("chapter_no", "?")
            title = ch.get("title", "")
            beats = normalize_beats_to_v2(ch.get("beats", {}))
            plot_summary = chapter_plan_plot_summary(beats)
            hook = chapter_plan_hook(beats)

            # 收集新增和解决的 open_plots
            added = ch.get("open_plots_intent_added", [])
            resolved = ch.get("open_plots_intent_resolved", [])

            context_parts.append(
                f"第{ch_no}章《{title}》:\n"
                f"  剧情梗概: {plot_summary[:500] if plot_summary else '（无）'}\n"
                f"  章末钩子: {hook[:200] if hook else '（无）'}\n"
                f"  新增线索: {json.dumps(added, ensure_ascii=False) if added else '[]'}\n"
                f"  解决线索: {json.dumps(resolved, ensure_ascii=False) if resolved else '[]'}\n"
            )

        # 汇总当前活跃的 open_plots（按章节号顺序折叠，避免模型乱序导致错判）
        active_plots = set()
        for ch in ordered:
            for p in ch.get("open_plots_intent_added", []):
                if isinstance(p, str) and p.strip():
                    active_plots.add(p.strip())
            for p in ch.get("open_plots_intent_resolved", []):
                if isinstance(p, str) and p.strip():
                    active_plots.discard(p.strip())

        summary = "\n".join(context_parts)
        if active_plots:
            summary += f"\n当前批次遗留的活跃线索（后续需承接或解决）:\n{json.dumps(list(active_plots), ensure_ascii=False)}\n"

        return summary

from app.services.novel_llm_chapter_service import NovelLLMChapterService
from app.services.novel_llm_memory_service import NovelLLMMemoryService
from app.services.novel_llm_draw_card_service import NovelLLMDrawCardService


class NovelLLMService(NovelLLMDrawCardService):
    """对外兼容入口：聚合所有小说 LLM 功能。"""

    pass
