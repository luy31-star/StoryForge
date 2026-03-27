from __future__ import annotations

from typing import Any

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class MergeAgent(BaseAgent):
    """合并音视频等输出的占位节点。"""

    async def process(self, inputs: list[AgentInput]) -> AgentOutput:
        return AgentOutput(
            data={"merged": [i.data for i in inputs]},
            success=True,
            metadata={"type": "merge"},
        )

    async def chat(self, message: str) -> str:
        return f"合并节点：{message}"
