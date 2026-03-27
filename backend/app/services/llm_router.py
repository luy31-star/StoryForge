from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from app.core.config import settings
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.runtime_llm_config import get_runtime_llm_config

logger = logging.getLogger(__name__)

LLMProvider = Literal["ai302", "custom"]


def _join_url(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return b + p


def _openai_chat_url(base: str) -> str:
    """
    兼容：
    - base = https://api.302.ai/v1  -> /chat/completions
    - base = http://proxy.xxx.com  -> /v1/chat/completions
    """
    b = (base or "").rstrip("/")
    if b.endswith("/v1"):
        return _join_url(b, "/chat/completions")
    return _join_url(b, "/v1/chat/completions")


def _ai302_kimi_messages_url(ai302_base: str) -> str:
    # 302 文档：/v1/messages；settings.ai302_base_url 默认已含 /v1
    b = (ai302_base or "").rstrip("/")
    if b.endswith("/v1"):
        return _join_url(b, "/messages")
    return _join_url(b, "/v1/messages")


def _safe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


class LLMRouter:
    """
    统一大模型路由：
    - provider=ai302：默认 OpenAI 兼容 /chat/completions；若 model 以 kimi- 开头则走 /messages（Kimi）。
    - provider=custom：走自建 OpenAI 兼容代理（默认 /v1/chat/completions）。

    说明：
    - Doubao：按 302 的 OpenAI 兼容 /chat/completions 调用，model 传 Doubao-Seed-2.0-pro（参考 302 文档）。
    - Kimi：按 302 的 /messages 调用（参考 302 文档）。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        model: str | None = None,
        db: Session | None = None,
    ) -> None:
        close_db = False
        use_db = db
        if use_db is None:
            use_db = SessionLocal()
            close_db = True
        try:
            rcfg = get_runtime_llm_config(use_db)
        finally:
            if close_db and use_db is not None:
                use_db.close()
        base_provider = provider or rcfg.provider or "ai302"
        base_model = model if model is not None else rcfg.model
        self.provider: LLMProvider = (base_provider or "ai302")  # type: ignore[assignment]
        self.model = (base_model or "").strip()

    def _ai302_headers(self) -> dict[str, str]:
        if not settings.ai302_api_key:
            raise RuntimeError("未配置 AI302_API_KEY")
        return {
            "Authorization": f"Bearer {settings.ai302_api_key}",
            "Content-Type": "application/json",
        }

    def _custom_headers(self) -> dict[str, str]:
        if not settings.custom_llm_api_key:
            raise RuntimeError("未配置 CUSTOM_LLM_API_KEY")
        return {
            "Authorization": f"Bearer {settings.custom_llm_api_key}",
            "Content-Type": "application/json",
        }

    def _resolve_model(self, *, fallback: str) -> str:
        return self.model or fallback

    async def chat_text(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        timeout: float = 600.0,
        web_search: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        start = time.perf_counter()

        if self.provider == "custom":
            model = self._resolve_model(fallback=settings.custom_llm_model)
            url = _openai_chat_url(settings.custom_llm_base_url)
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens is not None:
                body["max_tokens"] = max_tokens
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, headers=self._custom_headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
            except Exception:
                logger.exception("custom llm failed | url=%s model=%s", url, model)
                raise
            try:
                return data["choices"][0]["message"]["content"]
            except Exception:
                return json.dumps(data, ensure_ascii=False)

        # provider == ai302
        model = self._resolve_model(fallback=settings.ai302_novel_model)
        if model.lower().startswith("kimi-"):
            # Kimi messages API (302)
            url = _ai302_kimi_messages_url(settings.ai302_base_url)
            body = {
                "model": model,
                "messages": messages,
                # 302 文档要求 max_tokens；这里给一个足够大默认值，避免被拒
                "max_tokens": max_tokens if max_tokens is not None else 4096,
                "temperature": temperature,
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, headers=self._ai302_headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
            except Exception:
                logger.exception("ai302 kimi failed | url=%s model=%s", url, model)
                raise
            # content: [{type:"text", text:"..."}]
            try:
                content = data.get("content")
                if isinstance(content, list):
                    texts: list[str] = []
                    for x in content:
                        if isinstance(x, dict) and x.get("type") == "text":
                            t = x.get("text")
                            if isinstance(t, str) and t:
                                texts.append(t)
                    if texts:
                        return "".join(texts)
                # fallback
                return json.dumps(data, ensure_ascii=False)
            finally:
                elapsed = time.perf_counter() - start
                logger.info("ai302 kimi done | elapsed=%.2fs", elapsed)

        # 302 OpenAI compatible chat completions (Doubao 也在这里)
        url = _join_url(settings.ai302_base_url, "/chat/completions")
        body2: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body2["max_tokens"] = max_tokens
        if web_search:
            body2["web-search"] = True
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers=self._ai302_headers(), json=body2)
                r.raise_for_status()
                data2 = r.json()
        except Exception:
            logger.exception("ai302 chat failed | url=%s model=%s", url, model)
            raise
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
    ) -> AsyncIterator[dict[str, str]]:
        """
        流式输出兼容你现有前端 SSE 协议：
        - {"type":"think","delta":"..."} / {"type":"text","delta":"..."}

        当前实现：
        - ai302 + OpenAI compatible：支持流式
        - ai302 + kimi(messages)：文档也支持 stream，但响应格式不同，这里先降级为非流式整段返回
        - custom：先降级为非流式整段返回
        """
        # custom 降级
        if self.provider == "custom":
            txt = await self.chat_text(
                messages=messages,
                temperature=temperature,
                timeout=timeout,
                web_search=web_search,
                max_tokens=max_tokens,
            )
            yield {"type": "text", "delta": txt}
            return

        model = self._resolve_model(fallback=settings.ai302_novel_model)
        if model.lower().startswith("kimi-"):
            txt = await self.chat_text(
                messages=messages,
                temperature=temperature,
                timeout=timeout,
                web_search=web_search,
                max_tokens=max_tokens,
            )
            yield {"type": "text", "delta": txt}
            return

        url = _join_url(settings.ai302_base_url, "/chat/completions")
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if web_search:
            body["web-search"] = True

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
                    delta = (evt.get("choices") or [{}])[0].get("delta") or {}
                    if not isinstance(delta, dict):
                        continue
                    think = delta.get("reasoning_content")
                    if isinstance(think, str) and think:
                        yield {"type": "think", "delta": think}
                    txt = delta.get("content")
                    if isinstance(txt, str) and txt:
                        yield {"type": "text", "delta": txt}

    def chat_text_sync(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        timeout: float = 600.0,
        web_search: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        start = time.perf_counter()

        if self.provider == "custom":
            model = self._resolve_model(fallback=settings.custom_llm_model)
            url = _openai_chat_url(settings.custom_llm_base_url)
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens is not None:
                body["max_tokens"] = max_tokens
            try:
                with httpx.Client(timeout=timeout) as client:
                    r = client.post(url, headers=self._custom_headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
            except Exception:
                logger.exception("custom llm(sync) failed | url=%s model=%s", url, model)
                raise
            try:
                return data["choices"][0]["message"]["content"]
            except Exception:
                return json.dumps(data, ensure_ascii=False)

        model = self._resolve_model(fallback=settings.ai302_novel_model)
        if model.lower().startswith("kimi-"):
            url = _ai302_kimi_messages_url(settings.ai302_base_url)
            body = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens if max_tokens is not None else 4096,
                "temperature": temperature,
            }
            try:
                with httpx.Client(timeout=timeout) as client:
                    r = client.post(url, headers=self._ai302_headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
            except Exception:
                logger.exception("ai302 kimi(sync) failed | url=%s model=%s", url, model)
                raise
            try:
                content = data.get("content")
                if isinstance(content, list):
                    texts: list[str] = []
                    for x in content:
                        if isinstance(x, dict) and x.get("type") == "text":
                            t = x.get("text")
                            if isinstance(t, str) and t:
                                texts.append(t)
                    if texts:
                        return "".join(texts)
                return json.dumps(data, ensure_ascii=False)
            finally:
                elapsed = time.perf_counter() - start
                logger.info("ai302 kimi(sync) done | elapsed=%.2fs", elapsed)

        url = _join_url(settings.ai302_base_url, "/chat/completions")
        body2: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body2["max_tokens"] = max_tokens
        if web_search:
            body2["web-search"] = True
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, headers=self._ai302_headers(), json=body2)
                r.raise_for_status()
                data2 = r.json()
        except Exception:
            logger.exception("ai302 chat(sync) failed | url=%s model=%s", url, model)
            raise
        try:
            return data2["choices"][0]["message"]["content"]
        except Exception:
            return json.dumps(data2, ensure_ascii=False)
        finally:
            elapsed = time.perf_counter() - start
            logger.info("ai302 chat(sync) done | elapsed=%.2fs", elapsed)

