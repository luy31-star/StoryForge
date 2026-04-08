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

logger = logging.getLogger(__name__)

_MISSING_CHAT_MODEL = (
    "未配置模型：请在管理后台「模型计价」中添加已启用模型并设置全站默认，"
    "或在调用处传入 model。"
)


def _require_chat_model(model: str | None) -> str:
    m = (model or "").strip()
    if not m:
        raise RuntimeError(_MISSING_CHAT_MODEL)
    return m


class AI302Client:
    """302.AI 中转：OpenAI 兼容 Chat、TTS 等（文档：https://doc.302.ai/ ）。"""

    def __init__(self) -> None:
        self._base = settings.ai302_base_url.rstrip("/")
        self._key = settings.ai302_api_key

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

    async def chat_completions(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        web_search: bool = False,
        timeout: float = 120.0,
    ) -> str:
        """OpenAI 兼容 POST /chat/completions，返回 assistant 文本。

        web_search=True 时附加 302「联网搜索」能力（见 https://doc.302.ai/260112819e0 ）。
        """
        url = f"{self._base}/chat/completions"
        resolved = _require_chat_model(model)
        body: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
        }
        if web_search:
            body["web-search"] = True
        logger.info("AI302 Request: POST %s | model=%s", url, resolved)
        start = time.perf_counter()

        max_retries = 3
        data = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, headers=self._headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
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
                        "AI302 chat attempt %d failed (%s), retrying in %.2fs... | model=%s",
                        attempt + 1, e, wait, resolved
                    )
                    await asyncio.sleep(wait)
                    continue

                # Handle failure after retries
                if isinstance(e, httpx.TimeoutException):
                    elapsed = time.perf_counter() - start
                    logger.exception(
                        "AI302 chat timeout after %d attempts and %.2fs | model=%s",
                        attempt + 1, elapsed, resolved
                    )
                elif isinstance(e, httpx.HTTPStatusError):
                    elapsed = time.perf_counter() - start
                    resp_text = (e.response.text or "")[:1200]
                    logger.exception(
                        "AI302 chat http error after %d attempts and %.2fs | status=%s | model=%s | resp=%s",
                        attempt + 1, elapsed, e.response.status_code, resolved, resp_text
                    )
                else:
                    elapsed = time.perf_counter() - start
                    logger.exception(
                        "AI302 chat request error after %d attempts and %.2fs | model=%s",
                        attempt + 1, elapsed, resolved
                    )
                raise

        if data is None:
            raise RuntimeError("AI302 chat failed to return data")

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return json.dumps(data, ensure_ascii=False)

    async def chat_completions_stream(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        web_search: bool = False,
        timeout: float = 300.0,
    ) -> AsyncIterator[dict[str, str]]:
        """
        OpenAI 兼容流式输出。
        产出:
        - {"type": "think", "delta": "..."}
        - {"type": "text", "delta": "..."}
        """
        url = f"{self._base}/chat/completions"
        resolved = _require_chat_model(model)
        body: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if web_search:
            body["web-search"] = True

        logger.info("AI302 Request (Stream): POST %s | model=%s", url, resolved)
        start = time.perf_counter()
        max_retries = 3
        try:
            for attempt in range(max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        async with client.stream(
                            "POST", url, headers=self._headers(), json=body
                        ) as resp:
                            resp.raise_for_status()
                            async for line in resp.aiter_lines():
                                if not line:
                                    continue
                                if not line.startswith("data:"):
                                    continue
                                payload = line[5:].strip()
                                if not payload:
                                    continue
                                if payload == "[DONE]":
                                    break
                                try:
                                    evt = json.loads(payload)
                                except json.JSONDecodeError:
                                    continue
                                delta = (
                                    (evt.get("choices") or [{}])[0].get("delta") or {}
                                    if isinstance(evt, dict)
                                    else {}
                                )
                                if not isinstance(delta, dict):
                                    continue
                                think = delta.get("reasoning_content")
                                if isinstance(think, str) and think:
                                    yield {"type": "think", "delta": think}
                                txt = delta.get("content")
                                if isinstance(txt, str) and txt:
                                    yield {"type": "text", "delta": txt}
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
                            "AI302 chat stream attempt %d failed (%s), retrying in %.2fs... | model=%s",
                            attempt + 1, e, wait, resolved
                        )
                        await asyncio.sleep(wait)
                        continue

                    elapsed = time.perf_counter() - start
                    logger.exception(
                        "AI302 chat stream failed after %d attempts and %.2fs | model=%s web_search=%s",
                        attempt + 1,
                        elapsed,
                        resolved,
                        web_search,
                    )
                    raise
        finally:
            pass

    def chat_completions_sync(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        timeout: float = 300.0,
        web_search: bool = False,
    ) -> str:
        """供 Celery 等同步环境调用。"""
        url = f"{self._base}/chat/completions"
        resolved = _require_chat_model(model)
        body: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "temperature": temperature,
        }
        if web_search:
            body["web-search"] = True
        logger.info("AI302 Request: POST %s | model=%s", url, resolved)
        start = time.perf_counter()

        max_retries = 3
        data = None
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    r = client.post(url, headers=self._headers(), json=body)
                    r.raise_for_status()
                    data = r.json()
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
                        "AI302 chat(sync) attempt %d failed (%s), retrying in %.2fs... | model=%s",
                        attempt + 1, e, wait, resolved
                    )
                    time.sleep(wait)
                    continue

                if isinstance(e, httpx.TimeoutException):
                    elapsed = time.perf_counter() - start
                    logger.exception(
                        "AI302 chat(sync) timeout after %d attempts and %.2fs | model=%s",
                        attempt + 1, elapsed, resolved
                    )
                elif isinstance(e, httpx.HTTPStatusError):
                    elapsed = time.perf_counter() - start
                    resp_text = (e.response.text or "")[:1200]
                    logger.exception(
                        "AI302 chat(sync) http error after %d attempts and %.2fs | status=%s | model=%s | resp=%s",
                        attempt + 1, elapsed, e.response.status_code, resolved, resp_text
                    )
                else:
                    elapsed = time.perf_counter() - start
                    logger.exception(
                        "AI302 chat(sync) request error after %d attempts and %.2fs | model=%s",
                        attempt + 1, elapsed, resolved
                    )
                raise

        if data is None:
            raise RuntimeError("AI302 chat(sync) failed to return data")

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return json.dumps(data, ensure_ascii=False)

    async def speech(
        self,
        *,
        text: str,
        voice: str = "alloy",
        model: str | None = None,
        response_format: str = "mp3",
    ) -> bytes:
        """OpenAI 兼容语音合成 POST {ai302_tts_path}，返回音频二进制。"""
        path = settings.ai302_tts_path.strip() or "/audio/speech"
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self._base}{path}"
        body = {
            "model": model or settings.ai302_tts_model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            r.raise_for_status()
            return r.content

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """通用 JSON POST，用于 302 上非标准路径（如部分视频异步任务）。"""
        p = path.strip()
        if not p.startswith("/"):
            p = "/" + p
        url = f"{self._base}{p}"
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, headers=self._headers(), json=payload)
            r.raise_for_status()
            if r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
            return {"raw": r.text}
