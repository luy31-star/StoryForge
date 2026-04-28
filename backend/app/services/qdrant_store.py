from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        collection: str | None = None,
        vector_size: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.qdrant_url).rstrip("/")
        self.api_key = api_key or settings.qdrant_api_key
        self.collection = collection or settings.novel_qdrant_collection
        self.vector_size = max(8, int(vector_size or settings.novel_embedding_dimension))
        self.timeout = float(timeout or settings.novel_retrieval_timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def healthcheck(self) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self._url("/healthz"), headers=self._headers())
                return resp.status_code == 200
        except Exception:
            logger.exception("qdrant healthcheck failed")
            return False

    def ensure_collection(self, *, distance: str = "Cosine") -> None:
        payload = {
            "vectors": {
                "size": self.vector_size,
                "distance": distance,
            }
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.put(
                    self._url(f"/collections/{self.collection}"),
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code == 409:
                    logger.info(
                        "qdrant collection already exists | collection=%s size=%s",
                        self.collection,
                        self.vector_size,
                    )
                    return
                resp.raise_for_status()
        except Exception:
            logger.exception(
                "qdrant ensure_collection failed | collection=%s size=%s",
                self.collection,
                self.vector_size,
            )
            raise

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        payload = {"points": points}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.put(
                self._url(f"/collections/{self.collection}/points"),
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()

    def delete_points_by_filter(self, filter_payload: dict[str, Any]) -> None:
        if not filter_payload:
            return
        payload = {"filter": filter_payload}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                self._url(f"/collections/{self.collection}/points/delete"),
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()

    def delete_points_by_ids(self, point_ids: list[Any]) -> None:
        if not point_ids:
            return
        payload = {"points": list(point_ids)}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                self._url(f"/collections/{self.collection}/points/delete"),
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()

    def search(
        self,
        vector: list[float],
        *,
        limit: int | None = None,
        filter_payload: dict[str, Any] | None = None,
        with_payload: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "vector": vector,
            "limit": int(limit or settings.novel_retrieval_top_k),
            "with_payload": with_payload,
        }
        if filter_payload:
            payload["filter"] = filter_payload

        started = time.perf_counter()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                self._url(f"/collections/{self.collection}/points/search"),
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if isinstance(data, dict):
            data.setdefault("elapsed_ms", elapsed_ms)
        return data


def ensure_novel_qdrant_collection() -> None:
    if not settings.novel_rag_enabled:
        return
    store = QdrantStore()
    store.ensure_collection()
    logger.info(
        "qdrant ready | url=%s collection=%s dim=%s",
        settings.qdrant_url,
        settings.novel_qdrant_collection,
        settings.novel_embedding_dimension,
    )
