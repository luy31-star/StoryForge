from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "vocalflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# 默认队列统一到 vocalflow，避免任务落到 celery 默认队列而无人消费
celery_app.conf.task_default_queue = "vocalflow"
celery_app.conf.task_default_exchange = "vocalflow"
celery_app.conf.task_default_routing_key = "vocalflow"
celery_app.conf.task_routes = {
    "novel.*": {"queue": "vocalflow"},
    "workflow.*": {"queue": "vocalflow"},
    "voice.*": {"queue": "vocalflow"},
    "video.*": {"queue": "vocalflow"},
}
celery_app.conf.include = [
    "app.tasks.workflow_tasks",
    "app.tasks.video_tasks",
    "app.tasks.voice_tasks",
    "app.tasks.novel_tasks",
]
celery_app.conf.beat_schedule = {
    "novel-daily-auto-chapters": {
        "task": "novel.daily_chapters",
        "schedule": crontab(
            hour=settings.novel_beat_hour,
            minute=settings.novel_beat_minute,
        ),
    },
    "novel-auto-refresh-memories": {
        "task": "novel.auto_refresh_memories",
        "schedule": crontab(
            hour=settings.novel_memory_beat_hour,
            minute=settings.novel_memory_beat_minute,
        ),
    },
}
