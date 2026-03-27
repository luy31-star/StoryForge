from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.services.ai302_client import AI302Client
from app.services.oss_storage import oss_storage


@dataclass
class VoiceResult:
    url: str
    duration: float | None = None
    format: str = "mp3"


class VoiceService:
    """
    语音合成：优先 302.AI OpenAI 兼容 TTS（音频再上传 OSS），
    无配置时返回占位 URL。
    """

    def __init__(self) -> None:
        self._302 = AI302Client()

    async def synthesize(
        self,
        *,
        text: str,
        model: str = "default",
        voice_settings: dict[str, Any] | None = None,
    ) -> VoiceResult:
        _ = model
        voice = "alloy"
        cfg = voice_settings or {}
        if isinstance(cfg.get("voice"), str):
            voice = cfg["voice"]

        if self._302.enabled and oss_storage.enabled:
            audio = await self._302.speech(text=text, voice=voice)
            key = f"tts/{uuid.uuid4().hex}.mp3"
            url = await oss_storage.put_bytes(
                key, audio, content_type="audio/mpeg"
            )
            return VoiceResult(url=url, duration=None, format="mp3")

        if self._302.enabled and not oss_storage.enabled:
            # 无 OSS 时无法持久化，返回说明性占位（生产务必配置 OSS）
            return VoiceResult(
                url=f"https://example.com/tts-requires-oss.mp3?q={text[:24]}",
                duration=None,
                format="mp3",
            )

        return VoiceResult(
            url=f"https://example.com/tts-placeholder.mp3?q={text[:32]}",
            duration=None,
        )

    async def blend_voices(
        self,
        *,
        references: list[str],
        ratios: list[float],
        text: str,
    ) -> VoiceResult:
        _ = references, ratios
        return await self.synthesize(text=text, model="blend", voice_settings=None)
