from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.workflow import Workflow
from app.services.workflow_engine import WorkflowEngine

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


class WorkflowCreate(BaseModel):
    name: str = "Untitled"
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []


@router.post("/create")
async def create_workflow(
    workflow_data: WorkflowCreate, db: Session = Depends(get_db)
) -> dict[str, str]:
    wf = Workflow(
        name=workflow_data.name,
        nodes_json=json.dumps(workflow_data.nodes),
        edges_json=json.dumps(workflow_data.edges),
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return {"id": wf.id, "status": "created"}


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {
        "id": wf.id,
        "name": wf.name,
        "nodes": json.loads(wf.nodes_json or "[]"),
        "edges": json.loads(wf.edges_json or "[]"),
    }


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    start_node_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    engine = WorkflowEngine()
    task_id = await engine.execute_async(db, workflow_id, start_node_id)
    return {"task_id": task_id, "status": "started"}


@router.get("/{workflow_id}/status")
async def get_workflow_status(workflow_id: str) -> dict[str, Any]:
    return WorkflowEngine.get_status(workflow_id)


@router.post("/execute-demo")
async def execute_demo() -> dict[str, str]:
    """演示执行，供前端试连。"""
    engine = WorkflowEngine()
    task_id = await engine.execute_demo()
    return {"task_id": task_id, "status": "started"}
