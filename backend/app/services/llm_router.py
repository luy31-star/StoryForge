from __future__ import annotations

import json
import logging
import time
import random
import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.runtime_llm_config import get_runtime_llm_config

logger = logging.getLogger(__name__)


def _apply_llm_billing(
    billing_db: Session | None,
    billing_user_id: str | None,
    model: str,
    response_json: dict[str, Any],
) -> None:
    from app.services.billing_service import (
        consume_points_for_llm,
        extract_usage_from_response,
    )

    usage = extract_usage_from_response(response_json)
    if not usage:
        logger.info("LLM Usage: [No usage data in response] | model=%s", model)
        return

    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    tt = usage.get("total_tokens", 0)

    if not billing_db or not billing_user_id:
        logger.info(
            "LLM Usage: prompt=%d, completion=%d, total=%d | model=%s [Billing skipped: no user/db]",
            pt, ct, tt, model
        )
        return

    try:
        cost = consume_points_for_llm(
            billing_db,
            user_id=billing_user_id,
            model_id=model,
            usage=usage,
        )
        logger.info(
            "LLM Usage: prompt=%d, completion=%d, total=%d | cost=%d points | model=%s | user_id=%s",
            pt, ct, tt, cost, model, billing_user_id
        )
    except RuntimeError as e:
        logger.warning("billing failed: %s | usage=%s | model=%s", e, usage, model)
        raise


def _join_url(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return b + p


def _safe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


class LLMRouter:
    """
    仅通过 302.AI OpenAI 兼容接口调用大模型：POST {AI302_BASE_URL}/chat/completions
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        user_id: str | None = None,
        db: Session | None = None,
    ) -> None:
        close_db = False
        use_db = db
        if use_db is None:
            use_db = SessionLocal()
            close_db = True
        try:
            rcfg = get_runtime_llm_config(use_db, user_id=user_id)
        finally:
            if close_db and use_db is not None:
                use_db.close()
        base_model = model if model is not None else rcfg.model
        self.model = (base_model or "").strip()

    def _ai302_headers(self) -> dict[str, str]:
        if not settings.ai302_api_key:
            raise RuntimeError("未配置 AI302_API_KEY")
        return {
            "Authorization": f"Bearer {settings.ai302_api_key}",
            "Content-Type": "application/json",
        }

    _MISSING_MODEL_MSG = (
        "未配置可用模型：请在管理后台「模型计价」中至少添加一个已启用模型，"
        "并在「全局 LLM 设置」中指定全站默认模型。"
    )

    def _require_model(self) -> str:
        m = (self.model or "").strip()
        if not m:
            raise RuntimeError(self._MISSING_MODEL_MSG)
        return m

    async def chat_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        timeout: float = 600.0,
        web_search: bool = False,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        billing_user_id: str | None = None,
        billing_db: Session | None = None,
    ) -> str:
        start = time.perf_counter()

        if billing_db and billing_user_id:
            from app.services.billing_service import assert_sufficient_balance

            assert_sufficient_balance(billing_db, billing_user_id, min_points=1)

        model = self._require_model()
        url = _join_url(settings.ai302_base_url, "/chat/completions")
        logger.info("LLM Request: POST %s | model=%s | user_id=%s", url, model, billing_user_id)
        body2: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body2["max_tokens"] = max_tokens
        if web_search:
            body2["web-search"] = True
        if response_format is not None:
            body2["response_format"] = response_format

        max_retries = 3
        data2 = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, headers=self._ai302_headers(), json=body2)
                    r.raise_for_status()
                    data2 = r.json()
                    break
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                is_transient = False
                if isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code in (429, 500, 502, 503, 504):
                        is_transient = True
                else:
                    is_transient = True

                if is_transient and attempt < max_retries:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "ai302 chat attempt %d failed (%s), retrying in %.2fs... | model=%s",
                        attempt + 1, e, wait, model
                    )
                    await asyncio.sleep(wait)
                    continue

                logger.exception("ai302 chat failed after %d attempts | url=%s model=%s", attempt + 1, url, model)
                raise

        if data2 is None:
            raise RuntimeError("ai302 chat failed to return data")

        _apply_llm_billing(billing_db, billing_user_id, model, data2)
        try:
            return data2["choices"][0]["message"]["content"]
        except Exception:
            return json.dumps(data2, ensure_ascii=False)
        finally:
            elapsed = time.perf_counter() - start
            logger.info("ai302 chat done | elapsed=%.2fs", elapsed)

    async def chat_text_stream(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        timeout: float = 600.0,
        web_search: bool = False,
        max_tokens: int | None = None,
        billing_user_id: str | None = None,
        billing_db: Session | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        """
        流式输出（302 OpenAI 兼容 SSE），含 usage 时计费。
        """
        if billing_db and billing_user_id:
            from app.services.billing_service import assert_sufficient_balance

            assert_sufficient_balance(billing_db, billing_user_id, min_points=1)

        model = self._require_model()

        url = _join_url(settings.ai302_base_url, "/chat/completions")
        logger.info("LLM Request (Stream): POST %s | model=%s | user_id=%s", url, model, billing_user_id)
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if web_search:
            body["web-search"] = True

        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                collected_usage: dict[str, Any] | None = None
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("POST", url, headers=self._ai302_headers(), json=body) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if not payload:
                                continue
                            if payload == "[DONE]":
                                break
                            evt = _safe_json_loads(payload)
                            if not isinstance(evt, dict):
                                continue
                            if "usage" in evt and evt["usage"]:
                                collected_usage = evt["usage"]
                            delta = (evt.get("choices") or [{}])[0].get("delta") or {}
                            if not isinstance(delta, dict):
                                continue
                            think = delta.get("reasoning_content")
                            if isinstance(think, str) and think:
                                yield {"type": "think", "delta": think}
                            txt = delta.get("content")
                            if isinstance(txt, str) and txt:
                                yield {"type": "text", "delta": txt}

                if collected_usage is not None:
                    _apply_llm_billing(billing_db, billing_user_id, model, {"usage": collected_usage})
                return  # 成功完成

            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                is_transient = False
                if isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code in (429, 500, 502, 503, 504):
                        is_transient = True
                else:
                    is_transient = True

                if is_transient and attempt < max_retries:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "ai302 chat stream attempt %d failed (%s), retrying in %.2fs... | model=%s",
                        attempt + 1, e, wait, model
                    )
                    await asyncio.sleep(wait)
                    continue

                logger.exception("ai302 chat stream failed after %d attempts | url=%s model=%s", attempt + 1, url, model)
                raise

    def chat_text_sync(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        timeout: float = 600.0,
        web_search: bool = False,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        billing_user_id: str | None = None,
        billing_db: Session | None = None,
    ) -> str:
        start = time.perf_counter()

        if billing_db and billing_user_id:
            from app.services.billing_service import assert_sufficient_balance

            assert_sufficient_balance(billing_db, billing_user_id, min_points=1)

        model = self._require_model()

        url = _join_url(settings.ai302_base_url, "/chat/completions")
        logger.info("LLM Request (Sync): POST %s | model=%s | user_id=%s", url, model, billing_user_id)
        body2: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body2["max_tokens"] = max_tokens
        if web_search:
            body2["web-search"] = True
        if response_format is not None:
            body2["response_format"] = response_format

        max_retries = 3
        data2 = None
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    r = client.post(url, headers=self._ai302_headers(), json=body2)
                    r.raise_for_status()
                    data2 = r.json()
                    break
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                is_transient = False
                if isinstance(e, httpx.HTTPStatusError):
                    if e.response.status_code in (429, 500, 502, 503, 504):
                        is_transient = True
                else:
                    is_transient = True

                if is_transient and attempt < max_retries:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "ai302 chat(sync) attempt %d failed (%s), retrying in %.2fs... | model=%s",
                        attempt + 1, e, wait, model
                    )
                    time.sleep(wait)
                    continue

                logger.exception("ai302 chat(sync) failed after %d attempts | url=%s model=%s", attempt + 1, url, model)
                raise

        if data2 is None:
            raise RuntimeError("ai302 chat(sync) failed to return data")

        _apply_llm_billing(billing_db, billing_user_id, model, data2)
        try:
            return data2["choices"][0]["message"]["content"]
        except Exception:
            return json.dumps(data2, ensure_ascii=False)
        finally:
            elapsed = time.perf_counter() - start
            logger.info("ai302 chat(sync) done | elapsed=%.2fs", elapsed)
