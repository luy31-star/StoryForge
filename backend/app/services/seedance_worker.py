from __future__ import annotations

import json
from typing import Any

import httpx
import redis

from app.core.config import settings


def _redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def _key(task_id: str) -> str:
    return f"vocalflow:seedance:{task_id}"


def run_seedance_job(task_id: str) -> dict[str, Any]:
    """
    Celery 同步任务：若配置了 AI302_VIDEO_SUBMIT_PATH，则向 302 提交视频任务；
    具体 body 需按你在 302 控制台选用的「即梦 / SeeDance / 视频生成」接口调整。
    """
    r = _redis()
    raw = r.get(_key(task_id))
    meta: dict[str, Any] = json.loads(raw) if raw else {}

    path = (settings.ai302_video_submit_path or "").strip()
    if not path or not settings.ai302_api_key:
        meta["status"] = "pending_config"
        meta["message"] = "请配置 AI302_API_KEY 与 AI302_VIDEO_SUBMIT_PATH（见 doc.302.ai 所选视频接口）"
        r.set(_key(task_id), json.dumps(meta), ex=86400)
        return meta

    base = settings.ai302_base_url.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base}{path}"
    payload = {
        "audio_url": meta.get("audio_url"),
        "image_url": meta.get("image_url"),
        "config": meta.get("config") or {},
    }
    try:
        resp = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.ai302_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
        meta["status"] = "submitted"
        meta["provider_response"] = data
        if isinstance(data, dict) and data.get("task_id"):
            meta["provider_task_id"] = data.get("task_id")
        if isinstance(data, dict) and data.get("video_url"):
            meta["video_url"] = data.get("video_url")
    except Exception as e:  # noqa: BLE001
        meta["status"] = "failed"
        meta["error"] = str(e)
    r.set(_key(task_id), json.dumps(meta), ex=86400)
    return meta
