from __future__ import annotations

from app.tasks.celery_app import celery_app


@celery_app.task(name="voice.synthesize")
def synthesize_task(text: str) -> dict[str, str]:
    return {"text": text, "state": "stub"}
