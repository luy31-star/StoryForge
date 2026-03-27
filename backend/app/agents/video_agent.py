from __future__ import annotations

from typing import Any

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent
from app.services.seedance_service import SeeDanceService


class SeeDanceVideoAgent(BaseAgent):
    def __init__(self, node_id: str, config: dict[str, Any]):
        super().__init__(node_id, config)
        self.seedance_service = SeeDanceService()

    async def process(self, inputs: list[AgentInput]) -> AgentOutput:
        try:
            audio_input = next(
                (inp for inp in inputs if inp.metadata.get("type") == "audio"),
                None,
            )
            image_input = next(
                (inp for inp in inputs if inp.metadata.get("type") == "image"),
                None,
            )
            if not audio_input or not image_input:
                return AgentOutput(
                    data=None,
                    success=False,
                    message="需要音频和图像输入",
                )
            task_id = await self.seedance_service.generate_video_async(
                audio_url=str(audio_input.data),
                image_url=str(image_input.data),
                config=self.config.get("video_config", {}),
            )
            return AgentOutput(
                data={"task_id": task_id, "status": "processing"},
                success=True,
                metadata={"type": "video_task"},
            )
        except Exception as e:  # noqa: BLE001
            return AgentOutput(
                data=None,
                success=False,
                message=f"视频生成失败: {e}",
            )

    async def chat(self, message: str) -> str:
        return f"SeeDance 视频节点：{message}"
