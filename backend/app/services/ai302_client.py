from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        body: dict[str, Any] = {
            "model": model or settings.ai302_chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if web_search:
            body["web-search"] = True
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers=self._headers(), json=body)
                r.raise_for_status()
                data = r.json()
        except httpx.TimeoutException:
            elapsed = time.perf_counter() - start
            logger.exception(
                "AI302 chat timeout after %.2fs | model=%s | web_search=%s | timeout=%.1fs",
                elapsed,
                body.get("model"),
                web_search,
                timeout,
            )
            raise
        except httpx.HTTPStatusError as e:
            elapsed = time.perf_counter() - start
            resp_text = (e.response.text or "")[:1200]
            logger.exception(
                "AI302 chat http error after %.2fs | status=%s | model=%s | web_search=%s | body=%s",
                elapsed,
                e.response.status_code,
                body.get("model"),
                web_search,
                resp_text,
            )
            raise
        except httpx.RequestError:
            elapsed = time.perf_counter() - start
            logger.exception(
                "AI302 chat request error after %.2fs | model=%s | web_search=%s",
                elapsed,
                body.get("model"),
                web_search,
            )
            raise
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
        body: dict[str, Any] = {
            "model": model or settings.ai302_chat_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if web_search:
            body["web-search"] = True

        start = time.perf_counter()
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
        except Exception:
            elapsed = time.perf_counter() - start
            logger.exception(
                "AI302 chat(stream) failed after %.2fs | model=%s web_search=%s",
                elapsed,
                body.get("model"),
                web_search,
            )
            raise

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
        body: dict[str, Any] = {
            "model": model or settings.ai302_chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if web_search:
            body["web-search"] = True
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, headers=self._headers(), json=body)
                r.raise_for_status()
                data = r.json()
        except httpx.TimeoutException:
            elapsed = time.perf_counter() - start
            logger.exception(
                "AI302 chat(sync) timeout after %.2fs | model=%s | web_search=%s | timeout=%.1fs",
                elapsed,
                body.get("model"),
                web_search,
                timeout,
            )
            raise
        except httpx.HTTPStatusError as e:
            elapsed = time.perf_counter() - start
            resp_text = (e.response.text or "")[:1200]
            logger.exception(
                "AI302 chat(sync) http error after %.2fs | status=%s | model=%s | web_search=%s | body=%s",
                elapsed,
                e.response.status_code,
                body.get("model"),
                web_search,
                resp_text,
            )
            raise
        except httpx.RequestError:
            elapsed = time.perf_counter() - start
            logger.exception(
                "AI302 chat(sync) request error after %.2fs | model=%s | web_search=%s",
                elapsed,
                body.get("model"),
                web_search,
            )
            raise
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
