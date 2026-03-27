from __future__ import annotations

from datetime import datetime
from typing import Any

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent
from app.services.voice_service import VoiceService


class VoiceSynthesisAgent(BaseAgent):
    def __init__(self, node_id: str, config: dict[str, Any]):
        super().__init__(node_id, config)
        self.voice_service = VoiceService()
        self.current_text = ""
        self.voice_model = config.get("voice_model", "default")

    async def process(self, inputs: list[AgentInput]) -> AgentOutput:
        try:
            text_input = next(
                (inp for inp in inputs if inp.metadata.get("type") == "text"),
                None,
            )
            if not text_input:
                return AgentOutput(
                    data=None,
                    success=False,
                    message="需要文本输入",
                )
            self.current_text = str(text_input.data)
            result = await self.voice_service.synthesize(
                text=self.current_text,
                model=self.voice_model,
                voice_settings=self.config.get("voice_settings", {}),
            )
            return AgentOutput(
                data={
                    "audio_url": result.url,
                    "duration": result.duration,
                    "format": result.format,
                },
                success=True,
                metadata={"type": "audio", "duration": result.duration},
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(
                data=None,
                success=False,
                message=f"语音合成失败: {e}",
            )

    async def chat(self, message: str) -> str:
        self.conversation_history.append(
            {
                "role": "user",
                "content": message,
                "timestamp": datetime.now(),
            }
        )
        if "更换声音" in message:
            response = "请告诉我您想要的声音类型，可选：甜美、磁性、活力、温柔"
        elif "调整语速" in message:
            response = "请指定语速：慢速(0.5-0.8)、正常(0.9-1.1)、快速(1.2-1.5)"
        elif "预览" in message:
            if self.current_text:
                preview = await self.voice_service.synthesize(
                    text=self.current_text[:50] + "...",
                    model=self.voice_model,
                    voice_settings={},
                )
                response = f"语音预览已生成: {preview.url}"
            else:
                response = "请先提供要转换的文本"
        else:
            response = (
                "我是语音合成助手。您可以：\n"
                "1. 更换声音类型\n2. 调整语速\n3. 预览合成效果\n4. 直接输入要转换的文本"
            )
        self.conversation_history.append(
            {
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now(),
            }
        )
        return response
