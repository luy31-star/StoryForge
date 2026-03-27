from __future__ import annotations

from typing import Any

from app.agents.base_agent import AgentInput, AgentOutput, BaseAgent


class InputAgent(BaseAgent):
    """输入类节点占位。"""

    async def process(self, inputs: list[AgentInput]) -> AgentOutput:
        _ = inputs
        return AgentOutput(
            data=self.config.get("content"),
            success=True,
            metadata={"type": self.config.get("input_type", "text")},
        )

    async def chat(self, message: str) -> str:
        return f"输入节点：{message}"
