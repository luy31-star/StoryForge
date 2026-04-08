from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.llm_router import LLMRouter


class GeminiService:
    """
    工作流等场景的文本生成：统一走 302.AI OpenAI 兼容 Chat（与小说模块一致）。
    需配置 AI302_API_KEY。
    """

    async def generate_text(
        self,
        *,
        system_prompt: str | None,
        messages: list[dict[str, str]],
        model: str = "gemini-2.0-flash",
    ) -> str:
        if not settings.ai302_api_key:
            last = messages[-1]["content"] if messages else ""
            return (
                "[未配置 AI] 请在后端环境变量中设置 AI302_API_KEY（302.AI 中转）。"
                f"用户输入摘要：{last[:200]}"
            )

        msgs: list[dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                role = "user"
            msgs.append({"role": role, "content": m.get("content", "")})

        router = LLMRouter(model=model, user_id=None, db=None)
        return await router.chat_text(
            messages=msgs,
        )
