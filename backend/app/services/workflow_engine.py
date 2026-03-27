from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.workflow import Workflow


class WorkflowEngine:
    """工作流执行引擎占位：后续接入 Celery 与真实节点调度。"""

    _status: dict[str, dict[str, Any]] = {}

    @classmethod
    def get_status(cls, workflow_id: str) -> dict[str, Any]:
        return cls._status.get(
            workflow_id, {"workflow_id": workflow_id, "state": "idle"}
        )

    async def execute_async(
        self,
        db: Session | None,
        workflow_id: str,
        start_node_id: str | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        nodes: list[Any] = []
        wf = db.get(Workflow, workflow_id) if db else None
        if wf:
            try:
                nodes = json.loads(wf.nodes_json or "[]")
            except json.JSONDecodeError:
                nodes = []
        self.__class__._status[workflow_id] = {
            "workflow_id": workflow_id,
            "task_id": task_id,
            "state": "started",
            "start_node_id": start_node_id,
            "node_count": len(nodes),
        }
        return task_id

    async def execute_demo(self) -> str:
        return await self.execute_async(None, "demo-workflow", None)
