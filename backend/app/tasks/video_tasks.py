from __future__ import annotations

from app.services.seedance_worker import run_seedance_job
from app.tasks.celery_app import celery_app


@celery_app.task(name="video.seedance")
def seedance_task(task_id: str) -> dict[str, str]:
    """异步执行：真实 302 视频提交逻辑见 seedance_worker。"""
    run_seedance_job(task_id)
    return {"task_id": task_id, "state": "processed"}
