from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.ai302_client import AI302Client


class GeminiService:
    """
    文本生成：优先 302.AI OpenAI 兼容 Chat（https://doc.302.ai/），
    否则直连 Google Gemini（需 GEMINI_API_KEY），否则占位。
    """

    def __init__(self) -> None:
        self._302 = AI302Client()

    async def generate_text(
        self,
        *,
        system_prompt: str | None,
        messages: list[dict[str, str]],
        model: str = "gemini-2.0-flash",
    ) -> str:
        if self._302.enabled:
            msgs: list[dict[str, str]] = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            for m in messages:
                role = m.get("role", "user")
                if role not in ("user", "assistant", "system"):
                    role = "user"
                msgs.append({"role": role, "content": m.get("content", "")})
            return await self._302.chat_completions(
                messages=msgs,
                model=model or settings.ai302_chat_model,
            )

        if not settings.gemini_api_key:
            last = messages[-1]["content"] if messages else ""
            return (
                f"[未配置 AI] 请设置 AI302_API_KEY（302.AI）或 GEMINI_API_KEY。"
                f"用户输入摘要：{last[:200]}"
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload: dict = {
            "contents": [
                {"role": "user", "parts": [{"text": m["content"]}]}
                for m in messages
                if m.get("role") == "user"
            ],
        }
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                url,
                params={"key": settings.gemini_api_key},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            return str(data)
