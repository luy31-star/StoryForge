from __future__ import annotations

from typing import Any
import time

from json_repair import loads as json_repair_loads

from app.core.config import settings
from app.models.novel import Novel
from app.services.novel_llm_service import NovelLLMCoreService
from app.services.novel_llm_utils import (
    _audit_chapter_against_plan_messages,
    _chapter_messages,
    _check_and_fix_chapter_messages,
    _de_ai_chapter_messages,
    _dedupe_str_list,
    _expressive_enhance_chapter_messages,
    _fix_chapter_to_plan_messages,
    _safe_json_dict,
    chapter_plan_has_guardrails,
)
import logging
logger = logging.getLogger(__name__)


class NovelLLMChapterService(NovelLLMCoreService):
    """章节生成与修订相关能力。"""

    async def generate_chapter(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        recent_full_context: str = "",
        chapter_plan_hint: str = "",
        db: Any = None,
        *,
        use_cold_recall: bool | None = None,
        cold_recall_items: int = 5,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> str:
        router = self._router(provider=llm_provider, model=llm_model or getattr(novel, "chapter_model", None), db=db)
        messages = _chapter_messages(
            novel,
            chapter_no,
            chapter_title_hint,
            memory_json,
            continuity_excerpt,
            recent_full_context,
            chapter_plan_hint,
            db=db,
            use_cold_recall=use_cold_recall,
            cold_recall_items=cold_recall_items,
        )
        effective_cold = use_cold_recall if use_cold_recall is not None else (
            settings.novel_cold_recall_auto_threshold > 0
            and chapter_no >= settings.novel_cold_recall_auto_threshold
        )
        budget_override = (
            int(settings.novel_prompt_char_budget * 1.33)
            if effective_cold
            else None
        )
        messages = self._budget_chapter_messages(messages, budget=budget_override)
        model = (llm_model or router.model or "").strip() or "-"
        web_search = self._novel_web_search(db, flow="generate")
        timeout = settings.novel_chapter_timeout
        start = time.perf_counter()
        logger.info(
            "generate_chapter start | novel_id=%s chapter_no=%s model=%s web_search=%s cold_recall=%s cold_items=%s msg_chars=%s mem_chars=%s continuity_chars=%s",
            novel.id,
            chapter_no,
            model,
            web_search,
            use_cold_recall,
            cold_recall_items,
            self._messages_chars(messages),
            len(memory_json or ""),
            len(continuity_excerpt or ""),
        )
        try:
            out = await self._chat_text_with_timeout_retry(
                router=router,
                operation="generate_chapter",
                novel_id=novel.id,
                chapter_no=chapter_no,
                messages=messages,
                temperature=0.45,
                web_search=web_search,
                timeout=timeout,
                max_tokens=settings.novel_chapter_max_tokens,
                **self._bill_kw(db, self._billing_user_id),
            )
            return out
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "generate_chapter done | novel_id=%s chapter_no=%s elapsed=%.2fs",
                novel.id,
                chapter_no,
                elapsed,
            )

    def generate_chapter_sync(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        recent_full_context: str = "",
        chapter_plan_hint: str = "",
        db: Any = None,
        *,
        use_cold_recall: bool | None = None,
        cold_recall_items: int = 5,
    ) -> str:
        router = self._router(db=db, model=getattr(novel, "chapter_model", None))
        messages = _chapter_messages(
            novel,
            chapter_no,
            chapter_title_hint,
            memory_json,
            continuity_excerpt,
            recent_full_context,
            chapter_plan_hint,
            db=db,
            use_cold_recall=use_cold_recall,
            cold_recall_items=cold_recall_items,
        )
        effective_cold = use_cold_recall if use_cold_recall is not None else (
            settings.novel_cold_recall_auto_threshold > 0
            and chapter_no >= settings.novel_cold_recall_auto_threshold
        )
        budget_override = (
            int(settings.novel_prompt_char_budget * 1.33)
            if effective_cold
            else None
        )
        messages = self._budget_chapter_messages(messages, budget=budget_override)
        model = (router.model or "").strip() or "-"
        web_search = self._novel_web_search(db, flow="generate")
        timeout = settings.novel_chapter_timeout
        start = time.perf_counter()
        logger.info(
            "generate_chapter_sync start | novel_id=%s chapter_no=%s model=%s web_search=%s cold_recall=%s cold_items=%s msg_chars=%s",
            novel.id,
            chapter_no,
            model,
            web_search,
            use_cold_recall,
            cold_recall_items,
            self._messages_chars(messages),
        )
        try:
            return self._chat_text_sync_with_timeout_retry(
                router=router,
                operation="generate_chapter",
                novel_id=novel.id,
                chapter_no=chapter_no,
                messages=messages,
                temperature=0.45,
                timeout=timeout,
                web_search=web_search,
                max_tokens=settings.novel_chapter_max_tokens,
                **self._bill_kw(db, self._billing_user_id),
            )
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "generate_chapter_sync done | novel_id=%s chapter_no=%s elapsed=%.2fs",
                novel.id,
                chapter_no,
                elapsed,
            )

    async def check_and_fix_chapter(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        chapter_text: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db, model=getattr(novel, "chapter_model", None))
        messages = _check_and_fix_chapter_messages(
            novel,
            chapter_no,
            chapter_title_hint,
            memory_json,
            continuity_excerpt,
            chapter_text,
            db,
        )
        messages = self._budget_chapter_messages(messages)
        start = time.perf_counter()
        logger.info(
            "check_and_fix_chapter start | novel_id=%s chapter_no=%s msg_chars=%s text_chars=%s",
            novel.id,
            chapter_no,
            self._messages_chars(messages),
            len(chapter_text or ""),
        )
        try:
            return await self._chat_text_with_timeout_retry(
                router=router,
                operation="check_and_fix_chapter",
                novel_id=novel.id,
                chapter_no=chapter_no,
                messages=messages,
                temperature=settings.novel_consistency_check_temperature,
                web_search=False,
                timeout=settings.novel_consistency_check_timeout,
                **self._bill_kw(db, self._billing_user_id),
            )
        finally:
            elapsed = time.perf_counter() - start
            logger.info(
                "check_and_fix_chapter done | novel_id=%s chapter_no=%s elapsed=%.2fs",
                novel.id,
                chapter_no,
                elapsed,
            )

    def check_and_fix_chapter_sync(
        self,
        novel: Novel,
        chapter_no: int,
        chapter_title_hint: str,
        memory_json: str,
        continuity_excerpt: str,
        chapter_text: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db, model=getattr(novel, "chapter_model", None))
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="check_and_fix_chapter",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _check_and_fix_chapter_messages(
                    novel,
                    chapter_no,
                    chapter_title_hint,
                    memory_json,
                    continuity_excerpt,
                    chapter_text,
                    db,
                )
            ),
            temperature=settings.novel_consistency_check_temperature,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def audit_chapter_against_plan_sync(
        self,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        chapter_text: str,
        db: Any = None,
    ) -> dict[str, Any]:
        if not chapter_plan_has_guardrails(beats):
            return {"ok": True, "violations": [], "warnings": [], "skipped": True}
        router = self._router(db=db)
        raw = self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="audit_chapter_against_plan",
            novel_id="-",
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _audit_chapter_against_plan_messages(
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    chapter_text=chapter_text,
                )
            ),
            temperature=0.15,
            web_search=False,
            timeout=180.0,
            **self._bill_kw(db, self._billing_user_id),
        )
        parsed = _safe_json_dict(raw)
        if not parsed:
            try:
                repaired = json_repair_loads(raw or "{}")
                parsed = repaired if isinstance(repaired, dict) else {}
            except Exception:
                parsed = {}
        violations = _dedupe_str_list(parsed.get("violations") or [], max_items=12)
        warnings = _dedupe_str_list(parsed.get("warnings") or [], max_items=12)
        ok = bool(parsed.get("ok")) if "ok" in parsed else (len(violations) == 0)
        return {
            "ok": ok and len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "skipped": False,
        }

    def fix_chapter_to_plan_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        memory_json: str,
        continuity_excerpt: str,
        chapter_text: str,
        violations: list[str],
        db: Any = None,
    ) -> str:
        router = self._router(db=db, model=getattr(novel, "chapter_model", None))
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="fix_chapter_to_plan",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _fix_chapter_to_plan_messages(
                    novel,
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    memory_json=memory_json,
                    continuity_excerpt=continuity_excerpt,
                    chapter_text=chapter_text,
                    violations=violations,
                    db=db,
                )
            ),
            temperature=settings.novel_consistency_check_temperature,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def polish_chapter_style_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        chapter_text: str,
        db: Any = None,
    ) -> str:
        router = self._router(db=db, model=getattr(novel, "chapter_model", None))
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="polish_chapter_style",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _de_ai_chapter_messages(
                    novel,
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    chapter_text=chapter_text,
                    db=db,
                )
            ),
            temperature=0.25,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )

    def expressive_enhance_chapter_sync(
        self,
        novel: Novel,
        *,
        chapter_no: int,
        plan_title: str,
        beats: dict[str, Any],
        chapter_text: str,
        db: Any = None,
        strength: str | None = None,
    ) -> str:
        st = (strength or settings.novel_expressive_enhance_strength or "safe").strip()
        router = self._router(db=db, model=getattr(novel, "chapter_model", None))
        return self._chat_text_sync_with_timeout_retry(
            router=router,
            operation="expressive_enhance_chapter",
            novel_id=novel.id,
            chapter_no=chapter_no,
            messages=self._budget_chapter_messages(
                _expressive_enhance_chapter_messages(
                    novel,
                    chapter_no=chapter_no,
                    plan_title=plan_title,
                    beats=beats,
                    chapter_text=chapter_text,
                    strength=st,
                    db=db,
                )
            ),
            temperature=0.35,
            web_search=False,
            timeout=settings.novel_consistency_check_timeout,
            **self._bill_kw(db, self._billing_user_id),
        )
