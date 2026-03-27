from __future__ import annotations

import json
import uuid
from typing import Any

import redis
from fastapi import UploadFile

from app.core.config import settings

_redis_client: redis.Redis | None = None
_redis_available: bool | None = None


def _get_redis() -> redis.Redis | None:
    global _redis_client, _redis_available
    if _redis_available is False:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        _redis_client.ping()
        _redis_available = True
        return _redis_client
    except redis.exceptions.RedisError:
        _redis_available = False
        return None


class SeeDanceService:
    """
    SeeDance / 视频生成：任务元数据优先存 Redis，供 Celery 调用 302 视频接口。
    无 Redis 时退回到进程内字典（仅单机调试）。
    """

    _local_tasks: dict[str, dict[str, Any]] = {}

    def _key(self, task_id: str) -> str:
        return f"vocalflow:seedance:{task_id}"

    def _set_meta(self, task_id: str, meta: dict[str, Any]) -> None:
        r = _get_redis()
        if r:
            r.set(self._key(task_id), json.dumps(meta), ex=86400)
        else:
            self._local_tasks[task_id] = meta

    def _get_meta(self, task_id: str) -> dict[str, Any] | None:
        r = _get_redis()
        if r:
            raw = r.get(self._key(task_id))
            if raw:
                return json.loads(raw)
            return None
        return self._local_tasks.get(task_id)

    async def generate_video_async(
        self,
        *,
        audio_url: str | None = None,
        image_url: str | None = None,
        audio: UploadFile | None = None,
        image: UploadFile | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        meta: dict[str, Any] = {
            "status": "queued",
            "audio_url": audio_url,
            "image_url": image_url,
            "filenames": (
                audio.filename if audio else None,
                image.filename if image else None,
            ),
            "config": config or {},
        }
        self._set_meta(task_id, meta)

        try:
            from app.tasks.video_tasks import seedance_task

            seedance_task.delay(task_id)
        except Exception:  # noqa: BLE001
            meta["status"] = "queued_no_worker"
            self._set_meta(task_id, meta)

        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._get_meta(task_id)
