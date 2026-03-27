from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="workflow.run")
def run_workflow_task(workflow_id: str) -> dict[str, str]:
    return {"workflow_id": workflow_id, "state": "stub"}
