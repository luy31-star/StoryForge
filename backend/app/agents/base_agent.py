from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class AgentInput(BaseModel):
    data: Any
    metadata: dict[str, Any] = {}


class AgentOutput(BaseModel):
    data: Any
    metadata: dict[str, Any] = {}
    success: bool
    message: str | None = None


class BaseAgent(ABC):
    def __init__(self, node_id: str, config: dict[str, Any]):
        self.node_id = node_id
        self.config = config
        self.conversation_history: list[dict[str, Any]] = []

    @abstractmethod
    async def process(self, inputs: list[AgentInput]) -> AgentOutput:
        raise NotImplementedError

    @abstractmethod
    async def chat(self, message: str) -> str:
        raise NotImplementedError

    def can_auto_proceed(self) -> bool:
        return bool(self.config.get("auto_proceed", False))

    def validate_inputs(self, inputs: list[AgentInput]) -> bool:
        required = self.config.get("required_inputs", [])
        return len(inputs) >= len(required)
