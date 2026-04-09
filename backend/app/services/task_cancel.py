from __future__ import annotations

import redis
from redis.exceptions import RedisError

from app.core.config import settings


def _redis_client() -> redis.Redis | None:
    try:
        r = redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        return r
    except RedisError:
        return None


def cancel_key_for_batch(batch_id: str) -> str:
    return f"vocalflow:cancel:batch:{batch_id}"


def request_cancel_batch(batch_id: str, *, ttl_seconds: int = 24 * 60 * 60) -> bool:
    r = _redis_client()
    if r is None:
        return False
    try:
        r.set(cancel_key_for_batch(batch_id), "1", ex=int(ttl_seconds))
        return True
    except Exception:
        return False


def is_cancel_requested(batch_id: str) -> bool:
    r = _redis_client()
    if r is None:
        return False
    try:
        return bool(r.get(cancel_key_for_batch(batch_id)))
    except Exception:
        return False

